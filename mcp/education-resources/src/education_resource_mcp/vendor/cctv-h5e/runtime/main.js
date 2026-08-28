// src/cli/main.ts
import * as fsPromises from "node:fs/promises";
import * as path2 from "node:path";

// src/cmdutil.ts
var logFunc = (type, content) => {
  switch (type) {
    case 0 /* DEBUG */:
      console.debug(content);
      break;
    case 1 /* LOG */:
      console.log(content);
      break;
    case 2 /* WARN */:
      console.warn(content);
      break;
    case 3 /* ERROR */:
      console.error(content);
      break;
  }
};
var noLog = false;
function setNoLog(v) {
  noLog = v;
}
function log(content) {
  if (noLog)
    return;
  logFunc(1 /* LOG */, content);
}
function error(content) {
  if (noLog)
    return;
  logFunc(3 /* ERROR */, content);
}

// src/util.ts
async function getURLAsUint8Array(url, fetchOptions) {
  const response = await fetch(url, fetchOptions);
  if (!response.ok)
    throw new Error(`URL returned error: ${response.status} ${response.statusText}`);
  return new Uint8Array(await response.arrayBuffer());
}
async function getURLAsText(url, fetchOptions) {
  const response = await fetch(url, fetchOptions);
  if (!response.ok)
    throw new Error(`URL returned error: ${response.status} ${response.statusText}`);
  return await response.text();
}
async function getURLAsJSON(url, fetchOptions) {
  const response = await fetch(url, fetchOptions);
  if (!response.ok)
    throw new Error(`URL returned error: ${response.status} ${response.statusText}`);
  return await response.json();
}
async function getM3U8FromWebPage(url, resolution, fetchOptions) {
  if (!Number.isInteger(resolution))
    throw new Error("resolution not integer");
  const webpageContent = await getURLAsText(url, fetchOptions);
  let guid;
  for (const line of webpageContent.split("\n")) {
    if (!line.match(/var\s+(?:video_)?guid\s*=/))
      continue;
    guid = line.replace(/.*(["'])(.*)\1.*/, "$2").trim();
    break;
  }
  if (!guid)
    throw new Error("no guid found in webpage provided");
  return await getM3U8FromGUID(guid, resolution, fetchOptions);
}
async function getM3U8FromGUID(guid, resolution, fetchOptions) {
  if (!Number.isInteger(resolution))
    throw new Error("resolution not integer");
  log(`got guid "${guid}"`);
  const videoInfo = await getURLAsJSON(
    `https://vdn.apps.cntv.cn/api/getHttpVideoInfo.do?pid=${guid}`,
    fetchOptions
  );
  if (videoInfo.ack === "no")
    throw new Error(`invalid guid "${guid}"`);
  const ret = videoInfo.manifest.hls_h5e_url.replace(/main/g, resolution.toString()).replace(/\?.*/, "");
  log(`got link "${ret}"`);
  return ret;
}
var Queue = class {
  arr = [];
  getPromiseResolves = [];
  putPromiseResolves = [];
  maxSize;
  constructor(maxSize = 10) {
    this.maxSize = maxSize;
  }
  get currentSize() {
    return this.arr.length;
  }
  async get() {
    if (!this.arr.length)
      await new Promise(
        (resolve) => this.getPromiseResolves.push(resolve)
      );
    this.putPromiseResolves.shift()?.();
    return this.arr.shift();
  }
  async put(el) {
    if (this.arr.length >= this.maxSize)
      await new Promise(
        (resolve) => this.putPromiseResolves.push(resolve)
      );
    this.getPromiseResolves.shift()?.();
    this.arr.push(el);
  }
};
async function* getTsFromM3U8(url, queueCallback, maxCache = 10, fetchOptions) {
  async function backgroundFetcher(urls2, queue2) {
    for (const i in urls2) {
      await queue2.put(await getURLAsUint8Array(urls2[i]));
      queueCallback?.({
        currentSlice: Number(i),
        currentSize: queue2.currentSize,
        maxSize: queue2.maxSize
      });
    }
  }
  const m3u8Content = await getURLAsText(url, fetchOptions);
  const queue = new Queue(maxCache);
  const urls = m3u8Content.split(/\n/).filter((l) => l && !l.startsWith("#")).map((e) => new URL(e, url));
  backgroundFetcher(urls, queue);
  for (const i in urls) {
    yield {
      buffer: await queue.get(),
      currentSlice: Number(i),
      totalSlice: urls.length
    };
    queueCallback?.({
      currentSlice: null,
      currentSize: queue.currentSize,
      maxSize: queue.maxSize
    });
  }
}

// src/worker/worker-type.ts
var isNode = typeof process === "object" && typeof process.versions === "object" && typeof process.versions.node === "string";

// src/worker/wrapper.ts
var fs;
var os;
var path;
var workerThreads;
if (isNode) {
  fs = await import("node:fs");
  os = await import("node:os");
  path = await import("node:path");
  workerThreads = await import("node:worker_threads");
}
var DecryptWorkerWrapper = class {
  worker;
  callbacks = [];
  constructor(errorCallback = (e) => {
  }) {
    if (isNode) {
      let workerFilename = null;
      const joiner = (e) => path.join(import.meta.dirname, e);
      for (const i of [
        "../worker/worker.ts",
        // running from repo
        "../worker/worker.js",
        // running from build
        "./worker.js"
        // bundled
      ]) {
        try {
          fs.accessSync(joiner(i));
        } catch (e) {
          continue;
        }
        workerFilename = i;
        break;
      }
      if (workerFilename === null)
        throw new Error("Worker file not found; check you've downloaded all required files correctly.");
      const options = {};
      if (workerFilename.endsWith(".ts"))
        options.execArgv = "-r tsx".split(/ /);
      this.worker = new workerThreads.Worker(joiner(workerFilename), options);
      this.worker.on("message", (e) => {
        this.onMessage(e);
      });
      this.worker.on("error", errorCallback);
    } else {
      this.worker = new Worker("js/worker/worker.js", { type: "module" });
      this.worker.addEventListener("message", (e) => {
        this.onMessage(e);
      });
      this.worker.addEventListener("error", errorCallback);
    }
  }
  sendMessage(type, payload, transferArr = []) {
    if (!this.worker)
      throw new Error("Worker has died");
    this.worker.postMessage({ type, payload }, transferArr);
  }
  onMessage(e) {
    const d = isNode ? e : e.data;
    switch (d.type) {
      case 0 /* WANT_DECRYPT */:
      case 2 /* PUSH_WORKER_ENCRYPTED_BUFFER */:
      case 4 /* FINISH_DECRYPT */:
        error("this message is not intended to be sent to the main thread");
        break;
      case 1 /* CAN_PUSH_ENCRYPTED_BUFFER */:
        this.callbacks.shift()?.[0]();
        break;
      case 3 /* PUSH_MAIN_THREAD_DECRYPTED_BUFFER */:
        this.callbacks.shift()?.[0](d.payload.buffer);
        break;
      case 5 /* FINISH_DESTROYING */:
        this.callbacks.shift()?.[0]();
        break;
      case 7 /* DECRYPT_ERROR */:
        this.callbacks.shift()?.[1](d.payload.message);
        break;
    }
  }
  startDecrypt() {
    return new Promise((resolve, reject) => {
      this.callbacks.push([resolve, reject]);
      this.sendMessage(0 /* WANT_DECRYPT */);
    });
  }
  endDecrypt() {
    return new Promise((resolve, reject) => {
      this.callbacks.push([resolve, reject]);
      this.sendMessage(4 /* FINISH_DECRYPT */);
    });
  }
  terminate() {
    if (!this.worker)
      throw new Error("Worker has died");
    const r = this.worker.terminate();
    this.worker = null;
    return Promise.resolve(r);
  }
  decryptTsBuffer(buffer) {
    return new Promise((resolve, reject) => {
      this.callbacks.push([resolve, reject]);
      this.sendMessage(
        2 /* PUSH_WORKER_ENCRYPTED_BUFFER */,
        { buffer, isNALU: false },
        [buffer.buffer]
      );
    });
  }
  decryptNALU(buffer) {
    return new Promise((resolve, reject) => {
      this.callbacks.push([resolve, reject]);
      this.sendMessage(
        2 /* PUSH_WORKER_ENCRYPTED_BUFFER */,
        { buffer, isNALU: true },
        [buffer.buffer]
      );
    });
  }
};

// src/cli/main.ts
async function* getTsFromM3U8File(filename, queueCallback, maxCache = 10) {
  async function backgroundFetcher(urls2, queue2) {
    for (const i in urls2) {
      await queue2.put(await fsPromises.readFile(urls2[i]));
      queueCallback?.({
        currentSlice: Number(i),
        currentSize: queue2.currentSize,
        maxSize: queue2.maxSize
      });
    }
  }
  const m3u8Content = await fsPromises.readFile(filename, { encoding: "utf8" });
  const queue = new Queue(maxCache);
  const urls = m3u8Content.split(/\n/).filter((l) => l && !l.startsWith("#")).map((e) => path2.join(path2.dirname(filename), e));
  backgroundFetcher(urls, queue);
  for (const i in urls) {
    yield {
      buffer: await queue.get(),
      currentSlice: Number(i),
      totalSlice: urls.length
    };
    queueCallback?.({
      currentSlice: null,
      currentSize: queue.currentSize,
      maxSize: queue.maxSize
    });
  }
}
function usage() {
  error("usage: main.js [--quiet] [--version] [--get-m3u8] [--get-guid <resolution>] [--local-m3u8] [--cache-slice <number>] {local.m3u8 | in.ts | url} out.ts");
  process.exit(1);
}
async function main() {
  let getM3U8 = false;
  let getGUID = false;
  let localM3U8 = false;
  let guidResolution = -1;
  let cacheSlice = 10;
  let decryptWorkerWrapper = new DecryptWorkerWrapper(
    (e) => {
      error("Worker \u51FA\u73B0\u9519\u8BEF");
      error(e);
      process.exit(1);
    }
  );
  process.stdin.setEncoding("utf8");
  if (process.argv.length >= 3 && process.argv[2] === "--quiet") {
    setNoLog(true);
    process.argv.splice(2, 1);
  }
  if (process.argv.length >= 3 && process.argv[2] === "--version") {
    log("cctv-h5e-decrypt version 1.1.1");
    process.exit(0);
  }
  if (process.argv.length >= 3 && process.argv[2] === "--get-m3u8") {
    getM3U8 = true;
    process.argv.splice(2, 1);
  }
  if (process.argv.length >= 4 && process.argv[2] === "--get-guid") {
    getGUID = true;
    guidResolution = Number(process.argv[3]);
    process.argv.splice(2, 2);
  }
  if (process.argv.length >= 3 && process.argv[2] === "--local-m3u8") {
    localM3U8 = true;
    process.argv.splice(2, 1);
  }
  if (process.argv.length >= 4 && process.argv[2] === "--cache-slice") {
    cacheSlice = Number(process.argv[3]);
    process.argv.splice(2, 1);
  }
  if (Number(getM3U8) + Number(getGUID) + Number(localM3U8) > 1) {
    error("use only one of --get-m3u8, --get-guid or --local-m3u8");
    process.exit(1);
  }
  if (process.argv.length >= 3 && process.argv[2] === "--help")
    usage();
  if (process.argv.length !== 4)
    usage();
  await Promise.all([
    fsPromises.rm(process.argv[3], { force: true }),
    decryptWorkerWrapper.startDecrypt()
  ]);
  if (cacheSlice < 1 || cacheSlice > 100)
    throw new Error("invalid cache slice size");
  if (getM3U8) {
    log(`decrypting from m3u8 direct link "${process.argv[2]}"...`);
    for await (const { buffer, currentSlice, totalSlice } of getTsFromM3U8(
      process.argv[2],
      (e) => {
        if (e.currentSlice !== null)
          log(`downloading slice ${e.currentSlice}.ts...`);
      },
      cacheSlice
    )) {
      log(`decrypting slice ${currentSlice}.ts...`);
      await fsPromises.writeFile(
        process.argv[3],
        await decryptWorkerWrapper.decryptTsBuffer(buffer),
        { flag: "a" }
      );
    }
  } else if (getGUID) {
    log(`decrypting from video page link "${process.argv[2]}" with resolution "${guidResolution}"...`);
    for await (const { buffer, currentSlice, totalSlice } of getTsFromM3U8(
      await getM3U8FromWebPage(process.argv[2], guidResolution),
      (e) => {
        if (e.currentSlice !== null)
          log(`downloading slice ${e.currentSlice}.ts...`);
      },
      cacheSlice
    )) {
      log(`decrypting slice ${currentSlice}.ts...`);
      await fsPromises.writeFile(
        process.argv[3],
        await decryptWorkerWrapper.decryptTsBuffer(buffer),
        { flag: "a" }
      );
    }
  } else if (localM3U8) {
    log(`decrypting from local m3u8 ${process.argv[2]}`);
    for await (const { buffer, currentSlice, totalSlice } of getTsFromM3U8File(
      process.argv[2],
      (e) => {
        if (e.currentSlice !== null)
          log(`downloading slice ${e.currentSlice}.ts...`);
      },
      cacheSlice
    )) {
      log(`decrypting slice ${currentSlice}.ts...`);
      await fsPromises.writeFile(
        process.argv[3],
        await decryptWorkerWrapper.decryptTsBuffer(buffer),
        { flag: "a" }
      );
    }
  } else {
    log(`decrypting file ${process.argv[2]}...`);
    let b;
    try {
      b = await fsPromises.readFile(process.argv[2]);
    } catch (e) {
      if (e instanceof Error && e.code !== "ERR_FS_FILE_TOO_LARGE")
        throw e;
      error("this file is too large to be read by node.js in oneshot, try using local-m3u8 mode.");
      process.exit(1);
    }
    const buffer = new Uint8Array(b.buffer, b.byteOffset, b.length);
    await fsPromises.writeFile(
      process.argv[3],
      await decryptWorkerWrapper.decryptTsBuffer(buffer),
      { flag: "a" }
    );
  }
  log("done");
  await decryptWorkerWrapper.endDecrypt();
  await decryptWorkerWrapper.terminate();
}
main();
//# sourceMappingURL=main.js.map

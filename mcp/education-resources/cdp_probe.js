// CDP probe for the OpenClaw controlled browser (port 18800).
// Usage: node cdp_probe.js <action> [jsonArgs]
//   actions: cookies | localstorage | eval | screenshot | url
const http = require("http");

const CDP_PORT = 18800;

function getJson(path) {
  return new Promise((resolve, reject) => {
    http
      .get({ host: "127.0.0.1", port: CDP_PORT, path }, (res) => {
        let body = "";
        res.on("data", (c) => (body += c));
        res.on("end", () => {
          try {
            resolve(JSON.parse(body));
          } catch (e) {
            reject(new Error("bad json: " + body.slice(0, 200)));
          }
        });
      })
      .on("error", reject);
  });
}

async function main() {
  const action = process.argv[2];
  const list = await getJson("/json/list");
  const page = list.find((t) => t.type === "page");
  if (!page) throw new Error("no page target");
  const ws = new WebSocket(page.webSocketDebuggerUrl);
  let seq = 0;
  const pending = new Map();
  ws.onmessage = (ev) => {
    const msg = JSON.parse(ev.data);
    if (msg.id && pending.has(msg.id)) {
      pending.get(msg.id)(msg);
      pending.delete(msg.id);
    }
  };
  const send = (method, params = {}) =>
    new Promise((resolve) => {
      const id = ++seq;
      pending.set(id, resolve);
      ws.send(JSON.stringify({ id, method, params }));
    });
  await new Promise((res) => (ws.onopen = res));

  if (action === "cookies") {
    const r = await send("Storage.getCookies");
    const cookies = (r.result?.cookies || []).map((c) => ({
      name: c.name, value: c.value, domain: c.domain, path: c.path,
      expires: c.expires, httpOnly: c.httpOnly, secure: c.secure,
      sameSite: c.sameSite,
    }));
    console.log(JSON.stringify(cookies));
  } else if (action === "localstorage") {
    const r = await send("Runtime.evaluate", {
      expression: "JSON.stringify(localStorage)",
      returnByValue: true,
    });
    console.log(r.result?.result?.value || "{}");
  } else if (action === "sessionstorage") {
    const r = await send("Runtime.evaluate", {
      expression: "JSON.stringify(sessionStorage)",
      returnByValue: true,
    });
    console.log(r.result?.result?.value || "{}");
  } else if (action === "eval") {
    const r = await send("Runtime.evaluate", {
      expression: process.argv[3] || "document.title",
      returnByValue: true,
      awaitPromise: true,
    });
    console.log(JSON.stringify(r.result?.result?.value ?? r));
  } else if (action === "screenshot") {
    const r = await send("Page.captureScreenshot", { format: "png" });
    const fs = require("fs");
    fs.writeFileSync(process.argv[3] || "shot.png", Buffer.from(r.result?.data || "", "base64"));
    console.log("saved " + (process.argv[3] || "shot.png"));
  } else if (action === "url") {
    const r = await send("Runtime.evaluate", { expression: "location.href", returnByValue: true });
    console.log(r.result?.result?.value);
  }
  ws.close();
  process.exit(0);
}

main().catch((e) => {
  console.error("ERR:", e.message);
  process.exit(1);
});

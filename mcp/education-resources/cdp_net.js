// Capture network traffic of the current page for N seconds.
// Usage: node cdp_net.js <seconds>
const http = require("http");
const CDP_PORT = 18800;

function getJson(path) {
  return new Promise((resolve, reject) => {
    http.get({ host: "127.0.0.1", port: CDP_PORT, path }, (res) => {
      let b = "";
      res.on("data", (c) => (b += c));
      res.on("end", () => resolve(JSON.parse(b)));
    }).on("error", reject);
  });
}

async function main() {
  const seconds = parseInt(process.argv[2] || "15", 10);
  const list = await getJson("/json/list");
  const page = list.find((t) => t.type === "page");
  const ws = new WebSocket(page.webSocketDebuggerUrl);
  let seq = 0;
  const pending = new Map();
  const requests = new Map();
  const setCookies = [];
  ws.onmessage = (ev) => {
    const m = JSON.parse(ev.data);
    if (m.id && pending.has(m.id)) {
      pending.get(m.id)(m);
      pending.delete(m.id);
    } else if (m.method === "Network.requestWillBeSent") {
      requests.set(m.params.requestId, { url: m.params.request.url, headers: m.params.request.headers || {} });
    } else if (m.method === "Network.responseReceived") {
      const r = requests.get(m.params.requestId);
      if (r) r.status = m.params.response.status;
    } else if (m.method === "Network.responseReceivedExtraInfo") {
      const sc = m.params.headers["set-cookie"];
      if (sc) {
        const r = requests.get(m.params.requestId);
        setCookies.push({ from: r ? r.url.slice(0, 90) : "?", cookie: String(sc).slice(0, 120) });
      }
    }
  };
  const send = (method, params = {}) =>
    new Promise((res) => {
      const id = ++seq;
      pending.set(id, res);
      ws.send(JSON.stringify({ id, method, params }));
    });
  await new Promise((res) => (ws.onopen = res));
  await send("Network.enable");
  await send("Page.enable");
  await send("Page.reload", { ignoreCache: true });
  await new Promise((res) => setTimeout(res, seconds * 1000));
  console.log("=== requests (ximalaya relevant) ===");
  for (const [id, r] of requests) {
    if (/ximalaya|xmcdn/i.test(r.url) && !/\.(png|jpg|jpeg|webp|gif|css|woff2?|svg)/.test(r.url)) {
      console.log((r.status || "?") + " " + r.url.slice(0, 110));
    }
  }
  console.log("=== set-cookie (webtk?) ===");
  for (const s of setCookies) {
    console.log(s.from.slice(0, 60) + "  =>  " + s.cookie);
  }
  ws.close();
  process.exit(0);
}

main().catch((e) => {
  console.error("ERR:", e.message);
  process.exit(1);
});

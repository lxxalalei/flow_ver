#!/usr/bin/env node
"use strict";

const fs = require("fs");
const https = require("https");
const zlib = require("zlib");

const MAX_RESULTS = 50;
const SEARCH_HOST = "https://weixin.sogou.com";

const USER_AGENTS = [
  "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36",
  "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Edg/125.0.0.0 Chrome/125.0.0.0 Safari/537.36",
  "Mozilla/5.0 (Macintosh; Intel Mac OS X 14_5) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.5 Safari/605.1.15",
  "Mozilla/5.0 (X11; Linux x86_64; rv:126.0) Gecko/20100101 Firefox/126.0",
  "Mozilla/5.0 (iPhone; CPU iPhone OS 17_5 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.5 Mobile/15E148 Safari/604.1",
];

function randomUserAgent() {
  return USER_AGENTS[Math.floor(Math.random() * USER_AGENTS.length)];
}

function sleep(ms) {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

function decompress(buffer, encoding) {
  const normalized = String(encoding || "").toLowerCase();
  try {
    if (normalized.includes("gzip")) return zlib.gunzipSync(buffer);
    if (normalized.includes("deflate")) return zlib.inflateSync(buffer);
    if (normalized.includes("br")) return zlib.brotliDecompressSync(buffer);
  } catch {
    return buffer;
  }
  return buffer;
}

function request(url, options = {}) {
  const timeoutMs = Number(options.timeoutMs || 15000);
  const headers = {
    Accept: "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Encoding": "identity",
    "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
    "User-Agent": randomUserAgent(),
    ...options.headers,
  };

  return new Promise((resolve, reject) => {
    const target = new URL(url);
    const req = https.request({
      hostname: target.hostname,
      path: target.pathname + target.search,
      method: options.method || "GET",
      headers,
    }, (res) => {
      const chunks = [];
      res.on("data", (chunk) => chunks.push(chunk));
      res.on("end", () => {
        const body = decompress(Buffer.concat(chunks), res.headers["content-encoding"]);
        resolve({
          statusCode: res.statusCode || 0,
          headers: res.headers,
          text: body.toString("utf-8"),
        });
      });
    });

    req.on("error", reject);
    req.setTimeout(timeoutMs, () => {
      req.destroy(new Error("Request timeout"));
    });
    req.end();
  });
}

function extractCookies(headers) {
  const setCookie = headers["set-cookie"];
  if (!Array.isArray(setCookie)) return "";
  return setCookie
    .map((value) => String(value).split(";")[0].trim())
    .filter(Boolean)
    .join("; ");
}

async function getSogouCookie() {
  if (process.env.SOGOU_WEIXIN_COOKIE) {
    return process.env.SOGOU_WEIXIN_COOKIE;
  }
  try {
    const response = await request("https://v.sogou.com/v?ie=utf8&query=&p=40030600", {
      timeoutMs: 10000,
    });
    return extractCookies(response.headers);
  } catch {
    return "";
  }
}

function isBlockedPage(html) {
  return /antispider|captcha|请输入验证码|验证码|安全验证|访问过于频繁/i.test(html || "");
}

function decodeHtml(value) {
  return String(value || "")
    .replace(/&#(\d+);/g, (_, code) => String.fromCharCode(Number(code)))
    .replace(/&#x([0-9a-f]+);/gi, (_, code) => String.fromCharCode(parseInt(code, 16)))
    .replace(/&quot;/g, '"')
    .replace(/&apos;/g, "'")
    .replace(/&#39;/g, "'")
    .replace(/&lt;/g, "<")
    .replace(/&gt;/g, ">")
    .replace(/&amp;/g, "&")
    .replace(/&nbsp;/g, " ");
}

function stripTags(value) {
  return String(value || "").replace(/<[^>]+>/g, " ");
}

function cleanText(value) {
  return decodeHtml(stripTags(value)).replace(/\s+/g, " ").trim();
}

function absoluteUrl(url) {
  if (!url) return "";
  try {
    return new URL(decodeHtml(url), SEARCH_HOST).toString();
  } catch {
    return "";
  }
}

function formatChinaTime(date) {
  const china = new Date(date.getTime() + 8 * 60 * 60 * 1000);
  const pad = (value) => String(value).padStart(2, "0");
  return [
    china.getUTCFullYear(),
    pad(china.getUTCMonth() + 1),
    pad(china.getUTCDate()),
  ].join("-") + " " + [
    pad(china.getUTCHours()),
    pad(china.getUTCMinutes()),
    pad(china.getUTCSeconds()),
  ].join(":");
}

function dateDescription(date) {
  const diffMs = Date.now() - date.getTime();
  const minutes = Math.floor(diffMs / 60000);
  const hours = Math.floor(minutes / 60);
  const days = Math.floor(hours / 24);
  if (days > 0) return `${days}天前`;
  if (hours > 0) return `${hours}小时前`;
  if (minutes > 0) return `${minutes}分钟前`;
  return "刚刚";
}

function parseDateFromBlock(block) {
  const timestampMatch = block.match(/(\d{10})/);
  if (timestampMatch) {
    const date = new Date(Number(timestampMatch[1]) * 1000);
    return {
      datetime: formatChinaTime(date),
      date_text: formatChinaTime(date).slice(0, 10),
      date_description: dateDescription(date),
    };
  }
  const text = cleanText(block);
  return {
    datetime: "",
    date_text: text,
    date_description: text,
  };
}

function attrValue(tag, name) {
  const match = String(tag || "").match(new RegExp(`${name}\\s*=\\s*(["'])(.*?)\\1`, "i"));
  return match ? match[2] : "";
}

function firstMatch(block, pattern) {
  const match = String(block || "").match(pattern);
  return match ? match[1] : "";
}

function parseArticle(block, rank) {
  const titleAnchor = firstMatch(block, /<h3[^>]*>\s*(<a\b[\s\S]*?<\/a>)\s*<\/h3>/i);
  if (!titleAnchor) return null;
  const startTag = firstMatch(titleAnchor, /(<a\b[^>]*>)/i);
  const title = cleanText(titleAnchor);
  const url = absoluteUrl(attrValue(startTag, "href"));
  if (!title || !url) return null;

  const sourceBlock = firstMatch(block, /<div[^>]+class=["'][^"']*\bs-p\b[^"']*["'][^>]*>([\s\S]*?)<\/div>/i);
  const source =
    cleanText(firstMatch(sourceBlock, /<a[^>]+class=["'][^"']*\baccount\b[^"']*["'][^>]*>([\s\S]*?)<\/a>/i)) ||
    cleanText(firstMatch(sourceBlock, /<span[^>]+class=["'][^"']*\ball-time-y2\b[^"']*["'][^>]*>([\s\S]*?)<\/span>/i));
  const date = parseDateFromBlock(sourceBlock);

  return {
    title,
    url,
    summary: cleanText(firstMatch(block, /<p[^>]+class=["'][^"']*\btxt-info\b[^"']*["'][^>]*>([\s\S]*?)<\/p>/i)),
    datetime: date.datetime,
    date_text: date.date_text,
    date_description: date.date_description,
    source,
    rank,
  };
}

function parseSearchPage(html, startRank, limit) {
  if (isBlockedPage(html)) {
    throw new Error("SEARCH_BLOCKED: sogou weixin captcha or antispider page");
  }

  const listMatch = String(html || "").match(/<ul[^>]+class=["'][^"']*\bnews-list\b[^"']*["'][^>]*>([\s\S]*?)<\/ul>/i);
  const listHtml = listMatch ? listMatch[1] : html;
  const items = [];
  const liPattern = /<li\b[^>]*>([\s\S]*?)<\/li>/gi;
  let match;
  while ((match = liPattern.exec(listHtml)) && items.length < limit) {
    const article = parseArticle(match[1], startRank + items.length);
    if (article) items.push(article);
  }
  return items;
}

function extractRedirectUrl(html) {
  const meta = String(html || "").match(/<meta[^>]+http-equiv=["']refresh["'][^>]+url=([^"']+)["']/i);
  if (meta) return meta[1];
  const js = String(html || "").match(/(?:location\.href|window\.location|location)\s*=\s*["']([^"']+)["']/i);
  if (js) return js[1];

  const parts = [];
  for (const match of String(html || "").matchAll(/url\s*\+=\s*["']([^"']*)["']/g)) {
    parts.push(match[1]);
  }
  const joined = parts.join("");
  return joined.includes("mp.weixin.qq.com") ? joined : "";
}

async function resolveRealUrl(url, cookie) {
  if (!url.includes("weixin.sogou.com")) return { url, resolved: true };
  try {
    const response = await request(url, {
      timeoutMs: 7000,
      headers: cookie ? { Cookie: cookie } : {},
    });
    const location = response.headers.location;
    if (response.statusCode >= 300 && response.statusCode < 400 && location) {
      const target = absoluteUrl(location);
      if (target.includes("mp.weixin.qq.com")) return { url: target, resolved: true };
    }
    const redirect = extractRedirectUrl(response.text);
    if (redirect && redirect.includes("mp.weixin.qq.com")) {
      return { url: redirect, resolved: true };
    }
  } catch {
    return { url, resolved: false };
  }
  return { url, resolved: false };
}

async function searchWechatArticles(query, maxResults = 10, resolveUrl = false) {
  const limit = Math.min(Math.max(Number(maxResults) || 10, 1), MAX_RESULTS);
  const pages = Math.ceil(limit / 10);
  const cookie = await getSogouCookie();
  const articles = [];

  for (let page = 1; page <= pages && articles.length < limit; page += 1) {
    const remaining = limit - articles.length;
    const url = `${SEARCH_HOST}/weixin?query=${encodeURIComponent(query)}&s_from=input&_sug_=n&type=2&page=${page}&ie=utf8`;
    const response = await request(url, {
      timeoutMs: 30000,
      headers: {
        Host: "weixin.sogou.com",
        Referer: "https://weixin.sogou.com/",
        ...(cookie ? { Cookie: cookie } : {}),
      },
    });
    if (response.statusCode >= 400) {
      throw new Error(`HTTP_${response.statusCode}: sogou weixin search failed`);
    }
    articles.push(...parseSearchPage(response.text, articles.length + 1, remaining));
    if (page < pages) await sleep(500 + Math.random() * 1000);
  }

  if (!resolveUrl) return articles.slice(0, limit);

  const resolved = [];
  for (const article of articles.slice(0, limit)) {
    const real = await resolveRealUrl(article.url, cookie);
    resolved.push({
      ...article,
      url: real.url,
      url_resolved: real.resolved,
    });
    await sleep(300 + Math.random() * 700);
  }
  return resolved;
}

function parseArgs(argv) {
  const positionals = [];
  let num = 10;
  let output = "";
  let resolveUrl = false;

  for (let index = 0; index < argv.length; index += 1) {
    const value = argv[index];
    if (value === "-n" || value === "--num") {
      num = Number(argv[index + 1] || 10);
      index += 1;
    } else if (value === "-o" || value === "--output") {
      output = argv[index + 1] || "";
      index += 1;
    } else if (value === "-r" || value === "--resolve-url") {
      resolveUrl = true;
    } else if (!value.startsWith("-")) {
      positionals.push(value);
    }
  }

  return {
    query: positionals.join(" ").trim(),
    num,
    output,
    resolveUrl,
  };
}

async function main() {
  const args = parseArgs(process.argv.slice(2));
  if (!args.query) {
    console.error("Usage: node search_wechat.js <query> [-n count] [-o file] [-r]");
    process.exit(2);
  }

  try {
    const articles = await searchWechatArticles(args.query, args.num, args.resolveUrl);
    const payload = {
      query: args.query,
      total: articles.length,
      articles,
    };
    const text = JSON.stringify(payload, null, 2);
    if (args.output) {
      fs.writeFileSync(args.output, `${text}\n`, "utf-8");
    }
    process.stdout.write(`${text}\n`);
  } catch (error) {
    console.error(error && error.message ? error.message : String(error));
    process.exit(1);
  }
}

module.exports = { searchWechatArticles, parseSearchPage };

if (require.main === module) {
  main();
}

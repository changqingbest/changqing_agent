import http from "node:http";
import { readFile } from "node:fs/promises";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { Agent } from "./agent/agent.js";
import { OpenAICompatibleProvider } from "./agent/provider.js";
import {
  addMessage,
  createConversation,
  deleteConversation,
  getConversation,
  listConversations,
} from "./store.js";

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
const publicDir = path.join(root, "public");
const port = Number(process.env.PORT || 3000);
const provider = new OpenAICompatibleProvider({
  apiKey: process.env.OPENAI_API_KEY || "",
  baseUrl: process.env.OPENAI_BASE_URL || "https://api.openai.com/v1",
  model: process.env.OPENAI_MODEL || "gpt-4.1-mini",
});
const agent = new Agent({
  provider,
  systemPrompt: process.env.SYSTEM_PROMPT || "你是常青 Agent。回答准确、简洁；需要时主动调用工具。",
});

const mime = {
  ".html": "text/html; charset=utf-8",
  ".css": "text/css; charset=utf-8",
  ".js": "text/javascript; charset=utf-8",
  ".svg": "image/svg+xml",
};

function json(response, status, body) {
  response.writeHead(status, { "content-type": "application/json; charset=utf-8" });
  response.end(JSON.stringify(body));
}

async function readJson(request) {
  const chunks = [];
  for await (const chunk of request) chunks.push(chunk);
  return JSON.parse(Buffer.concat(chunks).toString("utf8") || "{}");
}

function sendEvent(response, event) {
  response.write(`data: ${JSON.stringify(event)}\n\n`);
}

async function api(request, response, url) {
  if (request.method === "GET" && url.pathname === "/api/status") {
    return json(response, 200, { mode: provider.isDemo ? "demo" : "model", model: provider.model });
  }
  if (request.method === "GET" && url.pathname === "/api/conversations") {
    return json(response, 200, await listConversations());
  }
  if (request.method === "POST" && url.pathname === "/api/conversations") {
    return json(response, 201, await createConversation());
  }

  const match = url.pathname.match(/^\/api\/conversations\/([^/]+)$/);
  if (match && request.method === "GET") {
    const item = await getConversation(match[1]);
    return item ? json(response, 200, item) : json(response, 404, { error: "会话不存在" });
  }
  if (match && request.method === "DELETE") {
    return json(response, (await deleteConversation(match[1])) ? 200 : 404, { ok: true });
  }

  if (request.method === "POST" && url.pathname === "/api/chat") {
    const { conversationId, message } = await readJson(request);
    if (!conversationId || !message?.trim()) return json(response, 400, { error: "参数不完整" });
    const conversation = await addMessage(conversationId, { role: "user", content: message.trim() });

    response.writeHead(200, {
      "content-type": "text/event-stream; charset=utf-8",
      "cache-control": "no-cache",
      connection: "keep-alive",
    });
    try {
      const answer = await agent.run(conversation.messages, (event) => sendEvent(response, event));
      await addMessage(conversationId, { role: "assistant", content: answer });
      sendEvent(response, { type: "done" });
    } catch (error) {
      sendEvent(response, { type: "error", value: error.message });
    }
    return response.end();
  }
  return false;
}

async function serveStatic(response, pathname) {
  const relative = pathname === "/" ? "index.html" : pathname.slice(1);
  const target = path.resolve(publicDir, relative);
  if (!target.startsWith(publicDir + path.sep) && target !== path.join(publicDir, "index.html")) return false;
  try {
    const body = await readFile(target);
    response.writeHead(200, { "content-type": mime[path.extname(target)] || "application/octet-stream" });
    response.end(body);
    return true;
  } catch (error) {
    if (error.code === "ENOENT") return false;
    throw error;
  }
}

const server = http.createServer(async (request, response) => {
  try {
    const url = new URL(request.url, `http://${request.headers.host}`);
    if (url.pathname.startsWith("/api/")) {
      const handled = await api(request, response, url);
      if (handled !== false) return;
    } else if (await serveStatic(response, url.pathname)) return;
    json(response, 404, { error: "Not found" });
  } catch (error) {
    if (!response.headersSent) json(response, 500, { error: error.message });
    else response.end();
  }
});

server.listen(port, "127.0.0.1", () => {
  console.log(`Changqing Agent: http://127.0.0.1:${port}`);
  console.log(`Mode: ${provider.isDemo ? "demo" : `${provider.model}`}`);
});

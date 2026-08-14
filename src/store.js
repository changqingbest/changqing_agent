import { mkdir, readFile, writeFile } from "node:fs/promises";
import path from "node:path";
import crypto from "node:crypto";

const dataDir = path.resolve("data");
const dataFile = path.join(dataDir, "conversations.json");

async function load() {
  try {
    return JSON.parse(await readFile(dataFile, "utf8"));
  } catch (error) {
    if (error.code === "ENOENT") return [];
    throw error;
  }
}

async function save(conversations) {
  await mkdir(dataDir, { recursive: true });
  await writeFile(dataFile, JSON.stringify(conversations, null, 2), "utf8");
}

export async function listConversations() {
  const items = await load();
  return items
    .map(({ id, title, createdAt, updatedAt, messages }) => ({
      id, title, createdAt, updatedAt, messageCount: messages.length,
    }))
    .sort((a, b) => b.updatedAt.localeCompare(a.updatedAt));
}

export async function getConversation(id) {
  return (await load()).find((item) => item.id === id) ?? null;
}

export async function createConversation() {
  const items = await load();
  const now = new Date().toISOString();
  const conversation = {
    id: crypto.randomUUID(),
    title: "新任务",
    createdAt: now,
    updatedAt: now,
    messages: [],
  };
  items.push(conversation);
  await save(items);
  return conversation;
}

export async function addMessage(id, message) {
  const items = await load();
  const conversation = items.find((item) => item.id === id);
  if (!conversation) throw new Error("会话不存在");

  conversation.messages.push({
    id: crypto.randomUUID(),
    createdAt: new Date().toISOString(),
    ...message,
  });
  if (message.role === "user" && conversation.messages.filter((m) => m.role === "user").length === 1) {
    conversation.title = message.content.replace(/\s+/g, " ").slice(0, 28) || "新任务";
  }
  conversation.updatedAt = new Date().toISOString();
  await save(items);
  return conversation;
}

export async function deleteConversation(id) {
  const items = await load();
  const next = items.filter((item) => item.id !== id);
  if (next.length === items.length) return false;
  await save(next);
  return true;
}

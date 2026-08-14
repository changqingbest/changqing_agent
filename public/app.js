const $ = (selector) => document.querySelector(selector);
const state = { conversations: [], activeId: null, busy: false };

const elements = {
  taskList: $("#task-list"),
  stream: $("#message-stream"),
  welcome: $("#welcome"),
  conversation: $("#conversation"),
  form: $("#composer"),
  input: $("#message-input"),
  send: $("#send-button"),
  title: $("#topbar-title"),
  activity: $("#activity"),
  activityText: $("#activity-text"),
  sidebar: $("#sidebar"),
  scrim: $("#sidebar-scrim"),
};

async function request(url, options) {
  const response = await fetch(url, options);
  if (!response.ok) {
    const body = await response.json().catch(() => ({}));
    throw new Error(body.error || `请求失败：${response.status}`);
  }
  return response.json();
}

function escapeHtml(value) {
  return value.replace(/[&<>"']/g, (char) => ({
    "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#039;",
  })[char]);
}

function renderText(value) {
  let safe = escapeHtml(value);
  safe = safe.replace(/```(?:\w+)?\n([\s\S]*?)```/g, "<pre><code>$1</code></pre>");
  safe = safe.replace(/`([^`]+)`/g, "<code>$1</code>");
  return safe.split(/\n{2,}/).map((part) => `<p>${part.replace(/\n/g, "<br>")}</p>`).join("");
}

function relativeTime(iso) {
  const distance = Date.now() - new Date(iso).getTime();
  if (distance < 60_000) return "刚刚";
  if (distance < 3_600_000) return `${Math.floor(distance / 60_000)} 分钟前`;
  if (distance < 86_400_000) return `${Math.floor(distance / 3_600_000)} 小时前`;
  return new Intl.DateTimeFormat("zh-CN", { month: "short", day: "numeric" }).format(new Date(iso));
}

function renderTasks() {
  if (!state.conversations.length) {
    elements.taskList.innerHTML = '<div class="task-empty">这里还没有任务。<br>创建一个，然后开始对话。</div>';
    return;
  }
  elements.taskList.innerHTML = state.conversations.map((item) => `
    <button class="task-item ${item.id === state.activeId ? "active" : ""}" data-id="${item.id}">
      <span class="task-title">${escapeHtml(item.title)}</span>
      <span class="task-meta">${relativeTime(item.updatedAt)} · ${item.messageCount} 条消息</span>
    </button>
  `).join("");
}

function messageTemplate(message) {
  const isUser = message.role === "user";
  return `<article class="message ${isUser ? "user" : "assistant"}">
    <div class="avatar">${isUser ? "YOU" : "CQ"}</div>
    <div class="message-body">
      <div class="message-author">${isUser ? "You" : "Changqing"}</div>
      <div class="message-content">${renderText(message.content)}</div>
    </div>
  </article>`;
}

function renderMessages(conversation) {
  const messages = conversation?.messages || [];
  elements.welcome.hidden = messages.length > 0;
  elements.stream.innerHTML = messages.map(messageTemplate).join("");
  elements.title.textContent = conversation?.title || "新任务";
  requestAnimationFrame(() => { elements.conversation.scrollTop = elements.conversation.scrollHeight; });
}

async function refreshList() {
  state.conversations = await request("/api/conversations");
  renderTasks();
}

async function selectConversation(id) {
  state.activeId = id;
  renderTasks();
  const conversation = await request(`/api/conversations/${id}`);
  renderMessages(conversation);
  closeSidebar();
}

async function createTask() {
  if (state.busy) return;
  const conversation = await request("/api/conversations", { method: "POST" });
  await refreshList();
  await selectConversation(conversation.id);
  elements.input.focus();
}

function setBusy(value, label = "正在思考") {
  state.busy = value;
  elements.input.disabled = value;
  elements.send.disabled = value;
  elements.activity.hidden = !value;
  elements.activityText.textContent = label;
}

async function consumeEvents(response, onEvent) {
  const reader = response.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";
  while (true) {
    const { done, value } = await reader.read();
    if (done) break;
    buffer += decoder.decode(value, { stream: true });
    const blocks = buffer.split("\n\n");
    buffer = blocks.pop();
    for (const block of blocks) {
      const line = block.split("\n").find((item) => item.startsWith("data: "));
      if (line) onEvent(JSON.parse(line.slice(6)));
    }
  }
}

async function sendMessage(text) {
  if (state.busy || !text.trim()) return;
  if (!state.activeId) await createTask();

  const content = text.trim();
  elements.input.value = "";
  resizeInput();
  elements.welcome.hidden = true;
  elements.stream.insertAdjacentHTML("beforeend", messageTemplate({ role: "user", content }));
  elements.conversation.scrollTop = elements.conversation.scrollHeight;
  setBusy(true);

  try {
    const response = await fetch("/api/chat", {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify({ conversationId: state.activeId, message: content }),
    });
    if (!response.ok) throw new Error(`请求失败：${response.status}`);

    await consumeEvents(response, (event) => {
      if (event.type === "status") setBusy(true, event.value === "thinking" ? "正在思考" : "正在处理工具结果");
      if (event.type === "tool_start") setBusy(true, `正在调用 ${event.name}`);
      if (event.type === "answer") elements.stream.insertAdjacentHTML("beforeend", messageTemplate({ role: "assistant", content: event.value }));
      if (event.type === "error") throw new Error(event.value);
    });
    await refreshList();
    const current = state.conversations.find((item) => item.id === state.activeId);
    if (current) elements.title.textContent = current.title;
  } catch (error) {
    elements.stream.insertAdjacentHTML("beforeend", messageTemplate({ role: "assistant", content: `运行失败：${error.message}` }));
  } finally {
    setBusy(false);
    elements.conversation.scrollTop = elements.conversation.scrollHeight;
    elements.input.focus();
  }
}

function resizeInput() {
  elements.input.style.height = "auto";
  elements.input.style.height = `${Math.min(elements.input.scrollHeight, 180)}px`;
}

function openSidebar() { elements.sidebar.classList.add("open"); elements.scrim.classList.add("open"); }
function closeSidebar() { elements.sidebar.classList.remove("open"); elements.scrim.classList.remove("open"); }

elements.taskList.addEventListener("click", (event) => {
  const item = event.target.closest("[data-id]");
  if (item && !state.busy) selectConversation(item.dataset.id);
});
elements.form.addEventListener("submit", (event) => { event.preventDefault(); sendMessage(elements.input.value); });
elements.input.addEventListener("input", resizeInput);
elements.input.addEventListener("keydown", (event) => {
  if (event.key === "Enter" && !event.shiftKey && !event.isComposing) {
    event.preventDefault();
    sendMessage(elements.input.value);
  }
});
$("#new-task").addEventListener("click", createTask);
$("#delete-task").addEventListener("click", async () => {
  if (!state.activeId || state.busy || !confirm("删除当前任务及其全部消息？")) return;
  await request(`/api/conversations/${state.activeId}`, { method: "DELETE" });
  state.activeId = null;
  await refreshList();
  if (state.conversations[0]) await selectConversation(state.conversations[0].id);
  else renderMessages(null);
});
document.querySelectorAll("[data-prompt]").forEach((button) => button.addEventListener("click", () => sendMessage(button.dataset.prompt)));
$("#open-sidebar").addEventListener("click", openSidebar);
$("#close-sidebar").addEventListener("click", closeSidebar);
elements.scrim.addEventListener("click", closeSidebar);
document.addEventListener("keydown", (event) => {
  if ((event.ctrlKey || event.metaKey) && event.key.toLowerCase() === "k") { event.preventDefault(); createTask(); }
});

async function boot() {
  try {
    const [status] = await Promise.all([request("/api/status"), refreshList()]);
    $("#runtime-dot").classList.add("online");
    $("#runtime-label").textContent = status.mode === "demo" ? "演示模式" : "模型已连接";
    $("#model-label").textContent = status.mode === "demo" ? "配置 API Key 以启用模型" : status.model;
    if (state.conversations[0]) await selectConversation(state.conversations[0].id);
    else renderMessages(null);
  } catch (error) {
    $("#runtime-label").textContent = "服务未连接";
    $("#model-label").textContent = error.message;
  }
  elements.input.focus();
}

boot();

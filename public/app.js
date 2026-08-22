const $ = (selector) => document.querySelector(selector);
const state = {
  conversations: [], activeId: null, busy: false,
  promptCatalog: { categories: [], templates: [] }, activeTemplateCategory: "all",
  modelConfig: null, theme: "system",
};

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
  templatePanel: $("#template-panel"),
  templateTrigger: $("#template-trigger"),
  templateSearch: $("#template-search"),
  templateCategories: $("#template-categories"),
  templateList: $("#template-list"),
  modelDialog: $("#model-dialog"),
  modelForm: $("#model-config-form"),
  providerPreset: $("#provider-preset"),
  providerName: $("#provider-name"),
  providerBaseUrl: $("#provider-base-url"),
  providerModel: $("#provider-model"),
  providerApiKey: $("#provider-api-key"),
  modelFormStatus: $("#model-form-status"),
  modelApply: $("#model-apply"),
  nativeSearchEnabled: $("#native-search-enabled"),
  nativeSearchStrategy: $("#native-search-strategy"),
  nativeSearchForced: $("#native-search-forced"),
};

const THEME_STORAGE_KEY = "changqing-theme";
const systemDarkTheme = window.matchMedia("(prefers-color-scheme: dark)");
const providerPresets = {
  qwen: {
    provider_name: "Qwen / DashScope",
    base_url: "https://dashscope.aliyuncs.com/compatible-mode/v1",
    model: "qwen-plus",
    enable_search: true,
    search_strategy: "turbo",
    forced_search: false,
  },
  openai: {
    provider_name: "OpenAI Compatible",
    base_url: "https://api.openai.com/v1",
    model: "gpt-4.1-mini",
    enable_search: false,
    search_strategy: "turbo",
    forced_search: false,
  },
};

// 背景只做轻微指针视差，真正的极光漂移动画由 CSS 完成。
// requestAnimationFrame 把高频 pointermove 合并为每帧一次，避免影响聊天滚动。
const ambientStage = $(".ambient-stage");
const reduceMotion = window.matchMedia("(prefers-reduced-motion: reduce)");
let ambientFrame = 0;
window.addEventListener("pointermove", (event) => {
  if (reduceMotion.matches || !ambientStage) return;
  const x = ((event.clientX / window.innerWidth) - 0.5) * 18;
  const y = ((event.clientY / window.innerHeight) - 0.5) * 14;
  cancelAnimationFrame(ambientFrame);
  ambientFrame = requestAnimationFrame(() => {
    ambientStage.style.setProperty("--ambient-x", `${x}px`);
    ambientStage.style.setProperty("--ambient-y", `${y}px`);
  });
}, { passive: true });

function readSavedTheme() {
  try {
    const saved = localStorage.getItem(THEME_STORAGE_KEY);
    return ["system", "light", "dark"].includes(saved) ? saved : "system";
  } catch (_error) {
    return "system";
  }
}

function applyTheme(theme, persist = true) {
  state.theme = ["system", "light", "dark"].includes(theme) ? theme : "system";
  if (state.theme === "system") delete document.documentElement.dataset.theme;
  else document.documentElement.dataset.theme = state.theme;
  if (persist) {
    try { localStorage.setItem(THEME_STORAGE_KEY, state.theme); } catch (_error) {}
  }
  document.querySelectorAll("[data-theme-value]").forEach((button) => {
    const active = button.dataset.themeValue === state.theme;
    button.classList.toggle("active", active);
    button.setAttribute("aria-pressed", String(active));
  });
  const systemLabel = systemDarkTheme.matches ? "暗色" : "浅色";
  const systemButton = $("[data-theme-value='system']");
  if (systemButton) systemButton.title = `跟随系统（当前${systemLabel}）`;
}

function inferProviderPreset(config) {
  try {
    const endpoint = new URL(config.base_url);
    if (endpoint.hostname.endsWith("aliyuncs.com") && endpoint.pathname.includes("/compatible-mode/v1")) return "qwen";
  } catch (_error) {}
  if (config.base_url.includes("api.openai.com")) return "openai";
  return "custom";
}

function syncNativeSearchControls() {
  const enabled = elements.nativeSearchEnabled.checked;
  elements.nativeSearchStrategy.disabled = !enabled;
  elements.nativeSearchForced.disabled = !enabled;
  $("#native-search-config").classList.toggle("disabled", !enabled);
}

function renderModelConfig(config) {
  state.modelConfig = config;
  $("#current-model-name").textContent = `${config.provider_name} / ${config.model}`;
  const searchLabel = config.enable_search
    ? `原生搜索 ${config.search_strategy.toUpperCase()}${config.forced_search ? " / 强制" : ""}`
    : "原生搜索关闭";
  $("#current-model-endpoint").textContent = `${config.base_url} · ${config.api_key_configured ? "KEY 已配置" : "未配置 KEY"} · ${searchLabel}`;
  elements.providerPreset.value = inferProviderPreset(config);
  elements.providerName.value = config.provider_name;
  elements.providerBaseUrl.value = config.base_url;
  elements.providerModel.value = config.model;
  elements.nativeSearchEnabled.checked = Boolean(config.enable_search);
  elements.nativeSearchStrategy.value = config.search_strategy || "turbo";
  elements.nativeSearchForced.checked = Boolean(config.forced_search);
  syncNativeSearchControls();
  elements.providerApiKey.value = "";
  elements.providerApiKey.placeholder = config.api_key_configured ? "留空保留当前密钥" : "输入新的 API Key";
}

function updateRuntimeLabels(config) {
  $("#runtime-dot").classList.add("online");
  $("#runtime-label").textContent = config.api_key_configured ? config.provider_name : "演示模式";
  $("#model-label").textContent = config.api_key_configured ? config.model : "配置 API Key 以启用模型";
}

function openModelDialog() {
  if (state.modelConfig) renderModelConfig(state.modelConfig);
  elements.modelFormStatus.textContent = "";
  elements.modelFormStatus.className = "model-form-status field-wide";
  elements.providerApiKey.type = "password";
  $("#toggle-api-key").textContent = "显示";
  elements.modelDialog.showModal();
}

function closeModelDialog() {
  elements.providerApiKey.value = "";
  elements.modelDialog.close();
}

function applyProviderPreset() {
  const preset = providerPresets[elements.providerPreset.value];
  if (!preset) return;
  elements.providerName.value = preset.provider_name;
  elements.providerBaseUrl.value = preset.base_url;
  elements.providerModel.value = preset.model;
  elements.nativeSearchEnabled.checked = preset.enable_search;
  elements.nativeSearchStrategy.value = preset.search_strategy;
  elements.nativeSearchForced.checked = preset.forced_search;
  syncNativeSearchControls();
}

async function saveModelConfig(event) {
  event.preventDefault();
  elements.modelApply.disabled = true;
  elements.modelFormStatus.textContent = "正在切换运行时模型…";
  elements.modelFormStatus.className = "model-form-status field-wide";
  try {
    const payload = {
      provider_name: elements.providerName.value.trim(),
      base_url: elements.providerBaseUrl.value.trim(),
      model: elements.providerModel.value.trim(),
      enable_search: elements.nativeSearchEnabled.checked,
      search_strategy: elements.nativeSearchStrategy.value,
      forced_search: elements.nativeSearchForced.checked,
    };
    const apiKey = elements.providerApiKey.value.trim();
    const normalizedNewUrl = payload.base_url.replace(/\/$/, "").replace(/\/chat\/completions$/, "");
    const normalizedCurrentUrl = state.modelConfig?.base_url.replace(/\/$/, "") || "";
    if (!apiKey && normalizedNewUrl !== normalizedCurrentUrl) {
      throw new Error("切换 API 地址时，请输入该服务对应的 API Key。");
    }
    if (apiKey) payload.api_key = apiKey;
    const config = await request("/api/model-config", {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify(payload),
    });
    renderModelConfig(config);
    updateRuntimeLabels(config);
    elements.modelFormStatus.textContent = `已切换到 ${config.provider_name} / ${config.model}，下一轮对话生效。`;
    elements.modelFormStatus.className = "model-form-status field-wide success";
    elements.providerApiKey.value = "";
  } catch (error) {
    elements.modelFormStatus.textContent = `切换失败：${error.message}`;
    elements.modelFormStatus.className = "model-form-status field-wide error";
  } finally {
    elements.modelApply.disabled = false;
  }
}

async function request(url, options) {
  const response = await fetch(url, options);
  if (!response.ok) {
    const body = await response.json().catch(() => ({}));
    throw new Error(body.detail || body.error || `请求失败：${response.status}`);
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

function reactTraceTemplate(traceId) {
  return `<section class="react-trace" id="${traceId}" aria-label="ReAct 执行轨迹" hidden>
    <div class="react-trace-head"><span>REACT LOOP</span><strong>执行轨迹</strong></div>
    <div class="react-trace-body"></div>
  </section>`;
}

function streamingAssistantTemplate(responseId, traceId) {
  return `<article class="message assistant response-pending" id="${responseId}">
    <div class="avatar">CQ</div>
    <div class="message-body">
      <div class="message-heading">
        <div class="message-author">Changqing</div>
        <button class="react-toggle" type="button" aria-expanded="false" aria-controls="${traceId}">
          <span>过程记录</span><b class="react-count">0</b><i aria-hidden="true">⌄</i>
        </button>
      </div>
      <div class="message-content answer-content" aria-live="polite">
        <p class="answer-placeholder">模型正在组织回答…</p>
      </div>
      ${reactTraceTemplate(traceId)}
    </div>
  </article>`;
}

function setAssistantAnswer(responseId, value, isError = false) {
  const response = document.getElementById(responseId);
  if (!response) return;
  response.classList.remove("response-pending");
  response.classList.toggle("response-error", isError);
  response.querySelector(".answer-content").innerHTML = renderText(value);
}

function appendReactEvent(traceId, event) {
  const body = document.querySelector(`#${traceId} .react-trace-body`);
  if (!body) return;
  const toggle = document.querySelector(`[aria-controls="${traceId}"]`);
  const currentCount = Number(toggle?.dataset.count || 0) + 1;
  if (toggle) {
    toggle.dataset.count = String(currentCount);
    toggle.querySelector(".react-count").textContent = String(currentCount);
  }
  if (event.type === "step") {
    body.insertAdjacentHTML("beforeend", `<div class="react-step">第 ${Number(event.value)} 步</div>`);
    return;
  }
  const labels = {
    interpreter: ["◈", "解释器"], thought: ["🧠", "思考"], action: ["🎬", "行动"], observation: ["👀", "观察"],
  };
  if (!labels[event.type]) return;
  const [icon, label] = labels[event.type];
  let value = event.value || "";
  if (event.type === "interpreter") value = `${event.name} · ${event.description}`;
  if (event.type === "action") value = event.name === "Finish" ? "Finish" : `${event.name}[${event.input || ""}]`;
  body.insertAdjacentHTML("beforeend", `<div class="react-row ${event.type}">
    <span class="react-icon" aria-hidden="true">${icon}</span>
    <div><strong>${label}</strong><div>${renderText(String(value))}</div></div>
  </div>`);
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
  const responseToken = `${Date.now()}-${Math.random().toString(16).slice(2)}`;
  const responseId = `assistant-response-${responseToken}`;
  const traceId = `react-trace-${responseToken}`;
  elements.stream.insertAdjacentHTML("beforeend", streamingAssistantTemplate(responseId, traceId));
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
      if (event.type === "status") setBusy(true, event.value === "thinking" ? "正在思考" : "正在处理观察结果");
      if (event.type === "tool_start") setBusy(true, `正在调用 ${event.name}`);
      if (["interpreter", "step", "thought", "action", "observation"].includes(event.type)) appendReactEvent(traceId, event);
      if (event.type === "answer") setAssistantAnswer(responseId, event.value);
      if (event.type === "error") throw new Error(event.value);
      elements.conversation.scrollTop = elements.conversation.scrollHeight;
    });
    await refreshList();
    const current = state.conversations.find((item) => item.id === state.activeId);
    if (current) elements.title.textContent = current.title;
  } catch (error) {
    setAssistantAnswer(responseId, `运行失败：${error.message}`, true);
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

function renderTemplateCategories() {
  const categories = [{ id: "all", name: "全部" }, ...state.promptCatalog.categories];
  elements.templateCategories.innerHTML = categories.map((category) => `
    <button type="button" role="tab" data-template-category="${escapeHtml(category.id)}"
      aria-selected="${category.id === state.activeTemplateCategory}"
      class="${category.id === state.activeTemplateCategory ? "active" : ""}">
      ${escapeHtml(category.name)}
    </button>
  `).join("");
}

function renderPromptTemplates() {
  const query = elements.templateSearch.value.trim().toLocaleLowerCase("zh-CN");
  const visible = state.promptCatalog.templates.filter((template) => {
    const inCategory = state.activeTemplateCategory === "all" || template.category === state.activeTemplateCategory;
    const searchable = `${template.title} ${template.description} ${template.prompt}`.toLocaleLowerCase("zh-CN");
    return inCategory && (!query || searchable.includes(query));
  });
  elements.templateList.innerHTML = visible.length ? visible.map((template) => `
    <button type="button" class="template-card" data-template-id="${escapeHtml(template.id)}">
      <strong>${escapeHtml(template.title)}</strong>
      <span>${escapeHtml(template.description)}</span>
    </button>
  `).join("") : '<div class="template-empty">没有匹配的模板</div>';
}

function openTemplatePanel() {
  if (state.busy) return;
  elements.templatePanel.hidden = false;
  elements.templateTrigger.setAttribute("aria-expanded", "true");
  elements.templateSearch.focus();
}

function closeTemplatePanel() {
  elements.templatePanel.hidden = true;
  elements.templateTrigger.setAttribute("aria-expanded", "false");
}

function applyPromptTemplate(templateId) {
  const template = state.promptCatalog.templates.find((item) => item.id === templateId);
  if (!template) return;
  elements.input.value = template.prompt;
  resizeInput();
  closeTemplatePanel();
  elements.input.focus();
  elements.input.setSelectionRange(elements.input.value.length, elements.input.value.length);
}

function openSidebar() { elements.sidebar.classList.add("open"); elements.scrim.classList.add("open"); }
function closeSidebar() { elements.sidebar.classList.remove("open"); elements.scrim.classList.remove("open"); }

elements.taskList.addEventListener("click", (event) => {
  const item = event.target.closest("[data-id]");
  if (item && !state.busy) selectConversation(item.dataset.id);
});
elements.form.addEventListener("submit", (event) => { event.preventDefault(); sendMessage(elements.input.value); });
elements.stream.addEventListener("click", (event) => {
  const toggle = event.target.closest(".react-toggle");
  if (!toggle) return;
  const trace = document.getElementById(toggle.getAttribute("aria-controls"));
  if (!trace) return;
  const willExpand = toggle.getAttribute("aria-expanded") !== "true";
  toggle.setAttribute("aria-expanded", String(willExpand));
  trace.hidden = !willExpand;
  if (willExpand) requestAnimationFrame(() => trace.scrollIntoView({ block: "nearest", behavior: "smooth" }));
});
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
elements.templateTrigger.addEventListener("click", () => {
  if (elements.templatePanel.hidden) openTemplatePanel();
  else closeTemplatePanel();
});
$("#template-close").addEventListener("click", closeTemplatePanel);
elements.templateSearch.addEventListener("input", renderPromptTemplates);
elements.templateCategories.addEventListener("click", (event) => {
  const button = event.target.closest("[data-template-category]");
  if (!button) return;
  state.activeTemplateCategory = button.dataset.templateCategory;
  renderTemplateCategories();
  renderPromptTemplates();
});
elements.templateList.addEventListener("click", (event) => {
  const card = event.target.closest("[data-template-id]");
  if (card) applyPromptTemplate(card.dataset.templateId);
});
$("#open-sidebar").addEventListener("click", openSidebar);
$("#close-sidebar").addEventListener("click", closeSidebar);
elements.scrim.addEventListener("click", closeSidebar);
document.querySelectorAll("[data-theme-value]").forEach((button) => {
  button.addEventListener("click", () => applyTheme(button.dataset.themeValue));
});
systemDarkTheme.addEventListener("change", () => {
  if (state.theme === "system") applyTheme("system", false);
});
$("#model-settings").addEventListener("click", openModelDialog);
$("#model-dialog-close").addEventListener("click", closeModelDialog);
$("#model-cancel").addEventListener("click", closeModelDialog);
elements.providerPreset.addEventListener("change", applyProviderPreset);
elements.nativeSearchEnabled.addEventListener("change", syncNativeSearchControls);
elements.modelForm.addEventListener("submit", saveModelConfig);
$("#toggle-api-key").addEventListener("click", () => {
  const showing = elements.providerApiKey.type === "text";
  elements.providerApiKey.type = showing ? "password" : "text";
  $("#toggle-api-key").textContent = showing ? "显示" : "隐藏";
  elements.providerApiKey.focus();
});
elements.modelDialog.addEventListener("click", (event) => {
  if (event.target === elements.modelDialog) closeModelDialog();
});
document.addEventListener("keydown", (event) => {
  if ((event.ctrlKey || event.metaKey) && event.key.toLowerCase() === "k") { event.preventDefault(); createTask(); }
  if (event.key === "Escape" && !elements.templatePanel.hidden) closeTemplatePanel();
});

async function boot() {
  applyTheme(readSavedTheme(), false);
  try {
    const [status, promptCatalog, modelConfig] = await Promise.all([
      request("/api/status"), request("/api/prompt-templates"), request("/api/model-config"), refreshList(),
    ]);
    state.promptCatalog = promptCatalog;
    renderTemplateCategories();
    renderPromptTemplates();
    renderModelConfig(modelConfig);
    updateRuntimeLabels(modelConfig);
    if (state.conversations[0]) await selectConversation(state.conversations[0].id);
    else renderMessages(null);
  } catch (error) {
    $("#runtime-label").textContent = "服务未连接";
    $("#model-label").textContent = error.message;
  }
  elements.input.focus();
}

boot();

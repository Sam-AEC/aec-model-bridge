const views = {
  chat: { title: "Chat", subtitle: "AEC Model Bridge" },
  plans: { title: "Pending Actions", subtitle: "Approval queue" },
  findings: { title: "Findings", subtitle: "Model health" },
  reports: { title: "Reports", subtitle: "Exports" },
  log: { title: "Run Log", subtitle: "Recent activity" },
  settings: { title: "Settings", subtitle: "Local bridge" }
};

// plans/findings/reports start empty and are populated only from real
// host.dispatchToHub responses (see the "message" listener below) - there is
// no fixture/demo data. Use the matching ribbon/panel action (Run Health
// Check, Review Pending Actions, Export Report) to populate each list.
const state = {
  host: null,
  snapshot: null,
  llm: null,
  plans: [],
  findings: [],
  reports: [],
  log: [
    { at: "09:00", title: "Panel loaded", detail: "Waiting for host status." }
  ]
};

const hostStatus = document.getElementById("host-status");
const systemAlerts = document.getElementById("system-alerts");
const title = document.getElementById("view-title");
const subtitle = document.getElementById("view-subtitle");
const chatFeed = document.getElementById("chat-feed");
const chatForm = document.getElementById("chat-form");
const chatInput = document.getElementById("chat-input");
const chatProvider = document.getElementById("chat-provider");
const chatReset = document.getElementById("chat-reset");
const planList = document.getElementById("plan-list");
const findingList = document.getElementById("finding-list");
const reportList = document.getElementById("report-list");
const runLog = document.getElementById("run-log");
const severityFilter = document.getElementById("severity-filter");
const settingsForm = document.getElementById("settings-form");
const hubUrl = document.getElementById("hub-url");

function postToHost(type, payload = {}) {
  if (window.chrome && window.chrome.webview) {
    window.chrome.webview.postMessage(JSON.stringify({ type, ...payload }));
  }
}

function escapeHtml(value) {
  return String(value).replace(/[&<>"']/g, (char) => ({
    "&": "&amp;",
    "<": "&lt;",
    ">": "&gt;",
    "\"": "&quot;",
    "'": "&#39;"
  })[char]);
}

function addLog(titleText, detail) {
  state.log.unshift({
    at: new Date().toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" }),
    title: titleText,
    detail
  });
  renderLog();
}

function hasActiveDocument() {
  const documentName = state.host?.activeDocument;
  return !!documentName && documentName !== "none";
}

function isHubOnline() {
  return !!state.host?.serverRunning;
}

function snapshotIsStale() {
  return state.host?.snapshotStale || state.host?.snapshotState === "stale" || state.snapshot?.stale === true;
}

function llmIsOffline() {
  return state.host?.llmOnline === false || state.host?.llmState === "offline" || state.llm?.online === false;
}

function modelActionsBlocked() {
  return !isHubOnline() || !hasActiveDocument();
}

function setView(viewName) {
  document.querySelectorAll(".nav").forEach((button) => {
    button.classList.toggle("is-active", button.dataset.view === viewName);
  });
  document.querySelectorAll(".view").forEach((view) => {
    view.classList.toggle("is-active", view.id === `view-${viewName}`);
  });
  title.textContent = views[viewName].title;
  subtitle.textContent = views[viewName].subtitle;
}

function renderHostStatus() {
  const online = state.host?.serverRunning;
  hostStatus.classList.toggle("is-online", !!online);
  hostStatus.classList.toggle("is-offline", !!state.host && !online);
  hostStatus.lastElementChild.textContent = online
    ? `Revit ${state.host.revitVersion || ""} :${state.host.port || ""}`
    : state.host ? "Hub down" : "Host pending";
}

function renderAlerts() {
  const alerts = [];
  if (!state.host) {
    alerts.push(["warning", "Waiting for host", "The panel has not received Revit status yet."]);
  } else {
    if (!isHubOnline()) {
      alerts.push(["error", "Hub down", "Start the bridge server from the Connection panel."]);
    }
    if (!hasActiveDocument()) {
      alerts.push(["warning", "No document open", "Open a Revit model to enable model tools."]);
    }
    if (snapshotIsStale()) {
      const dirtyCount = state.host?.dirtyElementCount || state.snapshot?.dirtyElementCount;
      const detail = dirtyCount
        ? `${dirtyCount} changed elements since the last clean snapshot.`
        : "Retake the model snapshot before running checks or exports.";
      alerts.push(["warning", "Snapshot stale", detail]);
    }
    if (llmIsOffline()) {
      alerts.push(["warning", "LLM offline", "Chat and natural-language tools are unavailable."]);
    }
  }

  systemAlerts.hidden = alerts.length === 0;
  systemAlerts.innerHTML = alerts.map(([level, heading, detail]) => `
    <div class="alert ${escapeHtml(level)}">
      <span class="alert-marker" aria-hidden="true"></span>
      <div>
        <strong>${escapeHtml(heading)}</strong>
        <p>${escapeHtml(detail)}</p>
      </div>
    </div>`).join("");
}

function updateToolAvailability() {
  const blocked = modelActionsBlocked();
  const chatBlocked = blocked || llmIsOffline();
  document.querySelectorAll("[data-action], [data-plan], [data-report]").forEach((control) => {
    control.disabled = blocked;
  });
  chatInput.disabled = chatBlocked;
  chatForm.querySelector("button").disabled = chatBlocked;
}

function renderSystemState() {
  renderHostStatus();
  renderAlerts();
  updateToolAvailability();
}

function renderChat() {
  chatFeed.innerHTML = "";
  [
    { role: "assistant", text: "Ready for the active model." },
    { role: "assistant", text: "Pending plans and findings will appear in their tabs." }
  ].forEach((message) => appendMessage(message.role, message.text));
}

function appendMessage(role, text) {
  const item = document.createElement("article");
  item.className = `message ${role === "user" ? "user" : "assistant"}`;
  item.innerHTML = `<div class="meta">${role === "user" ? "You" : "AMB"}</div><div>${escapeHtml(text)}</div>`;
  chatFeed.appendChild(item);
  chatFeed.scrollTop = chatFeed.scrollHeight;
  return item;
}

let pendingChatMessage = null;

function resolvePendingChatMessage(text, isError) {
  if (!pendingChatMessage) {
    appendMessage("assistant", text);
    return;
  }
  pendingChatMessage.classList.remove("pending");
  pendingChatMessage.classList.toggle("error", !!isError);
  pendingChatMessage.querySelector("div:last-child").textContent = text;
  pendingChatMessage = null;
  chatFeed.scrollTop = chatFeed.scrollHeight;
}

function renderPlans() {
  planList.innerHTML = "";
  if (state.plans.length === 0) {
    renderEmpty(planList, "No pending actions", "Approved or rejected ActionPlans will clear from this queue.");
    return;
  }

  state.plans.forEach((plan) => {
    const item = document.createElement("article");
    item.className = "item";
    item.innerHTML = `
      <div class="item-head">
        <h2>${escapeHtml(plan.title)}</h2>
        <span class="badge pending">${escapeHtml(plan.status)}</span>
      </div>
      <p>${escapeHtml(plan.detail)}</p>
      <div class="item-actions">
        <button type="button" data-plan="${escapeHtml(plan.id)}" data-decision="approve">Approve</button>
        <button type="button" data-plan="${escapeHtml(plan.id)}" data-decision="reject">Reject</button>
      </div>`;
    planList.appendChild(item);
  });
}

function renderFindings() {
  findingList.innerHTML = "";
  const severity = severityFilter.value;
  const findings = state.findings.filter((finding) => severity === "all" || finding.severity === severity);
  if (findings.length === 0) {
    renderEmpty(findingList, "No findings", "Run a health check or change the severity filter.");
    return;
  }

  findings.forEach((finding) => {
    const item = document.createElement("article");
    item.className = "item";
    item.innerHTML = `
      <div class="item-head">
        <h2>${escapeHtml(finding.title)}</h2>
        <span class="badge ${escapeHtml(finding.severity)}">${escapeHtml(finding.severity)}</span>
      </div>
      <p>${escapeHtml(finding.detail)}</p>`;
    findingList.appendChild(item);
  });
}

function renderReports() {
  reportList.innerHTML = "";
  if (state.reports.length === 0) {
    renderEmpty(reportList, "No reports", "Run a health check or refresh report exports.");
    return;
  }

  state.reports.forEach((report) => {
    const item = document.createElement("article");
    item.className = "item";
    item.innerHTML = `
      <div class="item-head">
        <h2>${escapeHtml(report.title)}</h2>
        <span class="badge info">report</span>
      </div>
      <p>${escapeHtml(report.detail)}</p>
      <div class="item-actions">
        <button type="button" data-report="${escapeHtml(report.id)}">Open</button>
      </div>`;
    reportList.appendChild(item);
  });
}

function renderLog() {
  runLog.innerHTML = "";
  if (state.log.length === 0) {
    renderEmpty(runLog, "No run log entries", "Panel and host events will appear here.");
    return;
  }

  state.log.forEach((event) => {
    const item = document.createElement("article");
    item.className = "event";
    item.innerHTML = `<div class="meta">${escapeHtml(event.at)}</div><strong>${escapeHtml(event.title)}</strong><p>${escapeHtml(event.detail)}</p>`;
    runLog.appendChild(item);
  });
}

function renderEmpty(container, heading, detail) {
  const item = document.createElement("article");
  item.className = "empty";
  item.innerHTML = `<strong>${escapeHtml(heading)}</strong><p>${escapeHtml(detail)}</p>`;
  container.appendChild(item);
}

document.querySelectorAll(".nav").forEach((button) => {
  button.addEventListener("click", () => setView(button.dataset.view));
});

document.body.addEventListener("click", (event) => {
  const target = event.target;
  if (!(target instanceof HTMLElement)) {
    return;
  }

  const action = target.dataset.action;
  if (action === "refresh-plans") {
    postToHost("plans.refresh");
    addLog("Plans refreshed", "Requested pending plans from the host.");
  }
  if (action === "approve-selected") {
    postToHost("plans.approveSelected");
    addLog("Approval requested", "Selected pending actions sent to the host.");
  }
  if (action === "run-health") {
    postToHost("qaqc.runHealthCheck");
    addLog("Health check requested", "QA/QC run sent to the host.");
  }
  if (action === "export-excel") {
    postToHost("reports.exportExcel");
    addLog("Report export requested", "Excel export sent to the host.");
  }
  if (action === "refresh-reports") {
    postToHost("reports.refresh");
    addLog("Reports refreshed", "Requested available reports from the host.");
  }

  const planId = target.dataset.plan;
  if (planId) {
    const decision = target.dataset.decision;
    postToHost(`plan.${decision}`, { planId });
    addLog(`Plan ${decision}`, planId);
  }

  const reportId = target.dataset.report;
  if (reportId) {
    postToHost("reports.open", { reportId });
    addLog("Report opened", reportId);
  }
});

chatForm.addEventListener("submit", (event) => {
  event.preventDefault();
  const text = chatInput.value.trim();
  if (!text) {
    return;
  }
  appendMessage("user", text);
  chatInput.value = "";
  postToHost("chat.message", { message: text, provider: chatProvider.value });
  pendingChatMessage = appendMessage("assistant", "Thinking…");
  pendingChatMessage.classList.add("pending");
  addLog("Chat message sent", `[${chatProvider.value}] ${text}`);
});

chatReset.addEventListener("click", () => {
  postToHost("chat.reset");
  pendingChatMessage = null;
  renderChat();
  addLog("Chat reset", "Started a new conversation.");
});

severityFilter.addEventListener("change", renderFindings);

settingsForm.addEventListener("submit", (event) => {
  event.preventDefault();
  postToHost("settings.save", {
    hubUrl: hubUrl.value,
    approvalMode: document.getElementById("approval-mode").value
  });
  addLog("Settings saved", hubUrl.value);
});

// Maps for the raw hub tool results the host forwards after a real MCP tool
// call (see packages/revit-bridge-addin/src/UI/BridgePanel.xaml.cs's
// DispatchToHubAsync) into the shapes the render* functions above expect.
function mapFindings(hubResult) {
  const findings = (hubResult && hubResult.findings) || [];
  return findings.map((finding, index) => ({
    id: finding.element_uid ? `${finding.rule_id}:${finding.element_uid}` : `${finding.rule_id}:${index}`,
    severity: finding.severity || "info",
    title: String(finding.rule_id || "finding").replace(/_/g, " ").replace(/\b\w/g, (c) => c.toUpperCase()),
    detail: finding.message || ""
  }));
}

function mapPlans(hubResult) {
  const plans = (hubResult && hubResult.plans) || [];
  return plans.map((plan) => {
    const actions = plan.actions || [];
    return {
      id: plan.plan_id,
      status: plan.state,
      title: actions.length === 1 ? actions[0].tool : `${actions.length} action(s)`,
      detail: actions.map((action) => action.tool).join(", ") || "No actions"
    };
  });
}

function mapReport(hubResult) {
  const fileName = String(hubResult.output_file || "").split(/[\\/]/).pop();
  return {
    id: hubResult.output_file || `report-${Date.now()}`,
    title: fileName || "Report",
    detail: `${hubResult.element_count ?? "?"} elements, ${hubResult.type_count ?? "?"} types exported to ${hubResult.output_file || "workspace"}`
  };
}

if (window.chrome && window.chrome.webview) {
  window.chrome.webview.addEventListener("message", (event) => {
    if (event.data?.type === "host.status") {
      state.host = event.data;
      renderSystemState();
      addLog("Host status updated", state.host.activeDocument || "No active document");
    }
    if (event.data?.type === "snapshot.status") {
      state.snapshot = event.data;
      renderSystemState();
    }
    if (event.data?.type === "llm.status") {
      state.llm = event.data;
      renderSystemState();
    }
    if (event.data?.type === "findings.updated") {
      state.findings = mapFindings(event.data.result);
      renderFindings();
      addLog("Health check complete", `${state.findings.length} finding(s)`);
    }
    if (event.data?.type === "plans.updated") {
      state.plans = mapPlans(event.data.result);
      renderPlans();
      addLog("Plans updated", `${state.plans.length} pending`);
    }
    if (event.data?.type === "reports.updated") {
      const report = mapReport(event.data.result);
      state.reports = [report, ...state.reports];
      renderReports();
      addLog("Report exported", report.title);
    }
    if (event.data?.type === "tool.error") {
      addLog(`Error: ${event.data.action || "tool"}`, event.data.message || "Unknown error");
    }
    if (event.data?.type === "chat.response") {
      resolvePendingChatMessage(event.data.message || "(empty response)", false);
      addLog("Chat response received", "");
    }
    if (event.data?.type === "chat.error") {
      resolvePendingChatMessage(`Error: ${event.data.message || "Unknown error"}`, true);
      addLog("Chat error", event.data.message || "Unknown error");
    }
    if (event.data?.type === "panel.view" && views[event.data.view]) {
      setView(event.data.view);
      if (event.data.action) {
        if (modelActionsBlocked()) {
          addLog("Ribbon command blocked", event.data.action);
        } else {
          postToHost(event.data.action);
          addLog("Ribbon command", event.data.action);
        }
      }
    }
  });
}

renderChat();
renderPlans();
renderFindings();
renderReports();
renderLog();
renderSystemState();
postToHost("panel.loaded");

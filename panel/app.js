const views = {
  chat: { title: "Chat", subtitle: "AEC Model Bridge" },
  plans: { title: "Pending Actions", subtitle: "Approval queue" },
  findings: { title: "Findings", subtitle: "Model health" },
  reports: { title: "Reports", subtitle: "Exports" },
  log: { title: "Run Log", subtitle: "Recent activity" },
  settings: { title: "Settings", subtitle: "Local bridge" }
};

const state = {
  host: null,
  snapshot: null,
  llm: null,
  plans: [
    {
      id: "plan_demo_01",
      title: "Set FireRating on 12 doors",
      status: "pending",
      detail: "Parameter Manager will write FireRating = 60 to matching door instances."
    },
    {
      id: "plan_demo_02",
      title: "Rename duplicate sheet numbers",
      status: "pending",
      detail: "QA/QC checker found duplicate sheet numbers in the active document."
    }
  ],
  findings: [
    { id: "f-001", severity: "error", title: "Doors missing FireRating", detail: "12 door instances have an empty FireRating value." },
    { id: "f-002", severity: "warning", title: "Views not on sheets", detail: "8 views are not placed on sheets." },
    { id: "f-003", severity: "info", title: "Unplaced rooms", detail: "3 rooms are unplaced in the active model." }
  ],
  reports: [
    { id: "r-001", title: "Model health workbook", detail: "Excel export with elements, types, and QA/QC issues." },
    { id: "r-002", title: "SQLite model summary", detail: "Local database export for downstream reporting." }
  ],
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
  postToHost("chat.message", { text });
  appendMessage("assistant", "Request sent to the host.");
  addLog("Chat message sent", text);
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

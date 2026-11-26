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
  providers: null,
  plans: [],
  // Plan ids ticked in the Plans view for "Approve Selected".
  selectedPlanIds: new Set(),
  // "<plan id>:<plan hash>" of plans whose review the person opened; Approve needs it for hash_version 2.
  openedReviews: new Set(),
  plansOmitted: 0,
  allPlans: [],
  showOtherPlans: false,
  otherHidden: 0,
  // "<plan id>:<plan hash>" of unbound plans the person ticked the explicit confirm for.
  confirmedUnbound: new Set(),
  // Plan ids whose "Show details" the person toggled. Dev mode opens details by default.
  detailsToggled: new Set(),
  expiredHidden: 0,
  showExpired: false,
  findings: [],
  reports: [],
  diagnostics: null,
  log: [
    { at: "09:00", title: "Panel loaded", detail: "Waiting for host status." }
  ]
};

const hostStatus = document.getElementById("host-status");
const systemAlerts = document.getElementById("system-alerts");
const title = document.getElementById("view-title");
const subtitle = document.getElementById("view-subtitle");
const viewIcon = document.getElementById("view-icon");
const chatRoot = document.getElementById("chat-root");
const modeChip = document.getElementById("mode-chip");
const planList = document.getElementById("plan-list");
const findingList = document.getElementById("finding-list");
const reportList = document.getElementById("report-list");
const runLog = document.getElementById("run-log");
const severityFilter = document.getElementById("severity-filter");
const settingsForm = document.getElementById("settings-form");
const approvalModeSelect = document.getElementById("approval-mode");
const autoMinutesLabel = document.getElementById("auto-minutes-label");
const autoMinutesSelect = document.getElementById("auto-minutes");
const autoOffButton = document.getElementById("auto-off");
const setupCard = document.getElementById("setup-check");
const setupStatus = document.getElementById("setup-status");
const setupLabel = document.getElementById("setup-label");
const setupBody = document.getElementById("setup-body");
const setupList = document.getElementById("setup-list");
const setupToggle = document.getElementById("setup-toggle");
const setupRefresh = document.getElementById("setup-refresh");
const setupSummary = document.getElementById("setup-summary");
const plansBadge = document.getElementById("plans-badge");
const modeCardsEl = document.getElementById("mode-cards");
const modeConfirm = document.getElementById("mode-confirm");
const modeConfirmText = document.getElementById("mode-confirm-text");
const modeConfirmOk = document.getElementById("mode-confirm-ok");
const modeConfirmCancel = document.getElementById("mode-confirm-cancel");
const devBar = document.getElementById("dev-bar");
const devBarText = document.getElementById("dev-bar-text");

function postToHost(type, payload = {}) {
  if (window.chrome && window.chrome.webview) {
    window.chrome.webview.postMessage(JSON.stringify({ type, ...payload }));
  }
}

// ---- Chat (panel/chat.js). Non-streaming: the host sends one whole chat.response. ----
// The chat renders model text with textContent / createElement only (never innerHTML).
let chat = null;
let chatProvider = null;
if (window.AMBChat) {
  chat = window.AMBChat.mount(chatRoot, {
    postToHost: (type, payload) => {
      postToHost(type, payload);
      if (type === "chat.message") {
        addLog("Chat message sent", `[${payload.provider}] ${payload.message}`);
      } else if (type === "chat.reset") {
        addLog("Chat reset", "Started a new conversation.");
      }
    },
    onReview: reviewPlan
  });
  chatProvider = document.getElementById("chat-provider");
} else {
  chatRoot.textContent = "Chat could not load: the panel's chat scripts are missing. Reinstall the add-in.";
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

let currentView = "chat";

function setView(viewName) {
  currentView = viewName;
  document.querySelectorAll(".nav").forEach((button) => {
    const active = button.dataset.view === viewName;
    button.classList.toggle("is-active", active);
    if (active) {
      button.setAttribute("aria-current", "page");
    } else {
      button.removeAttribute("aria-current");
    }
  });
  document.querySelectorAll(".view").forEach((view) => {
    view.classList.toggle("is-active", view.id === `view-${viewName}`);
  });
  title.textContent = views[viewName].title;
  subtitle.textContent = views[viewName].subtitle;
  viewIcon.setAttribute("href", `#nav-${viewName}`);
}

function renderHostStatus() {
  const online = state.host?.serverRunning;
  hostStatus.classList.toggle("is-online", !!online);
  hostStatus.classList.toggle("is-offline", !!state.host && !online);
  hostStatus.lastElementChild.textContent = online
    ? `Revit ${state.host.revitVersion || ""} :${state.host.port || ""}${hasActiveDocument() ? ` / ${visibleText(state.host.activeDocument)}` : ""}`
    : state.host ? "Hub down" : "Host pending";
}

// ---- Setup check (GET /diagnostics, forwarded by the host as diagnostics.updated) ----
// Human labels for the check ids collect_diagnostics() returns. Unknown ids
// fall back to the id itself so a newer hub never hides a failing check.
const CHECK_LABELS = {
  hub: "Panel hub",
  hub_version: "Panel hub version",
  mode: "Live Revit mode",
  revit_bridge: "Revit connection",
  workspace: "Workspace folder",
  ai_provider: "AI provider for chat"
};

let setupExpanded = false;
let diagnosticsRetry = null;
const HUB_RECOVERY = "Restart Revit to start the panel hub, or run 'aec-model-bridge-panel-server' in a terminal, then press Refresh. See docs/troubleshooting.md if it keeps failing.";

// approval_mode is a choice the person made (the mode chip shows it), not a fault: it must not
// count as a step to fix or replace a real error such as "hub unreachable" with its advice.
function failingChecks() {
  return (state.diagnostics?.checks || []).filter((check) => !check.ok && check.id !== "approval_mode");
}

// The specific recovery step for a failing check (by id), or the first failing
// check's step when no id is given. Empty string when there is nothing to say.
function nextStepFor(checkId) {
  const failing = failingChecks().filter((check) => check.next_step && (!checkId || check.id === checkId));
  return failing.length ? failing[0].next_step : "";
}

// Replaces the generic "Could not reach the hub" transport error with the
// failing check's next step when diagnostics know better.
function friendlyError(message) {
  const step = nextStepFor("hub");
  if (step && /could not reach the aec model bridge hub/i.test(message || "")) {
    return step;
  }
  return message;
}

function readySummary() {
  const mode = effectivePanelMode();
  const connected = (state.diagnostics?.checks || []).some((check) => check.id === "revit_bridge" && check.ok);
  const lead = connected ? "Connected to Revit. " : "";
  if (mode === "look_only") return `${lead}The assistant can only read.`;
  if (mode === "auto" || mode === "dev") return `${lead}Approval is off.`;
  return `${lead}Changes need your approval.`;
}

// Alerts from renderAlerts(), shown in the status strip next to the failing checks.
let alertItems = [];

function joinNames(names) {
  return names.join(" \u00b7 ");
}

// One compact strip: a label, a one-line summary and a caret. It expands to the alerts and checks.
function renderSetup() {
  const checks = state.diagnostics?.checks;
  const failing = failingChecks();
  let mode = "checking";
  if (checks) {
    mode = failing.length === 0 ? "ready" : "blocked";
  }
  const notices = alertItems.length;
  const issueNames = failing.map((check) => CHECK_LABELS[check.id] || check.id).concat(alertItems.map((item) => item[1]));
  let label;
  let summary = "";
  if (mode === "ready" && notices === 0) {
    label = "Ready";
    summary = readySummary();
  } else if (mode === "ready") {
    label = `${notices} notice${notices === 1 ? "" : "s"}`;
    summary = joinNames(issueNames);
  } else if (mode === "blocked") {
    label = `${failing.length + notices} to fix`;
    summary = joinNames(issueNames);
  } else {
    label = "Checking\u2026";
    summary = joinNames(issueNames);
  }
  setupCard.dataset.state = mode;
  setupCard.dataset.notices = String(notices);
  const approvalOff = effectivePanelMode() === "auto" || effectivePanelMode() === "dev";
  setupCard.dataset.caution = mode === "ready" && notices === 0 && approvalOff ? "1" : "0";
  setupLabel.textContent = label;
  setupSummary.textContent = summary;
  setupStatus.textContent = summary ? `${label}. ${summary}` : label;
  setupToggle.setAttribute("aria-expanded", String(setupExpanded));
  setupBody.hidden = !setupExpanded;
  setupList.hidden = !checks || checks.length === 0;
  setupList.innerHTML = (checks || []).map((check) => `
    <li class="setup-item ${check.ok ? "is-pass" : "is-fail"}">
      <span class="setup-glyph" aria-hidden="true">${check.ok ? "\u2713" : "!"}</span>
      <div>
        <strong>${escapeHtml(CHECK_LABELS[check.id] || check.id)}: ${check.ok ? "OK" : "Needs attention"}</strong>
        <p>${escapeHtml(check.detail || "")}</p>
        ${!check.ok && check.next_step ? `<p class="setup-next"><strong>What to do:</strong> ${escapeHtml(check.next_step)}</p>` : ""}
      </div>
    </li>`).join("");
}

function requestDiagnostics() {
  clearTimeout(diagnosticsRetry);
  diagnosticsRetry = null;
  setupCard.dataset.state = "checking";
  setupLabel.textContent = "Checking\u2026";
  setupSummary.textContent = "";
  setupStatus.textContent = "Checking setup\u2026";
  postToHost("diagnostics.refresh");
}

// The hub could not be reached at all, so there is no /diagnostics payload.
// This is derived from the transport failure, not fixture data.
function setHubUnreachable(message) {
  state.diagnostics = {
    ok: false,
    checks: [{
      id: "hub",
      ok: false,
      detail: message || "The panel could not reach the AEC Model Bridge hub.",
        next_step: HUB_RECOVERY
    }]
  };
  renderSetup();
  renderSystemState();
  // Revit's bridge can already be online while the separate Python hub starts.
  // Retry the diagnostics endpoint itself; serverRunning is not its readiness signal.
  clearTimeout(diagnosticsRetry);
  diagnosticsRetry = setTimeout(requestDiagnostics, 5000);
}

function renderAlerts() {
  const alerts = [];
  if (!state.host) {
    alerts.push(["warning", "Waiting for host", "The panel has not received Revit status yet."]);
  } else {
    if (!isHubOnline()) {
      alerts.push(["error", "Hub down", nextStepFor("hub") || "Start the bridge server from the Connection panel."]);
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
    if (state.providers && !state.providers.claude && !state.providers.codex) {
      alerts.push(["warning", "No AI provider available", nextStepFor("ai_provider") || "Set the MCP_REVIT_ANTHROPIC_API_KEY environment variable and restart Revit, or install and sign in to the claude/codex CLI."]);
    }
  }

  alertItems = alerts;
  systemAlerts.hidden = alerts.length === 0;
  systemAlerts.innerHTML = alerts.map(([level, heading, detail]) => `
    <div class="alert ${escapeHtml(level)}">
      <span class="alert-marker" aria-hidden="true"></span>
      <div>
        <strong>${escapeHtml(heading)}</strong>
        <p>${escapeHtml(detail)}</p>
      </div>
    </div>`).join("");
  renderSetup();
}

function updateToolAvailability() {
  const blocked = modelActionsBlocked();
  const chatBlocked = blocked || llmIsOffline();
  document.querySelectorAll("[data-action], [data-plan], [data-report], [data-select-plan]").forEach((control) => {
    // A plan whose review could not be shown stays unapprovable whatever the host state is.
    control.disabled = blocked || control.dataset.reviewBlocked === "1";
  });
  syncApproveSelected();
  if (chat) {
    chat.setDisabled(chatBlocked, chatBlocked ? "Chat is unavailable. See the alerts above." : "");
  }
}

function applyProviderAvailability() {
  if (!state.providers || !chatProvider) {
    return;
  }
  Array.from(chatProvider.options).forEach((option) => {
    option.dataset.baseLabel = option.dataset.baseLabel || option.textContent;
    const available = !!state.providers[option.value];
    option.disabled = !available;
    option.textContent = available ? option.dataset.baseLabel : `${option.dataset.baseLabel} (unavailable)`;
  });
  if (chatProvider.selectedOptions[0]?.disabled) {
    const firstAvailable = Array.from(chatProvider.options).find((option) => !option.disabled);
    if (firstAvailable) {
      chatProvider.value = firstAvailable.value;
    }
  }
}

function renderSystemState() {
  renderHostStatus();
  renderAlerts();
  updateToolAvailability();
}

// Mode chip + chat banner. The hub reports approval_mode in /diagnostics; the panel
// shows it, including the separate persistent Dev override chosen in Settings.
const MODE_CHIP = {
  look_only: ["Look only", "Look only: the assistant reads the model and cannot change it. Change in settings."],
  ask_first: ["Ask me first", "Ask me first: changes need your approval in this panel. Change in settings."],
  auto: ["Auto: not recommended", "Auto: approvals are skipped for a limited time. Switch back in settings."],
  dev: ["Dev: on", "Dev: approvals are skipped across this workspace until you switch it off in Settings. Actions are logged."]
};

function effectivePanelMode() {
  const mode = state.diagnostics && state.diagnostics.approval_mode;
  return mode === "auto" && state.diagnostics.dev_mode === true ? "dev" : mode;
}

function renderMode() {
  const mode = effectivePanelMode();
  const known = Object.prototype.hasOwnProperty.call(MODE_CHIP, mode) ? mode : null;
  modeChip.dataset.mode = known || "unknown";
  const left = known === "auto" ? autoMinutesLeft() : null;
  modeChip.textContent = known
    ? (left !== null ? `Auto: ${left} min left` : MODE_CHIP[known][0])
    : "Mode unknown";
  modeChip.title = known ? MODE_CHIP[known][1] : "The hub has not reported its approval mode yet.";
  if (chat) {
    chat.setApprovalMode(known);
  }
}

// Chat card "Review N changes": approval itself only exists in the Plans view.
function reviewPlan(planId) {
  setView("plans");
  const item = Array.from(planList.children).find((child) => child.dataset && child.dataset.planId === planId);
  if (item) {
    item.focus();
    if (item.scrollIntoView) {
      item.scrollIntoView({ block: "nearest" });
    }
  } else {
    // Not in the list: more than PLAN_LIMIT plans are pending, or it is no longer pending.
    const note = document.createElement("p");
    note.className = "review-blocked";
    note.setAttribute("role", "alert");
    note.textContent = `Plan ${visibleText(planId)} is not shown in this panel (too many pending plans, or it is no longer pending). ` +
      `Use ${cliShowCommand(planId)} to read it.`;
    planList.prepend(note);
  }
}

function planStatusBadgeClass(status) {
  if (status === "approved" || status === "executed") return "success";
  if (status === "rejected") return "error";
  if (status === "rolled_back") return "idle";
  return "pending";
}

// Details are folded by default; Dev mode opens them. A toggle flips whichever default applies.
function detailsAreOpen(plan) {
  return state.detailsToggled.has(plan.id) !== (effectivePanelMode() === "dev");
}

// Only a plan that is still waiting for review can be approved or rejected.
// approved/executed/rolled_back/rejected plans are history: no decision buttons.
function isPlanActionable(plan) {
  return plan.status === "pending";
}

// Approve needs the plan's review (when it has one) to have been shown. Reject never does.
// An expired plan (hub flag `expired`) can never be approved here; it can still be rejected.
function isPlanApprovable(plan) {
  return isPlanActionable(plan) && !plan.expired && !plan.reviewBlocked && !plan.reviewPending
    && (!isUnboundPlan(plan) || state.confirmedUnbound.has(reviewKey(plan)));
}

// A plan with no binding cannot be tied to any document; approving it needs an explicit confirm.
function isUnboundPlan(plan) {
  return !plan.binding;
}

function normalizeDocName(name) {
  return String(name || "").trim().toLowerCase().replace(/\.rvt$/, "");
}

// True only when both the plan's bound title and the active document are known and differ.
function isBoundToOtherDocument(plan) {
  const bound = plan.binding && typeof plan.binding.doc_title === "string" ? plan.binding.doc_title : "";
  if (!bound || !hasActiveDocument()) return false;
  return normalizeDocName(bound) !== normalizeDocName(state.host.activeDocument);
}

function hostPid() {
  const pid = state.host && state.host.revitPid;
  return Number.isSafeInteger(pid) ? pid : null;
}

function hostGuid() {
  const guid = state.host && state.host.activeDocumentGuid;
  return typeof guid === "string" && guid ? guid : "";
}

function boundGuid(plan) {
  return plan.binding && typeof plan.binding.doc_guid === "string" ? plan.binding.doc_guid : "";
}

function boundPid(plan) {
  return plan.binding && Number.isSafeInteger(plan.binding.revit_pid) ? plan.binding.revit_pid : null;
}

// Both ids known and different: the plan was drafted in another Revit process.
function isBoundToOtherProcess(plan) {
  const bound = boundPid(plan);
  const live = hostPid();
  return bound !== null && live !== null && bound !== live;
}

// A bound plan that is not for this panel's session: other document (guid, or title when the host
// reports no guid) or other Revit process. Such plans are hidden until the person asks.
function isOtherSessionPlan(plan) {
  if (!plan.binding) return false;
  if (isBoundToOtherProcess(plan)) return true;
  const guid = hostGuid();
  const bound = boundGuid(plan);
  if (guid && bound) return guid !== bound;
  return !guid && isBoundToOtherDocument(plan);
}

function applyPlanScope() {
  const all = state.allPlans;
  state.plans = state.showOtherPlans ? all : all.filter((plan) => !isOtherSessionPlan(plan));
  state.otherHidden = all.length - state.plans.length;
}

function syncOtherBar() {
  const bar = document.getElementById("other-bar");
  if (!bar) return;
  bar.hidden = !(state.otherHidden > 0 || state.showOtherPlans);
  const note = document.getElementById("other-note");
  const toggle = document.getElementById("other-toggle");
  if (note) {
    note.textContent = state.showOtherPlans
      ? "Plans for other models are shown. Approve works only for the model open in this session."
      : `${state.otherHidden} plan${state.otherHidden === 1 ? "" : "s"} for other models hidden`;
  }
  if (toggle) {
    toggle.textContent = state.showOtherPlans ? "Hide" : "Show";
    toggle.setAttribute("aria-pressed", state.showOtherPlans ? "true" : "false");
  }
}

function formatExpiry(value) {
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? visibleText(value) : date.toLocaleString();
}

// Plans the person can reject in bulk: pending, and either approvable or expired
// (expired plans are the stale queue a coordinator wants to clear).
function selectedRejectablePlanIds() {
  const ok = new Set(state.plans.filter((plan) => isPlanActionable(plan) && (plan.expired || isPlanApprovable(plan))).map((plan) => plan.id));
  return Array.from(state.selectedPlanIds).filter((id) => ok.has(id));
}

// The confirm bar opens only from a click on Reject selected (rejectArmed); a click on Confirm
// does nothing unless the bar was opened that way.
let rejectArmed = false;

function hideRejectConfirm() {
  rejectArmed = false;
  const bar = document.getElementById("reject-confirm");
  if (bar) bar.hidden = true;
  syncBulkBar();
}

// The bulk footer shows only while something is ticked, and gives way to the confirm bar.
function syncBulkBar() {
  const bulkBar = document.getElementById("plan-bulk");
  const confirmBar = document.getElementById("reject-confirm");
  const ids = selectedRejectablePlanIds();
  if (rejectArmed && ids.length === 0) {
    rejectArmed = false;
    if (confirmBar) confirmBar.hidden = true;
  }
  if (rejectArmed) {
    const text = document.getElementById("reject-confirm-text");
    if (text) text.textContent = `Reject ${ids.length} selected plan(s)? This cannot be undone.`;
  }
  // One ticked plan uses its own card buttons; the footer is for two or more.
  const ticked = new Set(selectedActionablePlanIds().concat(ids)).size;
  if (bulkBar) bulkBar.hidden = rejectArmed || ticked < 2;
}

function syncExpiredBar() {
  const bar = document.getElementById("expired-bar");
  if (!bar) return;
  bar.hidden = !(state.expiredHidden > 0 || state.showExpired);
  const note = document.getElementById("expired-note");
  const toggle = document.getElementById("expired-toggle");
  if (note) note.textContent = state.showExpired ? "Expired plans are shown. They cannot be approved." : `${state.expiredHidden} expired plan(s) hidden`;
  if (toggle) {
    toggle.textContent = state.showExpired ? "Hide expired" : "Show expired";
    toggle.setAttribute("aria-pressed", state.showExpired ? "true" : "false");
  }
}

function reviewKey(plan) {
  return `${plan.id}:${plan.hash}`;
}

function selectedActionablePlanIds() {
  const actionable = new Set(state.plans.filter(isPlanApprovable).map((plan) => plan.id));
  return Array.from(state.selectedPlanIds).filter((id) => actionable.has(id));
}

// "Approve Selected" needs at least one ticked, still-pending plan.
function syncPlansBadge() {
  const pending = state.plans.filter(isPlanActionable).length;
  plansBadge.hidden = pending === 0;
  plansBadge.textContent = String(pending);
  const navButton = document.querySelector('.nav[data-view="plans"]');
  if (navButton) navButton.setAttribute("aria-label", pending ? `Plans, ${pending} pending` : "Plans");
}

function syncApproveSelected() {
  const count = document.getElementById("plan-selected-count");
  if (count) count.textContent = `${new Set(selectedActionablePlanIds().concat(selectedRejectablePlanIds())).size} selected`;
  syncPlansBadge();
  syncBulkBar();
  document.querySelectorAll('[data-action="approve-selected"]').forEach((button) => {
    button.disabled = modelActionsBlocked() || selectedActionablePlanIds().length === 0;
    button.textContent = `Approve ${selectedActionablePlanIds().length}`;
  });
  document.querySelectorAll('[data-action="reject-selected"]').forEach((button) => {
    button.disabled = modelActionsBlocked() || selectedRejectablePlanIds().length === 0;
    button.textContent = `Reject ${selectedRejectablePlanIds().length}`;
  });
}

// The inline confirm in a card exists only after a click on that card's Reject; a list
// refresh rebuilds the cards and clears it, so a Confirm click can never outlive its prompt.
let singleRejectId = null;

function closeSingleReject(restoreFocus) {
  const open = singleRejectId;
  singleRejectId = null;
  planList.querySelectorAll(".plan-reject-confirm").forEach((node) => node.remove());
  if (restoreFocus && open) {
    const card = Array.from(planList.children).find((child) => child.dataset && child.dataset.planId === open);
    const button = card && card.querySelector('[data-decision="reject"]');
    if (button && button.focus) button.focus();
  }
}

function openSingleReject(planId, hash) {
  closeSingleReject(false);
  const card = Array.from(planList.children).find((child) => child.dataset && child.dataset.planId === planId);
  const actions = card && card.querySelector(".item-actions");
  if (!actions) return;
  const box = document.createElement("div");
  box.className = "plan-reject-confirm";
  box.setAttribute("role", "group");
  box.setAttribute("aria-label", "Confirm reject");
  const text = document.createElement("span");
  text.setAttribute("role", "alert");
  text.textContent = "Reject this plan? This cannot be undone.";
  const cancel = document.createElement("button");
  cancel.type = "button";
  cancel.dataset.rejectSingle = "cancel";
  cancel.textContent = "Cancel";
  const confirm = document.createElement("button");
  confirm.type = "button";
  confirm.dataset.rejectSingle = "confirm";
  confirm.dataset.rejectFor = planId;
  confirm.dataset.hash = hash;
  confirm.textContent = "Confirm";
  box.append(text, cancel, confirm);
  actions.append(box);
  singleRejectId = planId;
  if (cancel.focus) cancel.focus();
}

document.body.addEventListener("keydown", (event) => {
  if (event.key === "Escape" && singleRejectId) {
    event.preventDefault();
    closeSingleReject(true);
  }
});

function renderPlans() {
  planList.innerHTML = "";
  singleRejectId = null;
  hideRejectConfirm();
  syncExpiredBar();
  syncOtherBar();
  if (state.plans.length === 0) {
    renderEmpty(planList, "No pending plans", "", true);
    syncPlansBadge();
    syncBulkBar();
    return;
  }

  state.plans.forEach((plan) => {
    const item = document.createElement("article");
    item.className = "item plan-card";
    item.dataset.planId = plan.id;
    item.tabIndex = -1;
    const id = escapeHtml(plan.id);
    const label = escapeHtml(plan.title);
    const hash = escapeHtml(plan.hash);
    const actionable = isPlanActionable(plan);
    // The review block (tool, arguments, before value, and for hash_version 2 the rationale
    // the hash covers) is what the person approves, so it is shown only while a decision is
    // still open; settled plans keep a badge. If the review cannot be shown, Approve is off.
    const slot = document.createElement("div");
    slot.className = "plan-review-slot";
    plan.reviewBlocked = false;
    plan.reviewPending = false;
    if (actionable) {
      if (!plan.reviewState.ok) {
        plan.reviewBlocked = true;
      } else if (plan.reviewState.version === 2 && !state.openedReviews.has(reviewKey(plan))) {
        // Built only when asked for, and Approve waits for it: the person must have seen it.
        plan.reviewPending = true;
        const open = document.createElement("button");
        open.type = "button";
        open.dataset.openReview = plan.id;
        open.textContent = "Show the review to enable Approve";
        const hint = document.createElement("p");
        hint.className = "review-pending";
        hint.textContent = "This plan carries a review that the approval hash covers. Read it before you approve.";
        slot.append(hint, open);
      } else {
        plan.reviewBlocked = !fillReviewSlot(slot, plan.reviewState);
      }
    }
    const approvable = isPlanApprovable(plan);
    const lockedUnbound = actionable && !plan.expired && isUnboundPlan(plan) && !plan.reviewBlocked && !plan.reviewPending
      && !state.confirmedUnbound.has(reviewKey(plan));
    const select = approvable || (actionable && plan.expired)
      ? `<label class="plan-select"><input type="checkbox" data-select-plan="${id}" aria-label="Select plan ${label}"${state.selectedPlanIds.has(plan.id) ? " checked" : ""}></label>`
      : lockedUnbound
        ? `<label class="plan-select is-locked"><input type="checkbox" disabled aria-label="Select plan ${label}: locked until you confirm the warning" aria-describedby="plan-unbound-${id}"></label>`
        : "";
    const blockedAttr = !approvable && actionable ? ' disabled data-review-blocked="1"' : "";
    const mismatch = actionable && !plan.expired && (isBoundToOtherDocument(plan) || isBoundToOtherProcess(plan) || (!!hostGuid() && !!boundGuid(plan) && hostGuid() !== boundGuid(plan)));
    const unbound = actionable && !plan.expired && isUnboundPlan(plan);
    const boundTitle = plan.binding && typeof plan.binding.doc_title === "string" ? plan.binding.doc_title : "";
    const metaParts = [];
    if (boundTitle) metaParts.push(`Bound to document: ${escapeHtml(visibleText(boundTitle))}`);
    if (plan.expiresAt) metaParts.push(`Expires: ${escapeHtml(formatExpiry(plan.expiresAt))}`);
    const metaLine = metaParts.length ? `<p class="plan-meta">${metaParts.join(". ")}.</p>` : "";
    const pidNote = isBoundToOtherProcess(plan)
      ? ` It was drafted in Revit process ${escapeHtml(String(boundPid(plan)))}; this panel is in process ${escapeHtml(String(hostPid()))}.`
      : "";
    const warnLine = mismatch
      ? `<p class="review-blocked" id="plan-warn-${id}" role="alert">Warning: this plan is bound to ${escapeHtml(visibleText(boundTitle) || "another document")}, but the active document is ${escapeHtml(visibleText(state.host.activeDocument))}.${pidNote} The hub refuses the approval unless the bound document is active.</p>`
      : "";
    const unboundLine = unbound
      ? `<div class="review-blocked" id="plan-unbound-${id}" role="alert"><p>Warning: this plan is not bound to any document. It can run on whichever model is open when you approve.</p>
        <label><input type="checkbox" data-confirm-unbound="${id}"${state.confirmedUnbound.has(reviewKey(plan)) ? " checked" : ""}> I understand this plan is not tied to a document</label></div>`
      : "";
    const expiredLine = plan.expired
      ? `<p class="review-blocked" id="plan-expired-${id}">This plan has expired and cannot be approved. Reject it, or draft a new plan.</p>`
      : "";
    const describedBy = [plan.expired ? `plan-expired-${id}` : "", mismatch ? `plan-warn-${id}` : "", unbound ? `plan-unbound-${id}` : ""].filter(Boolean).join(" ");
    const describedAttr = describedBy ? ` aria-describedby="${describedBy}"` : "";
    const actions = actionable
      ? `<div class="item-actions"><span class="item-actions-for">${label}</span>
        <button type="button" data-plan="${id}" data-hash="${hash}" class="primary" data-decision="approve" aria-label="Approve plan ${label}"${describedAttr}${blockedAttr}>Approve</button>
        <button type="button" data-plan="${id}" data-hash="${hash}" data-decision="reject" aria-label="Reject plan ${label}">Reject</button>
      </div>`
      : "";
    const block = actionable ? buildPreviewBlock(plan.preview, plan.blastRadius, plan.id, plan.rollbackPreview) : null;
    const previewRows = isPlainObject(plan.preview) && Array.isArray(plan.preview.rows) ? plan.preview.rows : [];
    const rolledBack = actionable
      ? buildRollbackPreviewBlock(plan.rollbackPreview, previewRows.filter(isPlainObject).map((row) => row.element_id).filter(isKnown))
      : null;
    // A preview that was not rolled back, or that failed, must be seen before approving: it is never folded away.
    const rbRecord = isPlainObject(plan.rollbackPreview) ? plan.rollbackPreview : {};
    const rollbackLoud = !!rolledBack && (rbRecord.rolled_back === false || rbRecord.status === "failed");
    const hasPreview = !!block;
    const preMarkup = actionable ? `<pre class="plan-review">${escapeHtml(clipActions(plan.review))}</pre>` : "";
    const detailsOpen = detailsAreOpen(plan);
    if (mismatch || unbound || plan.expired) item.classList.add("is-warn");
    item.innerHTML = `
      <div class="item-head">
        ${select}<div class="plan-title"><h2>${label}</h2><span class="plan-id">${id}</span></div>
        <span class="badge ${planStatusBadgeClass(plan.status)}">${escapeHtml(String(plan.status).replace(/_/g, " "))}</span>
      </div>
      ${plan.detail && plan.detail !== plan.title ? `<p class="plan-detail">${escapeHtml(plan.detail)}</p>` : ""}
      ${expiredLine}${warnLine}${unboundLine}
      ${actionable ? '<div data-preview-mount></div>' : ""}
      ${rollbackLoud ? '<div data-rollback-loud></div>' : ""}
      ${actionable && !hasPreview ? preMarkup : ""}
      <div data-review-mount></div>
      ${actionable ? `<button type="button" class="link-btn" data-toggle-details="${id}" aria-expanded="${detailsOpen ? "true" : "false"}" aria-controls="plan-details-${id}">${detailsOpen ? "Hide details" : "Show details"}</button>` : ""}
      <div class="plan-details" id="plan-details-${id}"${detailsOpen && actionable ? "" : " hidden"}>
        ${metaLine}
        <p class="plan-cli">Plan <code>${id}</code>. To read it in full: <code class="plan-cli-command">${escapeHtml(cliShowCommand(plan.id))}</code>
          <button type="button" class="review-more" data-copy-command="${id}">Copy command</button></p>
        <div data-rollback-mount></div>
        ${actionable && hasPreview ? preMarkup : ""}
      </div>
      ${actions}`;
    const previewMount = item.querySelector("[data-preview-mount]");
    if (previewMount) {
      if (block) previewMount.replaceWith(block);
      else previewMount.remove();
    }
    const loudMount = item.querySelector("[data-rollback-loud]");
    if (loudMount) loudMount.replaceWith(rolledBack);
    const rollbackMount = item.querySelector("[data-rollback-mount]");
    if (rolledBack && !rollbackLoud) rollbackMount.replaceWith(rolledBack);
    else rollbackMount.remove();
    const pre = item.querySelector("pre.plan-review");
    if (pre && plan.review.length > ACTIONS_CLIP) {
      const more = document.createElement("button");
      more.type = "button";
      more.className = "review-more";
      more.setAttribute("aria-expanded", "false");
      more.textContent = `Show all actions (${plan.review.length - ACTIONS_CLIP} more characters)`;
      more.addEventListener("click", () => {
        const open = more.getAttribute("aria-expanded") === "true";
        pre.textContent = open ? clipActions(plan.review) : plan.review;
        more.textContent = open ? `Show all actions (${plan.review.length - ACTIONS_CLIP} more characters)` : "Show less";
        more.setAttribute("aria-expanded", open ? "false" : "true");
      });
      pre.after(more);
    }
    const mount = item.querySelector("[data-review-mount]");
    if (plan.reviewBlocked && actionable) {
      const note = document.createElement("p");
      note.className = "review-blocked";
      note.setAttribute("role", "alert");
      const reason = plan.reviewState.reason ? ` (${visibleText(plan.reviewState.reason).slice(0, 300)})` : "";
      note.textContent = REVIEW_BLOCKED_MESSAGE.replace("aec-model-bridge-approve show <plan id>", cliShowCommand(plan.id)) + reason;
      mount.replaceWith(note);
    } else if (actionable) {
      mount.replaceWith(slot);
    } else {
      mount.remove();
    }
    planList.appendChild(item);
  });
  if (state.plansOmitted > 0) {
    const more = document.createElement("p");
    more.className = "review-blocked";
    more.textContent = `${state.plansOmitted} more pending plan(s) are not shown. Use aec-model-bridge-approve list to see them.`;
    planList.appendChild(more);
  }
  syncApproveSelected();
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
    item.className = "item plan-card";
    const selectButton = finding.elementUid
      ? `<div class="item-actions">
          <button type="button" data-select-uid="${escapeHtml(finding.elementUid)}">Select in Revit</button>
        </div>`
      : "";
    item.innerHTML = `
      <div class="item-head">
        <h2>${escapeHtml(finding.title)}</h2>
        <span class="badge ${escapeHtml(finding.severity)}">${escapeHtml(finding.severity)}</span>
      </div>
      <p>${escapeHtml(finding.detail)}</p>
      ${selectButton}`;
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
    item.className = "item plan-card";
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

function renderEmpty(container, heading, detail, compact) {
  const item = document.createElement("article");
  item.className = compact ? "empty is-compact" : "empty";
  const iconView = { "plan-list": "plans", "finding-list": "findings", "report-list": "reports", "run-log": "log" }[container.id];
  const icon = iconView
    ? `<span class="empty-tile" aria-hidden="true"><svg class="ico" viewBox="0 0 256 256"><use href="#nav-${iconView}"/></svg></span>`
    : "";
  item.innerHTML = `${icon}<strong>${escapeHtml(heading)}</strong>${detail ? `<p>${escapeHtml(detail)}</p>` : ""}`;
  container.appendChild(item);
}

document.querySelectorAll(".nav").forEach((button) => {
  button.addEventListener("click", () => setView(button.dataset.view));
});

// The one Refresh: setup check plus the list behind the active view.
setupRefresh.addEventListener("click", () => {
  requestDiagnostics();
  if (currentView === "plans") {
    postToHost("plans.refresh");
    addLog("Plans refreshed", "Requested pending plans from the host.");
  } else if (currentView === "reports") {
    postToHost("reports.refresh");
    addLog("Reports refreshed", "Requested available reports from the host.");
  }
});
setupToggle.addEventListener("click", () => {
  setupExpanded = !setupExpanded;
  renderSetup();
});

document.body.addEventListener("click", (event) => {
  const target = event.target;
  if (!(target instanceof HTMLElement)) {
    return;
  }

  const copyFor = target.dataset.copyCommand;
  if (copyFor) {
    const command = cliShowCommand(copyFor);
    try {
      if (navigator.clipboard && navigator.clipboard.writeText) {
        navigator.clipboard.writeText(command).catch(() => {});
      }
    } catch (error) { /* clipboard may be unavailable in WebView2; the command is shown on the card */ }
    addLog("Command copied", command);
    return;
  }

  const toggleFor = target.dataset.toggleDetails;
  if (toggleFor) {
    if (state.detailsToggled.has(toggleFor)) state.detailsToggled.delete(toggleFor);
    else state.detailsToggled.add(toggleFor);
    const known = state.plans.find((candidate) => candidate.id === toggleFor);
    const open = known ? detailsAreOpen(known) : false;
    const panel = document.getElementById(`plan-details-${toggleFor}`);
    if (panel) panel.hidden = !open;
    target.setAttribute("aria-expanded", open ? "true" : "false");
    target.textContent = open ? "Hide details" : "Show details";
    return;
  }

  const openReview = target.dataset.openReview;
  if (openReview) {
    const known = state.plans.find((candidate) => candidate.id === openReview);
    if (known) {
      state.openedReviews.add(reviewKey(known));
      renderPlans();
      updateToolAvailability();
      const card = Array.from(planList.children).find((child) => child.dataset && child.dataset.planId === openReview);
      if (card && card.focus) card.focus();
    }
    return;
  }

  const action = target.dataset.action;
  if (action === "approve-selected") {
    // The host has no bulk message: approve each ticked, still-pending plan
    // through the same per-plan plan.approve it already handles.
    const ids = selectedActionablePlanIds();
    if (ids.length === 0) {
      addLog("Nothing selected", "Tick one or more pending plans first.");
    } else {
      ids.forEach((planId) => {
        const plan = state.plans.find((candidate) => candidate.id === planId);
        postToHost("plan.approve", { planId, planHash: plan ? plan.hash || "" : "" });
        state.selectedPlanIds.delete(planId);
      });
      addLog("Approval requested", `${ids.length} selected plan(s) sent to the host.`);
      renderPlans();
    }
  }
  if (action === "reject-selected") {
    // Same per-plan plan.reject the single Reject button sends; confirmed first, with the count.
    const ids = selectedRejectablePlanIds();
    if (ids.length === 0) {
      addLog("Nothing selected", "Tick one or more pending plans first.");
    } else {
      rejectArmed = true;
      document.getElementById("reject-confirm-text").textContent = `Reject ${ids.length} selected plan(s)? This cannot be undone.`;
      document.getElementById("reject-confirm").hidden = false;
      syncBulkBar();
      const cancelButton = document.querySelector('[data-action="reject-cancel"]');
      if (cancelButton && cancelButton.focus) cancelButton.focus();
    }
  }
  if (action === "reject-cancel") {
    hideRejectConfirm();
  }
  if (action === "reject-confirm") {
    const ids = rejectArmed ? selectedRejectablePlanIds() : [];
    hideRejectConfirm();
    ids.forEach((planId) => {
      const plan = state.plans.find((candidate) => candidate.id === planId);
      postToHost("plan.reject", { planId, planHash: plan ? plan.hash || "" : "" });
      state.selectedPlanIds.delete(planId);
    });
    if (ids.length > 0) addLog("Reject requested", `${ids.length} selected plan(s) sent to the host.`);
    renderPlans();
  }
  if (action === "toggle-other-plans") {
    state.showOtherPlans = !state.showOtherPlans;
    applyPlanScope();
    renderPlans();
    if (chat) chat.setProposals(state.plans);
  }
  if (action === "toggle-expired") {
    state.showExpired = !state.showExpired;
    syncExpiredBar();
    postToHost("plans.refresh", { includeExpired: state.showExpired });
  }
  if (action === "run-health") {
    postToHost("qaqc.runHealthCheck");
    addLog("Health check requested", "QA/QC run sent to the host.");
  }
  if (action === "export-excel") {
    postToHost("reports.exportExcel");
    addLog("Report export requested", "Excel export sent to the host.");
  }
  const rejectSingle = target.dataset.rejectSingle;
  if (rejectSingle === "cancel") {
    closeSingleReject(true);
    return;
  }
  if (rejectSingle === "confirm") {
    const forId = target.dataset.rejectFor;
    const open = singleRejectId;
    closeSingleReject(false);
    if (!forId || forId !== open) return;
    postToHost("plan.reject", { planId: forId, planHash: target.dataset.hash || "" });
    addLog("Plan reject", forId);
    return;
  }

  const planId = target.dataset.plan;
  if (planId) {
    const decision = target.dataset.decision;
    if (decision === "reject") {
      openSingleReject(planId, target.dataset.hash || "");
      return;
    }
    const known = state.plans.find((candidate) => candidate.id === planId);
    if (decision === "approve" && (!known || !isPlanApprovable(known))) {
      addLog("Approve blocked", REVIEW_BLOCKED_MESSAGE);
      return;
    }
    // planHash is the hash of the plan this list was rendered from; the hub refuses
    // the approval if the plan changed since.
    postToHost(`plan.${decision}`, { planId, planHash: target.dataset.hash || "" });
    addLog(`Plan ${decision}`, planId);
  }

  const reportId = target.dataset.report;
  if (reportId) {
    postToHost("reports.open", { reportId });
    addLog("Report opened", reportId);
  }

  const selectUid = target.dataset.selectUid;
  if (selectUid) {
    postToHost("selection.set", { elementUids: [selectUid] });
    addLog("Selection requested", selectUid);
  }
});

document.body.addEventListener("change", (event) => {
  const target = event.target;
  if (target instanceof HTMLElement && target.dataset.confirmUnbound) {
    const plan = state.plans.find((candidate) => candidate.id === target.dataset.confirmUnbound);
    if (!plan) return;
    if (target.checked) state.confirmedUnbound.add(reviewKey(plan));
    else state.confirmedUnbound.delete(reviewKey(plan));
    renderPlans();
    const again = Array.from(planList.querySelectorAll("[data-confirm-unbound]")).find((node) => node.dataset.confirmUnbound === plan.id);
    if (again) again.focus();
    return;
  }
  if (!(target instanceof HTMLElement) || !target.dataset.selectPlan) {
    return;
  }
  if (target.checked) {
    state.selectedPlanIds.add(target.dataset.selectPlan);
  } else {
    state.selectedPlanIds.delete(target.dataset.selectPlan);
  }
  syncApproveSelected();
});

severityFilter.addEventListener("change", renderFindings);

approvalModeSelect.addEventListener("change", () => {
  autoMinutesLabel.hidden = approvalModeSelect.value !== "auto";
});

// The cards are the control; the hidden select keeps the value the host message is built from.
// Auto and Dev never switch on from one click: a confirm panel names what changes first.
let pendingMode = null;

function confirmCopy(mode) {
  const minutes = Number(autoMinutesSelect.value) || 30;
  if (mode === "auto") {
    return {
      text: `Turn approvals OFF for ${minutes} minutes? While Auto is on, the assistant can change the model without showing you a plan first. It switches back to Ask me first by itself.`,
      ok: "Turn on Auto"
    };
  }
  return {
    text: "Dev mode skips your approval for every change, in every session that uses this workspace, until you switch it off. It stays on across documents and restarts. Writes are still logged.",
    ok: "Turn on Dev"
  };
}

function showModeConfirm(mode) {
  pendingMode = mode;
  approvalModeSelect.value = mode;
  autoMinutesLabel.hidden = mode !== "auto";
  const copy = confirmCopy(mode);
  modeConfirmText.textContent = copy.text;
  modeConfirmOk.textContent = copy.ok;
  modeConfirm.hidden = false;
  renderModeCards();
  if (modeConfirmCancel.focus) modeConfirmCancel.focus();
}

function hideModeConfirm() {
  pendingMode = null;
  modeConfirm.hidden = true;
  const mode = effectivePanelMode();
  if (mode === "auto" || mode === "dev" || mode === "ask_first") approvalModeSelect.value = mode;
  autoMinutesLabel.hidden = approvalModeSelect.value !== "auto";
  renderModeCards();
}

function renderModeCards() {
  const mode = effectivePanelMode();
  const locked = !mode || mode === "look_only";
  document.querySelectorAll("[data-mode-pick]").forEach((card) => {
    const pick = card.dataset.modePick;
    const selected = pendingMode ? pick === pendingMode : pick === mode;
    card.setAttribute("aria-checked", selected ? "true" : "false");
    card.disabled = locked || pick === "look_only";
  });
}

modeCardsEl.addEventListener("click", (event) => {
  const card = event.target && event.target.closest ? event.target.closest("[data-mode-pick]") : null;
  if (!card || card.disabled || card.getAttribute("aria-checked") === "true") return;
  const pick = card.dataset.modePick;
  if (pick === "ask_first") {
    hideModeConfirm();
    approvalModeSelect.value = "ask_first";
    postToHost("settings.save", { approvalMode: "ask_first" });
    addLog("Approval mode requested", "Ask me first");
    return;
  }
  showModeConfirm(pick);
});

autoMinutesSelect.addEventListener("change", () => {
  if (pendingMode === "auto") showModeConfirm("auto");
});

modeConfirmCancel.addEventListener("click", hideModeConfirm);

settingsForm.addEventListener("submit", (event) => {
  event.preventDefault();
  const mode = pendingMode;
  if (!mode || effectivePanelMode() === "look_only") return;
  const minutes = Number(autoMinutesSelect.value) || 30;
  postToHost("settings.save", { approvalMode: mode, minutes, confirm: true });
  addLog("Approval mode requested", mode === "dev" ? "Dev until switched off" : `Auto for ${minutes} minutes`);
  hideModeConfirm();
});

autoOffButton.addEventListener("click", () => {
  if (effectivePanelMode() === "look_only") return;
  hideModeConfirm();
  approvalModeSelect.value = "ask_first";
  autoMinutesLabel.hidden = true;
  postToHost("settings.save", { approvalMode: "ask_first" });
  addLog("Approval mode requested", "Ask me first");
});

// Auto is a time-limited window: keep the chip's countdown honest and, when it runs out,
// ask the hub what is in force now instead of assuming.
let autoTicker = null;
function autoMinutesLeft() {
  const at = state.diagnostics && state.diagnostics.auto_expires_at;
  return at ? Math.max(0, Math.ceil((at * 1000 - Date.now()) / 60000)) : null;
}
let devWasOn = false;
function syncAutoControls() {
  const mode = effectivePanelMode();
  const isAuto = mode === "auto";
  const isDev = mode === "dev";
  const locked = !mode || mode === "look_only";
  approvalModeSelect.disabled = locked;
  modeConfirmOk.disabled = locked;
  autoMinutesSelect.disabled = locked;
  devBar.hidden = !(isAuto || isDev);
  devBarText.textContent = isDev ? "Dev skips approval. Writes are audited." : "Auto skips approval until the timer ends. Writes are audited.";
  autoOffButton.textContent = isDev ? "Turn Dev off" : "Back to Ask me first";
  document.documentElement.dataset.mode = mode || "unknown";
  if (isDev !== devWasOn) {
    devWasOn = isDev;
    renderPlans();
  }
  if (!pendingMode && (isAuto || isDev || mode === "ask_first")) {
    approvalModeSelect.value = mode;
    autoMinutesLabel.hidden = mode !== "auto";
  }
  renderModeCards();
  if (isAuto && !autoTicker) {
    autoTicker = setInterval(() => {
      if (autoMinutesLeft() === 0) {
        clearInterval(autoTicker);
        autoTicker = null;
        requestDiagnostics();
      } else {
        renderMode();
      }
    }, 15000);
  } else if (!isAuto && autoTicker) {
    clearInterval(autoTicker);
    autoTicker = null;
  }
}

// Maps for the raw hub tool results the host forwards after a real MCP tool
// call (see packages/revit-bridge-addin/src/UI/BridgePanel.xaml.cs's
// DispatchToHubAsync) into the shapes the render* functions above expect.
function mapFindings(hubResult) {
  const findings = (hubResult && hubResult.findings) || [];
  return findings.map((finding, index) => ({
    id: finding.element_uid ? `${finding.rule_id}:${finding.element_uid}` : `${finding.rule_id}:${index}`,
    elementUid: finding.element_uid || null,
    severity: finding.severity || "info",
    title: String(finding.rule_id || "finding").replace(/_/g, " ").replace(/\b\w/g, (c) => c.toUpperCase()),
    detail: finding.message || ""
  }));
}

// Model-controlled text: show control and format characters (ANSI/bidi/zero-width)
// as visible escapes, as the aec-model-bridge-approve CLI does.
function visibleText(value) {
  const escaped = String(value).replace(/[\p{Cc}\p{Cf}\p{Zl}\p{Zp}\p{Cs}\p{Co}\p{Cn}\u034F\u115F\u1160\u17B4\u17B5\u2800\u3164\uFFA0]/gu, (ch) => {
    // Newline and tab are layout, not hidden content: keep pretty-printed JSON readable.
    if (ch === "\n" || ch === "\t") return ch;
    const code = ch.codePointAt(0);
    const hex = code.toString(16).padStart(code <= 0xff ? 2 : code <= 0xffff ? 4 : 8, "0");
    return (code <= 0xff ? "\\x" : code <= 0xffff ? "\\u" : "\\U") + hex;
  });
  // More than two combining marks in a row can stack over neighbouring lines: keep two.
  return escaped.replace(/(\p{M}{2})\p{M}+/gu, (run, keep) => keep + `[${run.length - keep.length} more combining marks hidden]`);
}

function stringifyForReview(value) {
  try {
    const text = JSON.stringify(value === undefined ? null : value, null, 2);
    return visibleText(text === undefined ? String(value) : text);
  } catch (error) {
    return "(not displayable)";
  }
}

// Everything the person approves: each action's tool, arguments and before value.
// ---- Plan review block (hash_version 2) -------------------------------------------------
// The hub sends a validated copy as plan.review_view. Everything in it is untrusted model
// text: it is only ever put on the page with textContent, never innerHTML, and a plan the
// panel cannot show completely is not approvable here (fail closed).
const REVIEW_CLIP = 280;
const REVIEW_LIST_CAP = 100;
const PLAN_LIMIT = 50;
const ACTIONS_CLIP = 4000;

// The action text (tool, arguments incl. code, before values) is what the person approves:
// shown in full up to ACTIONS_CLIP characters, the rest behind "Show all actions".
function clipActions(text) {
  const t = String(text);
  if (t.length <= ACTIONS_CLIP) return t;
  let cut = t.slice(0, ACTIONS_CLIP);
  if (/[\uD800-\uDBFF]$/.test(cut)) cut = cut.slice(0, -1);
  return cut + "\u2026";
}
const PLAN_ID_SHAPE = /^plan_[0-9a-f]{12}$/;
const REVIEW_BLOCKED_MESSAGE =
  "This plan cannot be shown completely here, so it cannot be approved in this panel. " +
  "Use aec-model-bridge-approve show <plan id> in a terminal to read it, then approve or reject there.";

function cliShowCommand(planId) {
  return `aec-model-bridge-approve show ${visibleText(planId)}`;
}

function isPlainObject(value) {
  return value !== null && typeof value === "object" && !Array.isArray(value);
}

function reviewBlocked(reason) {
  return { ok: false, version: null, review: null, revertsPlanId: null, reason: String(reason || "") };
}

// Returns { ok, version, review, revertsPlanId, reason }. Unknown keys are ignored; a wrong
// type anywhere in a field the card shows makes the whole review unusable.
function planReviewState(plan) {
  try {
    const view = plan && plan.review_view;
    const claimsReview = Boolean(plan) && (plan.hash_version !== undefined || "review" in plan);
    const noReview = { ok: true, version: 1, review: null, revertsPlanId: null, reason: "" };
    if (!isPlainObject(view)) {
      return claimsReview ? reviewBlocked("the hub did not send a validated review") : noReview;
    }
    if (view.status === "none") {
      return claimsReview ? reviewBlocked("the plan carries a review but the hub marked it as having none") : noReview;
    }
    if (view.status !== "ok" || view.hash_version !== 2) {
      return reviewBlocked(view.error || "the hub reported the review as invalid");
    }
    const r = view.review;
    if (!isPlainObject(r) || typeof r.summary !== "string" || typeof r.reasoning !== "string") {
      return reviewBlocked("the review is malformed");
    }
    for (const key of ["citations", "assumptions", "excluded", "warnings", "conflicts"]) {
      if (!Array.isArray(r[key])) return reviewBlocked("the review is malformed");
    }
    const strOrNum = (v) => typeof v === "string" || Number.isSafeInteger(v);
    const okAll =
      r.citations.every((c) => isPlainObject(c) && typeof c.rule_id === "string" && typeof c.clause === "string" && typeof c.source === "string") &&
      r.assumptions.every((a) => typeof a === "string") &&
      r.excluded.every((x) => isPlainObject(x) && strOrNum(x.element_id) && typeof x.reason === "string") &&
      r.warnings.every((w) => typeof w === "string") &&
      r.conflicts.every((c) => isPlainObject(c) && strOrNum(c.element_id) &&
        ["parameter", "expected_current", "actual_current", "revert_to"].every((k) => typeof c[k] === "string"));
    if (!okAll) return reviewBlocked("the review is malformed");
    for (const key of ["citations", "assumptions", "excluded", "warnings", "conflicts"]) {
      if (r[key].length > REVIEW_LIST_CAP) {
        return reviewBlocked(`the review has ${r[key].length} ${key} entries; the panel shows at most ${REVIEW_LIST_CAP}`);
      }
    }
    const reverts = view.reverts_plan_id;
    if (reverts !== null && reverts !== undefined && !(typeof reverts === "string" && PLAN_ID_SHAPE.test(reverts))) {
      return reviewBlocked("the review is malformed");
    }
    return { ok: true, version: 2, review: r, revertsPlanId: reverts || null, reason: "" };
  } catch (error) {
    return reviewBlocked("the review could not be read");
  }
}

function reviewEl(tag, className, text) {
  const node = document.createElement(tag);
  if (className) node.className = className;
  if (text !== undefined) node.textContent = text;
  return node;
}

// Text clipped to REVIEW_CLIP characters with a button that shows the rest. Both states are
// text nodes; the full string is never dropped.
function clippedText(tag, className, raw) {
  const full = visibleText(raw);
  const node = reviewEl(tag, className);
  const chars = Array.from(full);
  if (chars.length <= REVIEW_CLIP) {
    node.textContent = full;
    return node;
  }
  const clipped = chars.slice(0, REVIEW_CLIP).join("") + "…";
  const body = reviewEl("span", "review-text", clipped);
  const hidden = chars.length - REVIEW_CLIP;
  const moreLabel = `Show more (${hidden} more characters)`;
  const more = reviewEl("button", "review-more", moreLabel);
  more.type = "button";
  more.setAttribute("aria-expanded", "false");
  more.addEventListener("click", () => {
    const open = more.getAttribute("aria-expanded") === "true";
    body.textContent = open ? clipped : full;
    more.textContent = open ? moreLabel : "Show less";
    more.setAttribute("aria-expanded", open ? "false" : "true");
  });
  node.append(body, " ", more);
  return node;
}

function reviewSection(title, count) {
  const section = reviewEl("section", "review-section");
  section.append(reviewEl("h3", "", count === undefined ? title : `${title} (${count})`));
  return section;
}

function reviewList(items, build) {
  const list = reviewEl("ul", "review-list");
  items.forEach((item) => {
    const li = reviewEl("li");
    li.append(build(item));
    list.append(li);
  });
  return list;
}

function labelled(parts) {
  const d = reviewEl("div");
  parts.forEach(([label, value]) => {
    d.append(reviewEl("span", "review-label", label), clippedText("span", "review-value", value), " ");
  });
  return d;
}

// Builds the review block for one plan from a state planReviewState accepted.
function buildReviewPanel(reviewState) {
  const root = reviewEl("div", "plan-review-block");
  root.dataset.reviewKind = reviewState.version === 2 ? "v2" : "v1";
  const hashNote = reviewEl("p", "review-hash-note");
  if (reviewState.version !== 2) {
    hashNote.textContent = "Hash version 1: this plan has no review block. The approval hash covers the actions only.";
    root.append(hashNote);
    return root;
  }
  const r = reviewState.review;
  hashNote.textContent =
    "Hash version 2. Covered by the approval hash: the actions above and everything in this review " +
    "(summary, reasoning, citations, assumptions, excluded elements, warnings, conflicts)" +
    (reviewState.revertsPlanId ? ", and the id of the plan it reverts" : "") +
    ". Also covered but not shown here: the creation time, the snapshot id and the skipped list (aec-model-bridge-approve show lists them). " +
    "Changing any of it after you approve cancels the approval. An AI model wrote this text: read it as a claim, not a fact.";
  root.append(hashNote);
  if (reviewState.revertsPlanId) {
    const p = reviewEl("p", "review-reverts");
    p.append("Reverts plan: ", reviewEl("code", "", visibleText(reviewState.revertsPlanId)));
    root.append(p);
  }
  const summary = reviewSection("Summary");
  summary.append(r.summary ? clippedText("p", "review-body", r.summary) : reviewEl("p", "review-empty", "(none)"));
  const reasoning = reviewSection("Reasoning");
  reasoning.append(r.reasoning ? clippedText("p", "review-body", r.reasoning) : reviewEl("p", "review-empty", "(none)"));
  root.append(summary, reasoning);

  const sections = [
    ["Citations", r.citations, (c) => labelled([["Rule", c.rule_id], ["Clause", c.clause || "(none)"], ["Source", c.source || "(none)"]])],
    ["Assumptions", r.assumptions, (a) => clippedText("span", "", a)],
    ["Excluded elements", r.excluded, (x) => labelled([["Element", String(x.element_id)], ["Reason", x.reason || "(none given)"]])],
    ["Warnings", r.warnings, (w) => clippedText("span", "", w)],
    ["Conflicts", r.conflicts, (c) => labelled([
      ["Element", String(c.element_id)], ["Parameter", c.parameter || "(none)"],
      ["Expected", c.expected_current || "(none)"], ["Actual", c.actual_current || "(none)"],
      ["Revert to", c.revert_to || "(none)"]])]
  ];
  sections.forEach(([title, items, build]) => {
    const section = reviewSection(title, items.length);
    if (items.length === 0) section.append(reviewEl("p", "review-empty", "None listed."));
    else section.append(reviewList(items, build));
    root.append(section);
  });
  return root;
}

// Fills the review slot of a plan card. Returns false when the review could not be shown,
// in which case the card disables Approve.
function fillReviewSlot(slot, reviewState) {
  if (!reviewState.ok) return false;
  try {
    slot.replaceChildren(buildReviewPanel(reviewState));
    return true;
  } catch (error) {
    slot.replaceChildren();
    return false;
  }
}

function planActionLines(actions) {
  return actions.map((action, index) => {
    const lines = [`${index + 1}. ${visibleText(action && action.tool)}`];
    const args = action && action.arguments;
    lines.push(`   arguments: ${stringifyForReview(args === undefined ? {} : args)}`);
    const before = action && action.diff && action.diff.before;
    if (before && Object.keys(before).length > 0) {
      lines.push(`   before: ${stringifyForReview(before)}`);
    }
    return lines.join("\n");
  });
}

const PREVIEW_ROW_CAP = 25;

// Before/after table and blast radius for a plan card. Every cell is a text node run through
// visibleText; a malformed or missing block yields null and the card simply omits it.
function isKnown(value) {
  return value !== null && value !== undefined && value !== "" && value !== "unknown";
}

// "Walls, Doors" or "Walls (not all known)"; "" when nothing is known, so the field is left out.
function knownList(values) {
  if (!Array.isArray(values)) return "";
  const known = values.filter(isKnown).map((x) => visibleText(x));
  if (known.length === 0) return "";
  return known.join(", ") + (known.length < values.length ? " (not all known)" : "");
}

// Rolled-back preview results by "<element id>|<parameter>", used to fill a before value the plan did not capture.
function rollbackBefores(rollback) {
  const found = new Map();
  const actions = isPlainObject(rollback) && Array.isArray(rollback.actions) ? rollback.actions : [];
  actions.forEach((a) => {
    if (isPlainObject(a) && a.ok === true && a.element_id !== undefined && typeof a.parameter === "string" && isKnown(a.before)) {
      found.set(`${a.element_id}|${a.parameter}`, a.before);
    }
  });
  return found;
}

// Before/after table and blast radius for a plan card. Every cell is a text node run through
// visibleText; a malformed or missing block yields null and the card simply omits it. A field the hub
// does not know (UniqueId, categories, levels, worksets) is left out rather than printed as "unknown" (#384).
function buildPreviewBlock(preview, radius, planId, rollback) {
  try {
    const rows = isPlainObject(preview) && Array.isArray(preview.rows) ? preview.rows.filter(isPlainObject) : [];
    if (!isPlainObject(radius) && rows.length === 0) return null;
    const root = reviewEl("div", "plan-preview");
    if (isPlainObject(radius)) {
      const head = reviewEl("p", "plan-blast");
      head.dataset.risk = visibleText(radius.risk);
      let text = `Risk: ${visibleText(radius.risk)}. ${visibleText(radius.element_count)} element(s), ${visibleText(radius.action_count)} action(s).`;
      [["Categories", radius.categories], ["Levels", radius.levels], ["Worksets", radius.worksets]].forEach(([label, list]) => {
        const shown = knownList(list);
        if (shown) text += ` ${label}: ${shown}.`;
      });
      head.textContent = text;
      root.append(head);
    }
    if (rows.length > 0) {
      const withUid = rows.some((row) => isKnown(row.unique_id));
      const fills = rollbackBefores(rollback);
      let filled = 0;
      const withElement = rows.some((row) => isKnown(row.element_id));
      const withParameter = rows.some((row) => isKnown(row.parameter));
      const cols = [["Element", ""], ["UniqueId", "col-uid"], ["Parameter", ""], ["Before", "col-before"], ["After", "col-after"], ["Tool", "col-tool"]]
        .filter(([name]) => (withUid || name !== "UniqueId") && (withElement || name !== "Element") && (withParameter || name !== "Parameter"));
      const table = reviewEl("table", "plan-preview-table");
      const headRow = reviewEl("tr");
      cols.forEach(([name, cls]) => headRow.append(reviewEl("th", cls, name)));
      headRow.className = "head-row";
      table.append(headRow);
      rows.slice(0, PREVIEW_ROW_CAP).forEach((row) => {
        let before = row.before;
        const fill = fills.get(`${row.element_id}|${row.parameter}`);
        if (before === "(not captured)" && fill !== undefined) {
          before = fill;
          filled += 1;
        }
        const values = {
          Element: row.element_id === null || row.element_id === undefined ? "unknown" : row.element_id,
          UniqueId: row.unique_id || "-",
          Parameter: row.parameter || "-",
          Before: before,
          After: row.after,
          Tool: row.tool
        };
        const tr = reviewEl("tr");
        cols.forEach(([name, cls]) => {
          const cell = values[name];
          const td = reviewEl("td", cls, visibleText(cell === undefined || cell === null ? "" : cell));
          td.dataset.label = name;
          tr.append(td);
        });
        table.append(tr);
      });
      root.append(table);
      if (filled > 0) root.append(reviewEl("p", "review-empty", `${filled} before value(s) come from the rolled-back preview.`));
      const total = Number.isSafeInteger(preview.row_count) ? preview.row_count : rows.length;
      if (total > PREVIEW_ROW_CAP) {
        root.append(reviewEl("p", "review-empty", `${total - PREVIEW_ROW_CAP} more row(s) not shown. To read all of them: ${cliShowCommand(planId)}`));
      }
    }
    return root;
  } catch (error) {
    return null;
  }
}

// The rolled-back preview (#293): what the add-in reported when it ran the plan in a transaction group
// that it always rolls back. It is part of the plan hash. Every cell is a text node run through
// visibleText. A missing or malformed record yields null. It never changes the Approve button: a preview
// is not an approval.
function buildRollbackPreviewBlock(record, namedIds) {
  try {
    if (!isPlainObject(record)) return null;
    const root = reviewEl("div", "plan-rollback-preview");
    const status = visibleText(record.status);
    if (record.rolled_back === false) {
      const alert = reviewEl("p", "plan-blast", "The preview was NOT rolled back. Check the model before approving anything.");
      alert.dataset.risk = "high";
      root.append(alert);
    }
    const ids = Array.isArray(record.changed_element_ids) ? record.changed_element_ids : [];
    const warnings = Array.isArray(record.warnings) ? record.warnings.filter(isPlainObject) : [];
    if (status === "unavailable") {
      root.append(reviewEl("p", "review-empty", `Rolled-back preview: not available. ${visibleText(record.reason || "")}`));
      return root;
    }
    let head = `Rolled-back preview (nothing was kept in the model): ${ids.length} element(s) would change, ${warnings.length} warning(s).`;
    if (status === "failed") head += ` A step failed in the preview: ${visibleText(record.reason || "no reason given")}.`;
    root.append(reviewEl("p", "plan-blast", head));
    if (ids.length > 0) {
      const shown = ids.slice(0, 20).map((id) => visibleText(id)).join(", ");
      root.append(reviewEl("p", "review-empty", `Changed element ids: ${shown}${ids.length > 20 ? ` and ${ids.length - 20} more` : ""}.`));
      const named = new Set(Array.from(namedIds || []).map((id) => String(id)));
      (Array.isArray(record.actions) ? record.actions : []).forEach((a) => {
        if (isPlainObject(a) && a.element_id !== undefined) named.add(String(a.element_id));
      });
      const extra = ids.filter((id) => !named.has(String(id)));
      if (extra.length > 0) {
        const listed = extra.slice(0, 20).map((id) => visibleText(id)).join(", ");
        root.append(reviewEl("p", "review-empty", `Also changed, not named in the plan: ${listed}${extra.length > 20 ? ` and ${extra.length - 20} more` : ""}.`));
      }
    }
    const actions = Array.isArray(record.actions) ? record.actions.filter(isPlainObject) : [];
    if (actions.length > 0) {
      const table = reviewEl("table", "plan-preview-table");
      const headRow = reviewEl("tr");
      ["Step", "Tool", "Result", "Element", "Parameter", "Before", "After"].forEach((h) => headRow.append(reviewEl("th", "", h)));
      table.append(headRow);
      actions.slice(0, PREVIEW_ROW_CAP).forEach((a) => {
        const tr = reviewEl("tr");
        [Number.isSafeInteger(a.index) ? a.index + 1 : "", a.tool, a.ok === true ? "ok" : (a.error || "failed"),
          a.element_id === undefined ? "-" : a.element_id, a.parameter || "-",
          a.before === undefined ? "(not captured)" : a.before, a.after === undefined ? "(not reported)" : a.after]
          .forEach((cell) => tr.append(reviewEl("td", "", visibleText(cell === undefined || cell === null ? "" : cell))));
        table.append(tr);
      });
      root.append(table);
    }
    warnings.slice(0, PREVIEW_ROW_CAP).forEach((w) => {
      const onIds = Array.isArray(w.element_ids) && w.element_ids.length > 0
        ? ` (elements: ${w.element_ids.slice(0, 20).map((id) => visibleText(id)).join(", ")})` : "";
      root.append(reviewEl("p", "review-empty", `Warning: ${visibleText(w.message || "")}${onIds}`));
    });
    return root;
  } catch (error) {
    return null;
  }
}

function mapPlans(hubResult) {
  const all = (hubResult && hubResult.plans) || [];
  const hubOmitted = Number.isSafeInteger(hubResult && hubResult.omitted) && hubResult.omitted > 0 ? hubResult.omitted : 0;
  state.plansOmitted = hubOmitted + Math.max(0, all.length - PLAN_LIMIT);
  // expired_hidden, expired and binding come from the hub and are shown only when present.
  state.expiredHidden = Number.isSafeInteger(hubResult && hubResult.expired_hidden) && hubResult.expired_hidden > 0 ? hubResult.expired_hidden : 0;
  return all.slice(0, PLAN_LIMIT).map((plan) => {
    const actions = plan.actions || [];
    const reviewState = planReviewState(plan);
    return {
      id: plan.plan_id,
      hash: plan.plan_hash || "",
      status: plan.state,
      expired: plan.expired === true,
      binding: isPlainObject(plan.binding) ? plan.binding : null,
      expiresAt: typeof plan.expires_at === "string" ? plan.expires_at : "",
      title: actions.length === 1 ? actions[0].tool : `${actions.length} action(s)`,
      detail: actions.map((action) => action.tool).join(", ") || "No actions",
      review: planActionLines(actions).join("\n") || "No actions",
      reviewState,
      preview: plan.preview,
      blastRadius: plan.blast_radius,
      rollbackPreview: plan.rollback_preview,
      reviewBlocked: !reviewState.ok,
      reviewPending: reviewState.ok && reviewState.version === 2 && !state.openedReviews.has(`${plan.plan_id}:${plan.plan_hash || ""}`),
      // Facts for the chat card, from the same real actions: tool, arguments, captured before value.
      actions: actions.map((action) => ({
        tool: action && action.tool,
        arguments: action && action.arguments,
        before: action && action.diff && action.diff.before
      }))
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

// Maps one entry from GET /reports (packages/mcp-server-revit's panel_server.py) -
// a plain workspace-directory listing, not an MCP tool result, since listing past
// exports has no tool of its own.
function mapReportEntry(entry) {
  return {
    id: entry.path,
    title: entry.name,
    detail: `Modified ${new Date(entry.modified * 1000).toLocaleString()}`
  };
}

if (window.chrome && window.chrome.webview) {
  window.chrome.webview.addEventListener("message", (event) => {
    if (event.data?.type === "host.status") {
      const hubWasOnline = isHubOnline();
      state.host = event.data;
      const scoped = state.plans.map((plan) => plan.id).join();
      applyPlanScope();
      if (state.plans.map((plan) => plan.id).join() !== scoped) {
        renderPlans();
        if (chat) chat.setProposals(state.plans);
      }
      if (state.host.serverRunning && !hubWasOnline) {
        requestDiagnostics();
      }
      document.documentElement.dataset.theme = event.data.isDarkTheme ? "dark" : "light";
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
    if (event.data?.type === "providers.updated") {
      state.providers = event.data.providers;
      applyProviderAvailability();
      renderSystemState();
    }
    if (event.data?.type === "findings.updated") {
      state.findings = mapFindings(event.data.result);
      renderFindings();
      addLog("Health check complete", `${state.findings.length} finding(s)`);
    }
    if (event.data?.type === "plans.updated") {
      state.allPlans = mapPlans(event.data.result);
      applyPlanScope();
      // The hub hides expired plans by default; keep asking for them while the toggle is on.
      if (state.showExpired && state.expiredHidden > 0) postToHost("plans.refresh", { includeExpired: true });
      const known = new Set(state.plans.map((plan) => plan.id));
      state.selectedPlanIds.forEach((id) => { if (!known.has(id)) state.selectedPlanIds.delete(id); });
      renderPlans();
      if (chat) {
        chat.setProposals(state.plans);
      }
      addLog("Plans updated", `${state.plans.filter(isPlanActionable).length} pending of ${state.plans.length}`);
    }
    if (event.data?.type === "reports.updated") {
      const report = mapReport(event.data.result);
      state.reports = [report, ...state.reports];
      renderReports();
      addLog("Report exported", report.title);
    }
    if (event.data?.type === "reports.list") {
      state.reports = (event.data.reports || []).map(mapReportEntry);
      renderReports();
      addLog("Reports refreshed", `${state.reports.length} report(s)`);
    }
    if (event.data?.type === "selection.result") {
      const result = event.data.result || {};
      const notFound = result.not_found_count || 0;
      const detail = notFound > 0
        ? `${result.selected_count || 0} selected, ${notFound} not found in the active document`
        : `${result.selected_count || 0} selected`;
      addLog("Selection updated", detail);
    }
    if (event.data?.type === "diagnostics.updated") {
      clearTimeout(diagnosticsRetry);
      diagnosticsRetry = null;
      if (!event.data.diagnostics || !Array.isArray(event.data.diagnostics.checks)
          || event.data.diagnostics.checks.some((check) => !check || typeof check !== "object")) {
        setHubUnreachable("The panel hub returned an invalid diagnostics response.");
        return;
      }
      state.diagnostics = event.data.diagnostics;
      renderMode();
      syncAutoControls();
      renderSetup();
      renderSystemState();
      addLog("Setup check", failingChecks().length ? `${failingChecks().length} step(s) need attention` : "Ready");
    }
    if (event.data?.type === "tool.error") {
      if (event.data.action === "diagnostics.refresh") {
        setHubUnreachable(event.data.message);
      }
      addLog(`Error: ${event.data.action || "tool"}`, friendlyError(event.data.message) || "Unknown error");
    }
    if (event.data?.type === "chat.response") {
      if (chat) {
        chat.onHostMessage({ type: "chat.response", message: event.data.message });
      }
      addLog("Chat response received", "");
      // The assistant may have drafted a plan: ask the host for the pending list so the
      // chat can show it as a proposal card (the panel never calls the hub itself).
      postToHost("plans.refresh");
    }
    if (event.data?.type === "chat.error") {
      const chatMessage = friendlyError(event.data.message) || "Unknown error";
      if (chat) {
        chat.onHostMessage({ type: "chat.error", message: chatMessage });
      }
      addLog("Chat error", chatMessage);
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

renderMode();
syncAutoControls();
renderPlans();
renderFindings();
renderReports();
renderLog();
renderSystemState();
renderSetup();
postToHost("panel.loaded");
requestDiagnostics();
postToHost("providers.refresh");

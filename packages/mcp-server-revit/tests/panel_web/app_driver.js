/* Behaviour tests for the REAL panel page (index.html + app.js + chat.js) with a stubbed host.
 * Run by tests/test_panel_chat_browser.py in headless Chromium. */
(function () {
  "use strict";
  const $ = (id) => document.getElementById(id);
  const deliver = (d) => window.__deliver(d);
  const sent = () => window.__sent;
  const sentOf = (type) => window.__sent.filter((m) => m.type === type);
  const feed = () => document.querySelector("#chat-root .feed");

  function host(extra) {
    deliver(Object.assign({ type: "host.status", serverRunning: true, activeDocument: "m.rvt", activeDocumentGuid: "g1", revitPid: 7, revitVersion: "2025", port: 1 }, extra));
  }
  function diag(mode) {
    deliver({ type: "diagnostics.updated", diagnostics: { ok: true, approval_mode: mode, checks: [] } });
  }
  function plans(list) { deliver({ type: "plans.updated", result: { plans: list } }); }
  function type(text) {
    const i = $("chat-input");
    i.value = text;
    i.dispatchEvent(new Event("input", { bubbles: true }));
    return i;
  }
  function key(input, init) {
    const ev = new KeyboardEvent("keydown", Object.assign({ bubbles: true, cancelable: true }, init));
    input.dispatchEvent(ev);
    return ev;
  }
  function fresh() {
    document.querySelector('.nav[data-view="chat"]').click();
    host();
    diag("ask_first");
    plans([]);
    $("chat-reset").click();
    sent().length = 0;
    window.__copied.length = 0;
  }
  const SESSION = { doc_guid: "g1", revit_pid: 7 };
  const PLAN = (id, actions, state) => ({ plan_id: id, plan_hash: "abcdef0123456789", state: state || "pending", actions, binding: SESSION });
  const SET = (ids, withBefore) => ({
    tool: "revit_set_parameter",
    arguments: { element_ids: ids, name: "Fire Rating", value: "2h" },
    diff: withBefore ? { before: { value: "60" } } : undefined,
  });

  function fact(card, key) {
    const dt = Array.from(card.querySelectorAll(".facts dt")).find((n) => n.textContent === key);
    return dt ? dt.nextElementSibling.textContent : null;
  }

  test("csp: meta present, vendor + chat scripts ran, no violation", () => {
    const meta = document.querySelector('meta[http-equiv="Content-Security-Policy"]');
    expect(meta && /script-src 'self'/.test(meta.content), "CSP meta missing");
    expect(window.AMBChat && window.smd && window.hljs, "scripts did not run under the CSP");
    expect(window.__csp.length === 0, "CSP violations: " + window.__csp.join(" | "));
    expect(!(window.__pageErrors || []).length, "page errors: " + (window.__pageErrors || []).join(" | "));
  });

  test("empty state: 3 BIM example prompts; a card fills the composer", () => {
    fresh();
    const cards = document.querySelectorAll(".prompt-card");
    expect(cards.length === 3, "expected 3 prompts, got " + cards.length);
    cards[0].click();
    expect(/model health/i.test($("chat-input").value), "prompt did not fill the composer");
    expect(!document.querySelector(".send-btn").disabled, "send should enable");
  });

  test("Enter sends chat.message {message, provider} and shows a Thinking placeholder", () => {
    fresh();
    const i = type("How many doors?");
    key(i, { key: "Enter" });
    const m = sentOf("chat.message");
    expect(m.length === 1, "expected one chat.message");
    expect(m[0].message === "How many doors?" && m[0].provider === "claude", "payload " + JSON.stringify(m[0]));
    expect(Object.keys(m[0]).sort().join() === "message,provider,type", "unexpected payload keys " + Object.keys(m[0]));
    expect(i.value === "", "composer not cleared");
    expect(document.querySelector(".msg.assistant.pending .pending-text").textContent.indexOf("Thinking") === 0, "no thinking placeholder");
    expect(document.querySelectorAll(".prompt-card").length === 0, "empty state should be gone");
  });

  test("Shift+Enter and IME composition Enter do not send", () => {
    fresh();
    const i = type("line one");
    const shift = key(i, { key: "Enter", shiftKey: true });
    expect(!shift.defaultPrevented, "Shift+Enter must stay a newline");
    key(i, { key: "Enter", isComposing: true });
    key(i, { key: "Enter", keyCode: 229 });
    expect(sentOf("chat.message").length === 0, "sent while composing / Shift+Enter");
    expect(i.value === "line one", "composer changed");
  });

  test("composer auto-grows with lines and shrinks when cleared", () => {
    fresh();
    const i = type("a");
    const h0 = parseFloat(i.style.height);
    type("a\nb\nc\nd\ne");
    const h1 = parseFloat(i.style.height);
    expect(h1 > h0 + 20, "did not grow: " + h0 + " -> " + h1);
    type("");
    expect(parseFloat(i.style.height) <= h0 + 2, "did not shrink");
  });

  test("chat.response replaces the placeholder with rendered markdown", () => {
    fresh();
    key(type("summary"), { key: "Enter" });
    deliver({ type: "chat.response", message: "## Health\n\n| a | b |\n|---|---|\n| 1 | 2 |\n\n- one\n- two\n\n```python\nprint(1)\n```\n\n`inline`" });
    const msg = document.querySelector(".msg.assistant");
    expect(!msg.classList.contains("pending") && !msg.querySelector(".pending-text"), "placeholder still there");
    expect(document.querySelectorAll(".msg.assistant").length === 1, "response should reuse the pending message");
    expect(msg.querySelector("h2") && msg.querySelector("h2").textContent === "Health", "heading");
    expect(msg.querySelector(".table-wrap table th"), "table");
    expect(msg.querySelectorAll("ul li").length === 2, "list");
    expect(msg.querySelector(".codeblock .copy-btn"), "code block copy button");
    expect(msg.querySelector(".codeblock .hljs-built_in, .codeblock .hljs-keyword, .codeblock span[class^=hljs]"), "syntax highlighting");
    expect(msg.querySelector("p code").textContent === "inline", "inline code");
    expect(msg.querySelector(".msg-actions .act-btn"), "copy message button");
  });

  test("queued sends are answered in order", () => {
    fresh();
    key(type("first"), { key: "Enter" });
    key(type("second"), { key: "Enter" });
    deliver({ type: "chat.response", message: "answer one" });
    deliver({ type: "chat.response", message: "answer two" });
    const texts = Array.from(document.querySelectorAll(".msg.assistant .md")).map((n) => n.textContent);
    expect(texts.join("|") === "answer one|answer two", "order " + texts.join("|"));
  });

  test("chat.error shows 'Error:' with the hub's next step, markup stays text", () => {
    fresh();
    key(type("x"), { key: "Enter" });
    deliver({ type: "chat.error", message: "bad <b>bold</b><img src=x onerror=window.__x=1>" });
    const e = document.querySelector(".msg.assistant.error .error-text");
    expect(e && e.textContent === "Error: bad <b>bold</b><img src=x onerror=window.__x=1>", "error text " + (e && e.textContent));
    expect(!e.querySelector("b, img") && window.__x === undefined, "markup was parsed");
  });

  test("a hub-down transport error is replaced by the failing check's next step", () => {
    fresh();
    deliver({ type: "diagnostics.updated", diagnostics: { ok: false, approval_mode: "ask_first", checks: [{ id: "hub", ok: false, detail: "d", next_step: "Start the server." }] } });
    deliver({ type: "chat.error", message: "Could not reach the AEC Model Bridge hub." });
    expect(document.querySelector(".error-text").textContent === "Error: Start the server.", "friendlyError lost");
  });

  test("hub transport errors preserve their cause when another setup check failed", () => {
    fresh();
    deliver({ type: "diagnostics.updated", diagnostics: { checks: [{ id: "workspace", ok: false, next_step: "Fix the folder." }] } });
    deliver({ type: "chat.error", message: "Could not reach the AEC Model Bridge hub." });
    expect(document.querySelector(".error-text").textContent === "Error: Could not reach the AEC Model Bridge hub.", "unrelated check hid the hub failure");
  });

  test("failed setup retries the panel hub independently of the Revit bridge", () => {
    fresh();
    let retry = null;
    const original = window.setTimeout;
    window.setTimeout = (callback, delay) => {
      if (delay === 5000) { retry = callback; return 0; }
      return original(callback, delay);
    };
    try {
      deliver({ type: "tool.error", action: "diagnostics.refresh", message: "Hub is starting" });
    } finally { window.setTimeout = original; }
    expect(retry && /aec-model-bridge-panel-server/.test($("setup-list").textContent), "missing retry or wrong recovery");
    sent().length = 0;
    retry();
    expect(sentOf("diagnostics.refresh").length === 1, "hub readiness was not retried");
    diag("ask_first");
    expect($("setup-check").dataset.state === "ready", "setup did not recover");
  });

  test("malformed diagnostics show a recoverable setup failure", () => {
    fresh();
    deliver({ type: "diagnostics.updated", diagnostics: { checks: {} } });
    expect($("setup-check").dataset.state === "blocked" && /invalid diagnostics/.test($("setup-list").textContent), "bad diagnostics crashed or passed");
    diag("ask_first");
  });

  test("model text is never parsed as HTML (user bubble, response, hostile markdown)", () => {
    fresh();
    const evil = '<img src=x onerror="window.__pwn=1"><script>window.__pwn=2</script>';
    key(type(evil), { key: "Enter" });
    deliver({ type: "chat.response", message: evil + "\n\n[x](javascript:window.__pwn=3)\n\n![t](https://evil.example/p.png)" });
    const root = $("chat-root");
    expect(!root.querySelector("script, img, iframe, object, embed"), "dangerous element in chat");
    expect(root.querySelector(".bubble").textContent === evil, "user bubble not plain text");
    const a = Array.from(root.querySelectorAll(".md a"));
    expect(a.every((x) => !x.hasAttribute("href")), "javascript: link kept an href");
    expect(window.__pwn === undefined, "script executed");
    expect(root.querySelector(".md-image"), "image should be a blocked placeholder");
  });

  test("control and bidi characters are shown as escapes in bubble and response", () => {
    fresh();
    key(type("a‮b\u0007"), { key: "Enter" });
    deliver({ type: "chat.response", message: "x‮y​z" });
    expect(document.querySelector(".bubble").textContent === "a\\u202eb\\x07", "bubble " + document.querySelector(".bubble").textContent);
    expect(document.querySelector(".msg.assistant .md").textContent === "x\\u202ey\\u200bz", "response");
  });

  test("oversized message is cut with a notice and copy still gives the full text", async () => {
    fresh();
    key(type("big"), { key: "Enter" });
    const big = "word ".repeat(60000); // 300 KB
    deliver({ type: "chat.response", message: big });
    const md = document.querySelector(".msg.assistant .md");
    expect(md.textContent.length <= window.AMBChat.MAX_MESSAGE_CHARS, "not truncated: " + md.textContent.length);
    expect(/shortened for display/.test(document.querySelector(".truncated-note").textContent), "no notice");
    document.querySelector(".msg-actions .act-btn").click();
    await sleep(50);
    expect(window.__copied[0] === big, "copy should give the full text");
  });

  test("copy message and copy code use the clipboard", async () => {
    fresh();
    key(type("q"), { key: "Enter" });
    deliver({ type: "chat.response", message: "hello **world**\n\n```js\nvar a = 1;\n```" });
    document.querySelector(".codeblock .copy-btn").click();
    await sleep(50);
    expect(window.__copied[0] === "var a = 1;\n" || window.__copied[0] === "var a = 1;", "code copy " + JSON.stringify(window.__copied[0]));
    document.querySelector(".msg-actions .act-btn").click();
    await sleep(50);
    expect(/hello \*\*world\*\*/.test(window.__copied[1]), "message copy gives markdown source");
  });

  test("links: click posts link.open, shows the URL as copyable text, never navigates", async () => {
    fresh();
    key(type("q"), { key: "Enter" });
    deliver({ type: "chat.response", message: "see [BEP](https://example.com/bep) and [bad](javascript:alert(1))" });
    const a = document.querySelector(".md a[href]");
    const ev = new MouseEvent("click", { bubbles: true, cancelable: true });
    a.dispatchEvent(ev);
    expect(ev.defaultPrevented, "click was not intercepted");
    const m = sentOf("link.open");
    expect(m.length === 1 && m[0].url === "https://example.com/bep", "link.open " + JSON.stringify(m));
    const note = document.querySelector(".link-note");
    expect(!note.hidden && note.querySelector(".link-note-url").textContent === "https://example.com/bep", "URL not shown");
    note.querySelector(".act-btn").click();
    await sleep(50);
    expect(window.__copied[0] === "https://example.com/bep", "link copy");
    const bad = Array.from(document.querySelectorAll(".md a")).find((x) => x.textContent === "bad");
    expect(bad && !bad.hasAttribute("href") && bad.classList.contains("link-blocked"), "bad link not blocked");
  });

  test("New conversation posts chat.reset and restores the empty state", () => {
    fresh();
    key(type("q"), { key: "Enter" });
    deliver({ type: "chat.response", message: "a" });
    sent().length = 0;
    $("chat-reset").click();
    expect(sentOf("chat.reset").length === 1, "chat.reset not posted");
    expect(document.querySelectorAll(".prompt-card").length === 3 && !document.querySelector(".msg"), "empty state not restored");
  });

  test("chat is disabled while the hub is down", () => {
    fresh();
    host({ serverRunning: false });
    expect($("chat-input").disabled && document.querySelector(".send-btn").disabled, "composer should be disabled");
    host();
    expect(!$("chat-input").disabled, "composer should come back");
  });

  test("a chat.response asks the host for the pending plans (cards come from plans.updated)", () => {
    fresh();
    key(type("q"), { key: "Enter" });
    sent().length = 0;
    deliver({ type: "chat.response", message: "drafted a plan" });
    expect(sentOf("plans.refresh").length === 1, "plans.refresh not requested");
  });

  test("mode chip reads approval_mode from diagnostics (look_only, ask_first, auto, unknown)", () => {
    fresh();
    const chip = $("mode-chip");
    diag("look_only");
    expect(chip.dataset.mode === "look_only" && chip.textContent === "Look only", "look_only: " + chip.textContent);
    diag("ask_first");
    expect(chip.dataset.mode === "ask_first" && chip.textContent === "Ask me first", "ask_first: " + chip.textContent);
    diag("auto");
    expect(chip.dataset.mode === "auto" && /Auto/.test(chip.textContent) && /not recommended/i.test(chip.textContent), "auto: " + chip.textContent);
    deliver({ type: "diagnostics.updated", diagnostics: { ok: false, checks: [] } });
    expect(chip.dataset.mode === "unknown" && chip.textContent === "Mode unknown", "unknown: " + chip.textContent);
    diag("surprise");
    expect(chip.dataset.mode === "unknown", "unrecognised mode must not look known");
  });

  test("chip is informational: not a button, mentions settings, sends nothing", () => {
    fresh();
    diag("look_only");
    const chip = $("mode-chip");
    expect(chip.tagName === "SPAN", "chip must not be a control");
    expect(/Change in settings/.test(chip.title), "title should say Change in settings");
    chip.click();
    expect(sent().length === 0, "chip click must not post anything");
  });

  test("Look only banner shows only in look_only (warning style in auto)", () => {
    fresh();
    const banner = () => document.querySelector(".mode-banner");
    diag("look_only");
    expect(!banner().hidden && /Look only/.test(banner().textContent), "banner missing in look_only");
    diag("ask_first");
    expect(banner().hidden, "banner should hide in ask_first");
    diag("auto");
    expect(!banner().hidden && banner().classList.contains("is-warning"), "auto warning missing");
  });

  test("proposal card: facts from the real actions, Review button, no Approve in chat", () => {
    fresh();
    plans([PLAN("p1", [SET([1, 2], true), SET([2, 3], false), { tool: "revit_delete_element", arguments: { element_id: 9 } }])]);
    const card = document.querySelector(".proposal");
    expect(card, "no proposal card");
    expect(/3 proposed changes/.test(card.querySelector(".proposal-title").textContent), "count");
    expect(fact(card, "Tools") === "revit_set_parameter ×2, revit_delete_element", "tools: " + fact(card, "Tools"));
    expect(fact(card, "Scope") === "4 elements", "scope: " + fact(card, "Scope"));
    expect(fact(card, "Before values") === "Captured for 1 of 3", "before: " + fact(card, "Before values"));
    expect(/Ctrl\+Z in Revit, once per step/.test(card.textContent) && /not built yet/.test(card.textContent), "honest undo wording");
    const btn = card.querySelector("button.review-btn");
    expect(btn.textContent === "Review 3 changes", "button: " + btn.textContent);
    expect(!card.querySelector('[data-decision], [data-plan]') && !/approve/i.test(Array.from(card.querySelectorAll("button")).map((b) => b.textContent).join(" ")), "chat card must not offer Approve");
  });

  test("proposal card says so when before values or scope are not available", () => {
    fresh();
    plans([PLAN("p2", [{ tool: "revit_set_parameter", arguments: { name: "x" } }])]);
    const card = document.querySelector(".proposal");
    expect(fact(card, "Scope") === "Not stated in the actions", "scope: " + fact(card, "Scope"));
    expect(/^Not captured/.test(fact(card, "Before values")), "before: " + fact(card, "Before values"));
    expect(/1 proposed change(?!s)/.test(document.querySelector(".proposal-title").textContent), "singular");
  });

  test("proposal card escapes hostile tool names and arguments", () => {
    fresh();
    const evil = '<img src=x onerror="window.__pwn2=1">‮';
    plans([PLAN("p3", [{ tool: evil, arguments: { [evil]: evil } }])]);
    const card = document.querySelector(".proposal");
    expect(!card.querySelector("img, script"), "element created from model text");
    expect(card.textContent.indexOf("‮") === -1 && /\\u202e/.test(card.textContent), "bidi char not escaped");
    expect(window.__pwn2 === undefined, "executed");
  });

  test("Review N changes switches to the Plans view, which keeps Approve/Reject", () => {
    fresh();
    plans([PLAN("p4", [SET([1], true)])]);
    document.querySelector(".review-btn").click();
    expect($("view-plans").classList.contains("is-active") && !$("view-chat").classList.contains("is-active"), "view did not switch");
    expect(document.querySelector('.nav[data-view="plans"]').getAttribute("aria-current") === "page", "nav state");
    const plan = document.querySelector('#plan-list [data-plan="p4"][data-decision="approve"]');
    expect(plan && document.querySelector('#plan-list [data-plan="p4"][data-decision="reject"]'), "Plans Approve/Reject missing");
    expect(document.activeElement && document.activeElement.dataset.planId === "p4", "focus should land on the plan");
    expect(sentOf("plan.approve").length === 0, "review must not approve");
  });

  test("Plans view Approve still posts plan.approve with the hash", () => {
    fresh();
    plans([PLAN("p5", [SET([1], true)])]);
    sent().length = 0;
    const b = document.querySelector('#plan-list [data-plan="p5"][data-decision="approve"]');
    b.click();
    const m = sentOf("plan.approve");
    expect(m.length === 1 && m[0].planId === "p5" && m[0].planHash === "abcdef0123456789", "payload " + JSON.stringify(m));
  });

  test("Look only: the card explains approval is unavailable; ask_first does not", () => {
    fresh();
    plans([PLAN("p6", [SET([1], true)])]);
    diag("look_only");
    const lock = document.querySelector(".proposal-lock");
    expect(!lock.hidden && /cannot be approved/.test(lock.textContent), "explanation missing in look_only");
    expect(document.querySelector(".proposal").classList.contains("is-locked"), "card not marked locked");
    const btn = document.querySelector(".review-btn");
    expect(btn.getAttribute("aria-describedby") === lock.id, "explanation not linked to the button");
    diag("ask_first");
    expect(lock.hidden && !btn.hasAttribute("aria-describedby"), "explanation should clear in ask_first");
    diag("auto");
    expect(!lock.hidden && /skipped/.test(lock.textContent), "auto warning missing");
  });

  test("a plan that leaves the pending list is marked No longer pending; same plan is not duplicated", () => {
    fresh();
    plans([PLAN("p7", [SET([1], true)])]);
    plans([PLAN("p7", [SET([1], true)])]);
    expect(document.querySelectorAll(".proposal").length === 1, "duplicate card");
    plans([]);
    const card = document.querySelector(".proposal");
    expect(/No longer pending/.test(card.querySelector(".badge").textContent), "badge");
    expect(!card.querySelector(".review-btn"), "review button should go");
  });

  test("settled plans in the list never get a new chat card", () => {
    fresh();
    plans([PLAN("p8", [SET([1], true)], "executed")]);
    expect(document.querySelectorAll(".proposal").length === 0, "card for a settled plan");
  });

  test("Jump to latest pill appears when scrolled up and returns to the bottom", async () => {
    fresh();
    for (let n = 0; n < 25; n++) {
      key(type("message " + n + " with some words to take space"), { key: "Enter" });
      deliver({ type: "chat.response", message: "reply " + n + "\n\nmore text\n\nand more text" });
    }
    const f = feed();
    expect(f.scrollHeight > f.clientHeight + 100, "feed does not overflow: " + f.scrollHeight + "/" + f.clientHeight);
    f.scrollTop = 0;
    f.dispatchEvent(new Event("scroll"));
    const pill = document.querySelector(".jump-pill");
    expect(!pill.hidden, "pill should show when scrolled up");
    deliver({ type: "chat.response", message: "late answer" });
    expect(f.scrollTop === 0, "must not yank the reader to the bottom");
    expect(/New content below/.test(pill.textContent), "label " + pill.textContent);
    // Smooth scrolling needs real frames; honour reduced motion so the jump is immediate here.
    const realMatchMedia = window.matchMedia;
    window.matchMedia = (q) => (/reduced-motion/.test(q) ? { matches: true } : realMatchMedia.call(window, q));
    pill.click();
    await sleep(100);
    window.matchMedia = realMatchMedia;
    expect(f.scrollHeight - f.scrollTop - f.clientHeight < 60, "pill did not return to the bottom");
  });

  // ---- plan review block (hash_version 2) ------------------------------------------------
  const REVIEW = () => ({
    summary: "Raise fire rating to 60",
    reasoning: "Corridor walls need 60 min.",
    citations: [{ rule_id: "FIRE-001", clause: "B3.2", source: "Approved Document B" }],
    assumptions: ["Walls are load bearing"],
    excluded: [{ element_id: 9, reason: "linked model" }],
    warnings: ["Check with the fire engineer"],
    conflicts: [{ element_id: 1, parameter: "FireRating", expected_current: "60", actual_current: "90", revert_to: "30" }],
  });
  const V2 = (id, review, extra) => Object.assign({
    plan_id: id, plan_hash: "abcdef0123456789", state: "pending", hash_version: 2, binding: SESSION,
    actions: [SET([1], true)],
    review_view: { status: "ok", hash_version: 2, reverts_plan_id: null, review, error: "" },
  }, extra || {});
  // Deliver plans, then open every review that offers to be opened (Approve waits for it).
  function plansOpen(list) {
    plans(list);
    document.querySelectorAll("[data-open-review]").forEach((b) => b.click());
  }
  const cardOf = (id) => Array.from($("plan-list").children).find((c) => c.dataset.planId === id);
  const approveBtn = (card) => card.querySelector('[data-decision="approve"]');
  const FORBIDDEN = "script,img,iframe,object,embed,style,link,meta,base,form,svg,math,video,audio,a,textarea";
  const XSS = '<script>window.__pwned=1</script><img src=x onerror="window.__pwned=2"><a href="javascript:window.__pwned=3">x</a><svg onload="window.__pwned=4"></svg>';

  test("review: a v2 plan shows every hashed review field and says what the hash covers", () => {
    fresh();
    plansOpen([V2("r1", REVIEW())]);
    const card = cardOf("r1");
    const block = card.querySelector(".plan-review-block");
    expect(block && block.dataset.reviewKind === "v2", "review block missing");
    const t = block.textContent;
    for (const needle of ["Raise fire rating to 60", "Corridor walls need 60 min.", "FIRE-001", "B3.2", "Approved Document B",
      "Walls are load bearing", "linked model", "Check with the fire engineer", "FireRating", "Revert to"]) {
      expect(t.includes(needle), "missing in review: " + needle);
    }
    expect(/Covered by the approval hash/.test(t), "hash coverage not stated");
    for (const h of ["Summary", "Reasoning", "Citations", "Assumptions", "Excluded elements", "Warnings", "Conflicts"]) {
      expect(Array.from(block.querySelectorAll("h3")).some((n) => n.textContent.startsWith(h)), "section " + h);
    }
    expect(!approveBtn(card).disabled, "Approve should be on for a shown review");
  });

  test("review: reverts_plan_id is shown when present", () => {
    fresh();
    const p = V2("r2", REVIEW());
    p.review_view.reverts_plan_id = "plan_0123456789ab";
    plansOpen([p]);
    expect(/Reverts plan: plan_0123456789ab/.test(cardOf("r2").textContent), "reverted plan id not shown");
  });

  test("review: script and markup in every field stay inert text", () => {
    fresh();
    const r = {
      summary: XSS, reasoning: XSS,
      citations: [{ rule_id: XSS, clause: XSS, source: XSS }],
      assumptions: [XSS], excluded: [{ element_id: XSS, reason: XSS }], warnings: [XSS],
      conflicts: [{ element_id: XSS, parameter: XSS, expected_current: XSS, actual_current: XSS, revert_to: XSS }],
    };
    plansOpen([V2("x1", r)]);
    const block = cardOf("x1").querySelector(".plan-review-block");
    expect(block, "review block missing");
    expect(block.querySelectorAll(FORBIDDEN).length === 0, "active element inside the review");
    block.querySelectorAll("*").forEach((n) => {
      Array.from(n.attributes).forEach((a) => expect(!/^on/i.test(a.name) && a.name !== "href" && a.name !== "src", "attribute " + a.name));
    });
    expect(block.textContent.includes("<script>window.__pwned=1</script>"), "markup should appear as literal text");
    expect(window.__pwned === undefined, "script ran");
    expect(window.__csp.length === 0, "CSP violations: " + window.__csp.join(" | "));
    expect(!sent().some((m) => m.type === "link.open"), "a link was opened");
  });

  // ---- preview table and blast radius ---------------------------------------------------
  const ROW = (n, over) => Object.assign({ action_id: "a" + n, tool: "revit_set_parameter_value", element_id: String(n),
    unique_id: null, parameter: "Mark", before: "(empty)", after: "A" + n }, over || {});
  const RADIUS = { element_count: 2, action_count: 2, unidentified_actions: 0, categories: ["Walls", "unknown"],
    levels: ["unknown"], worksets: ["unknown"], risk: "medium" };

  test("preview: table shows before/after rows and the blast radius", () => {
    fresh();
    plans([V2("pv1", null, { review_view: { status: "none", hash_version: 1, reverts_plan_id: null, review: null, error: "" },
      hash_version: undefined, preview: { rows: [ROW(1), ROW(2, { before: "old" })], row_count: 2, rows_omitted: 0 }, blast_radius: RADIUS })]);
    const card = cardOf("pv1");
    const cells = Array.from(card.querySelectorAll(".plan-preview-table tr")).map((tr) => Array.from(tr.children).map((c) => c.textContent));
    expect(cells.length === 3 && cells[0][2] === "Before" && cells[1][2] === "(empty)" && cells[2][2] === "old" && cells[2][3] === "A2", "rows " + JSON.stringify(cells));
    expect(!cells[0].includes("UniqueId") && !/unknown/.test(JSON.stringify(cells)), "a UniqueId nobody knows must not be printed as unknown");
    const head = card.querySelector(".plan-blast");
    expect(head && /Risk: medium/.test(head.textContent) && /Categories: Walls \(not all known\)/.test(head.textContent), "blast radius header missing");
    expect(!/Levels|Worksets|unknown/.test(head.textContent), "unknown fields must be left out: " + head.textContent);
    expect(!!approveBtn(card) && !approveBtn(card).disabled, "preview must not change Approve state");
  });

  test("preview: a known UniqueId gets its column, and a before value comes from the rolled-back preview when the plan did not capture it", () => {
    fresh();
    const rb = { version: 1, status: "ok", rolled_back: true, changed_element_ids: [1, 2, 77],
      actions: [{ index: 0, tool: "revit_set_parameter_value", ok: true, element_id: 1, parameter: "Mark", before: "OLD1", after: "A1" }],
      warnings: [{ action_index: 0, severity: "Warning", message: "Duplicate Mark.", element_ids: [1, 2] }] };
    plans([V2("pv5", null, Object.assign({ rollback_preview: rb }, { review_view: { status: "none", hash_version: 1, reverts_plan_id: null, review: null, error: "" }, hash_version: undefined,
      preview: { rows: [ROW(1, { unique_id: "uid-1", before: "(not captured)" }), ROW(2, { before: "(not captured)" })], row_count: 2, rows_omitted: 0 }, blast_radius: RADIUS }))]);
    const card = cardOf("pv5");
    const cells = Array.from(card.querySelectorAll(".plan-preview-table tr")).map((tr) => Array.from(tr.children).map((c) => c.textContent));
    expect(cells[0].includes("UniqueId") && cells[1][1] === "uid-1", "UniqueId column " + JSON.stringify(cells[1]));
    expect(cells[1][3] === "OLD1" && cells[2][3] === "(not captured)", "before fill " + JSON.stringify(cells));
    expect(/1 before value\(s\) come from the rolled-back preview/.test(card.querySelector(".plan-preview").textContent), "fill not disclosed");
    const rbText = card.querySelector(".plan-rollback-preview").textContent;
    expect(/Also changed, not named in the plan: 77\./.test(rbText), "extra changed ids missing: " + rbText);
    expect(/Duplicate Mark\. \(elements: 1, 2\)/.test(rbText), "warning elements missing: " + rbText);
    expect(card.querySelector(".plan-details").contains(card.querySelector(".plan-rollback-preview")), "rolled-back preview belongs in the details");
  });

  test("preview: rows are capped at 25 and the rest is counted", () => {
    fresh();
    const rows = Array.from({ length: 30 }, (_, i) => ROW(i + 1));
    plans([V2("pv2", null, { review_view: { status: "none", hash_version: 1, reverts_plan_id: null, review: null, error: "" },
      hash_version: undefined, preview: { rows, row_count: 30, rows_omitted: 0 }, blast_radius: RADIUS })]);
    const card = cardOf("pv2");
    expect(card.querySelectorAll(".plan-preview-table tr").length === 26, "expected header + 25 rows");
    expect(/5 more row\(s\) not shown/.test(card.querySelector(".plan-preview").textContent), "omitted count missing");
  });

  test("preview: hostile cell text stays inert", () => {
    fresh();
    plans([V2("pv3", null, { review_view: { status: "none", hash_version: 1, reverts_plan_id: null, review: null, error: "" },
      hash_version: undefined, preview: { rows: [ROW(1, { after: XSS, parameter: XSS, tool: XSS, before: "x\u202Ey" })], row_count: 1, rows_omitted: 0 },
      blast_radius: Object.assign({}, RADIUS, { categories: [XSS], risk: XSS }) })]);
    const card = cardOf("pv3");
    expect(card.querySelectorAll(FORBIDDEN).length === 0, "active element in card");
    expect(card.querySelector(".plan-preview").textContent.includes("<script>window.__pwned=1</script>"), "markup should be literal text");
    expect(!card.querySelector(".plan-preview").textContent.includes("\u202E"), "bidi override shown raw");
    expect(window.__pwned === undefined, "script ran");
  });

  const ROLLED = (over) => Object.assign({ version: 1, status: "ok", rolled_back: true, changed_element_ids: [11, 12],
    actions: [{ index: 0, tool: "revit_set_parameter_value", ok: true, element_id: 11, parameter: "Mark", before: "A", after: "B" }],
    warnings: [{ action_index: 0, severity: "Warning", message: "Elements have duplicate Mark values.", element_ids: [11] }] }, over || {});
  const NO_REVIEW = { review_view: { status: "none", hash_version: 1, reverts_plan_id: null, review: null, error: "" }, hash_version: undefined };

  test("rollback preview: shows changed ids, before and after and the warnings, and leaves Approve alone", () => {
    fresh();
    plans([V2("rp1", null, Object.assign({ rollback_preview: ROLLED() }, NO_REVIEW))]);
    const card = cardOf("rp1");
    const block = card.querySelector(".plan-rollback-preview");
    expect(!!block, "rolled-back preview block missing");
    expect(/nothing was kept in the model/.test(block.textContent) && /Changed element ids: 11, 12/.test(block.textContent), "head " + block.textContent);
    const cells = Array.from(block.querySelectorAll("tr")).map((tr) => Array.from(tr.children).map((c) => c.textContent));
    expect(cells[1][5] === "A" && cells[1][6] === "B", "before/after " + JSON.stringify(cells));
    expect(/Elements have duplicate Mark values/.test(block.textContent), "warning missing");
    expect(!!approveBtn(card) && !approveBtn(card).disabled, "a preview must not change Approve state");
  });

  test("rollback preview: an unavailable preview says so, and a preview that was not rolled back is flagged", () => {
    fresh();
    plans([V2("rp2", null, Object.assign({ rollback_preview: ROLLED({ status: "unavailable", reason: "Revit was busy.", actions: [], changed_element_ids: [], warnings: [] }) }, NO_REVIEW)),
           V2("rp3", null, Object.assign({ rollback_preview: ROLLED({ rolled_back: false }) }, NO_REVIEW))]);
    expect(/not available\. Revit was busy\./.test(cardOf("rp2").querySelector(".plan-rollback-preview").textContent), "unavailable text");
    expect(/NOT rolled back/.test(cardOf("rp3").querySelector(".plan-rollback-preview").textContent), "not-rolled-back alert");
  });

  test("rollback preview: hostile text stays inert", () => {
    fresh();
    plans([V2("rp4", null, Object.assign({ rollback_preview: ROLLED({ warnings: [{ action_index: 0, severity: "Warning", message: XSS, element_ids: [] }],
      actions: [{ index: 0, tool: XSS, ok: false, error: XSS, before: "x‮y" }] }) }, NO_REVIEW))]);
    const card = cardOf("rp4");
    expect(card.querySelectorAll(FORBIDDEN).length === 0, "active element in card");
    expect(card.querySelector(".plan-rollback-preview").textContent.includes("<script>window.__pwned=1</script>"), "markup should be literal text");
    expect(!card.querySelector(".plan-rollback-preview").textContent.includes("‮"), "bidi override shown raw");
    expect(window.__pwned === undefined, "script ran");
  });

  test("preview: a plan without preview data still renders", () => {
    fresh();
    plans([PLAN("pv4", [SET([1], true)])]);
    expect(!!cardOf("pv4") && !cardOf("pv4").querySelector(".plan-preview"), "card should render with no preview block");
  });

  test("review: hostile text in the reverts id stays inert", () => {
    fresh();
    const p = V2("x2", REVIEW());
    p.review_view.reverts_plan_id = XSS;
    plansOpen([p]);
    expect(approveBtn(cardOf("x2")).disabled, "a reverts id that is not a plan id must block Approve");
    expect(cardOf("x2").querySelectorAll(FORBIDDEN).length === 0, "active element in card");
    expect(window.__pwned === undefined, "script ran");
  });

  test("review: control and bidi characters are shown as escapes", () => {
    fresh();
    const r = REVIEW();
    r.summary = "pay‮exe​now\u001b[31m";
    plansOpen([V2("c1", r)]);
    const t = cardOf("c1").querySelector(".plan-review-block").textContent;
    expect(!/[‮​\u001b]/.test(t), "raw control/bidi char reached the page");
    expect(t.includes("\\u202e") && t.includes("\\x1b"), "escapes not shown");
  });

  test("review: long text is clipped with Show more that reveals all of it", () => {
    fresh();
    const r = REVIEW();
    r.reasoning = "A".repeat(3000) + "END";
    plansOpen([V2("l1", r)]);
    const block = cardOf("l1").querySelector(".plan-review-block");
    const btn = block.querySelector(".review-more");
    expect(btn && /^Show more \(\d+ more characters\)$/.test(btn.textContent), "no Show more button");
    expect(!block.textContent.includes("END"), "text was not clipped");
    btn.click();
    expect(block.textContent.includes("A".repeat(3000) + "END"), "full text not revealed");
    expect(btn.textContent === "Show less" && btn.getAttribute("aria-expanded") === "true", "button state");
    btn.click();
    expect(!block.textContent.includes("END"), "second click should clip again");
  });

  test("review: unknown keys are ignored", () => {
    fresh();
    const r = REVIEW();
    r.extra = "<b>x</b>SECRET_TOP";
    r.citations[0].note = "SECRET_CITE";
    const p = V2("k1", r);
    p.review_view.extra = "SECRET_VIEW";
    plansOpen([p]);
    const card = cardOf("k1");
    expect(!/SECRET_/.test(card.textContent), "unknown key was rendered");
    expect(!approveBtn(card).disabled, "unknown keys must not block approval");
  });

  test("review: v1 plan (no review) is still approvable and says the hash covers actions only", () => {
    fresh();
    plans([PLAN("v1p", [SET([1], true)])]);
    const card = cardOf("v1p");
    expect(!approveBtn(card).disabled, "v1 plan blocked");
    expect(/Hash version 1/.test(card.textContent), "v1 note missing");
    approveBtn(card).click();
    expect(sentOf("plan.approve").length === 1, "approve not sent");
  });

  const BAD_REVIEWS = {
    "missing view": () => { const p = V2("f", REVIEW()); delete p.review_view; return p; },
    "hub says invalid": () => V2("f", null, { review_view: { status: "invalid", hash_version: 2, review: null, error: "not canonical" } }),
    "review null": () => V2("f", null),
    "citations not a list": () => { const r = REVIEW(); r.citations = "x"; return V2("f", r); },
    "assumption wrong type": () => { const r = REVIEW(); r.assumptions = [{ a: 1 }]; return V2("f", r); },
    "conflict field missing": () => { const r = REVIEW(); delete r.conflicts[0].revert_to; return V2("f", r); },
    "summary not a string": () => { const r = REVIEW(); r.summary = 5; return V2("f", r); },
    "v2 plan the hub reports as having no review": () => V2("f", null, { review_view: { status: "none", hash_version: 1, review: null } }),
  };
  function failClosed(plan) {
    fresh();
    plansOpen([plan]);
    const card = cardOf("f");
    const btn = approveBtn(card);
    expect(btn.disabled, "Approve is enabled for an unshowable review");
    expect(/aec-model-bridge-approve show/.test(card.textContent), "CLI fallback not named");
    expect(card.querySelector('[role="alert"]'), "no alert message");
    expect(!card.querySelector(".plan-select"), "bulk-select checkbox offered");
    btn.click();
    expect(sentOf("plan.approve").length === 0, "approve was sent");
    expect(!card.querySelector('[data-decision="reject"]').disabled, "Reject must stay available");
  }
  test("fail closed: missing view disables Approve and points to the CLI", () => failClosed(BAD_REVIEWS["missing view"]()));
  test("fail closed: hub says invalid disables Approve and points to the CLI", () => failClosed(BAD_REVIEWS["hub says invalid"]()));
  test("fail closed: review null disables Approve and points to the CLI", () => failClosed(BAD_REVIEWS["review null"]()));
  test("fail closed: citations not a list disables Approve and points to the CLI", () => failClosed(BAD_REVIEWS["citations not a list"]()));
  test("fail closed: assumption wrong type disables Approve and points to the CLI", () => failClosed(BAD_REVIEWS["assumption wrong type"]()));
  test("fail closed: conflict field missing disables Approve and points to the CLI", () => failClosed(BAD_REVIEWS["conflict field missing"]()));
  test("fail closed: summary not a string disables Approve and points to the CLI", () => failClosed(BAD_REVIEWS["summary not a string"]()));
  test("fail closed: v2 plan the hub reports as having no review disables Approve and points to the CLI", () => failClosed(BAD_REVIEWS["v2 plan the hub reports as having no review"]()));

  test("fail closed: a host status update does not re-enable a blocked Approve", () => {
    fresh();
    plansOpen([V2("f2", null)]);
    host({ serverRunning: true });
    diag("ask_first");
    expect(approveBtn(cardOf("f2")).disabled, "re-enabled by host.status");
    expect(document.querySelector('[data-action="approve-selected"]').disabled, "Approve Selected should have nothing to approve");
  });

  test("fail closed: a review that throws while rendering blocks Approve", () => {
    fresh();
    const long = REVIEW();
    long.summary = "S".repeat(1000); // takes the clipping path, which calls Array.from
    const real = Array.from;
    Array.from = function () { if (typeof arguments[0] === "string") throw new Error("boom"); return real.apply(Array, arguments); };
    try {
      plansOpen([V2("t1", long)]);
    } finally { Array.from = real; }
    const card = cardOf("t1");
    expect(approveBtn(card).disabled, "Approve enabled although rendering threw");
    expect(/aec-model-bridge-approve show/.test(card.textContent), "no CLI message");
  });

  test("review: a settled plan shows no review and no decision buttons", () => {
    fresh();
    plansOpen([V2("s1", REVIEW(), { state: "executed" })]);
    const card = cardOf("s1");
    expect(!card.querySelector(".plan-review-block") && !approveBtn(card), "settled plan shows decision UI");
  });


  test("review: Approve waits until the review has been opened, then works", () => {
    fresh();
    plans([V2("o1", REVIEW())]);
    let card = cardOf("o1");
    expect(approveBtn(card).disabled, "Approve should wait for the review");
    expect(!card.querySelector(".plan-review-block"), "review built before it was asked for");
    approveBtn(card).click();
    expect(sentOf("plan.approve").length === 0, "approve sent before the review was shown");
    card.querySelector("[data-open-review]").click();
    card = cardOf("o1");
    expect(card.querySelector(".plan-review-block"), "review not built on demand");
    expect(!approveBtn(card).disabled, "Approve still off after the review was shown");
    approveBtn(card).click();
    expect(sentOf("plan.approve").length === 1, "approve not sent");
  });

  test("review: invisible filler characters and long combining runs are escaped", () => {
    fresh();
    const r = REVIEW();
    r.summary = "aㅤbᅟcᅠdﾠe⠀f";
    r.warnings = ["x" + "́".repeat(40)];
    plansOpen([V2("fi1", r)]);
    const t = cardOf("fi1").querySelector(".plan-review-block").textContent;
    for (const ch of ["ㅤ", "ᅟ", "ᅠ", "ﾠ", "⠀"]) expect(!t.includes(ch), "raw filler " + ch.charCodeAt(0).toString(16));
    expect(t.includes("\\u3164") && t.includes("\\u2800"), "fillers not shown as escapes");
    expect((t.match(/́/g) || []).length <= 2, "combining run not capped");
    expect(/more combining marks hidden/.test(t), "no note about hidden marks");
  });

  test("review: a list over the cap blocks Approve and names the CLI", () => {
    fresh();
    const r = REVIEW();
    r.warnings = Array.from({ length: 101 }, (_, i) => "w" + i);
    plansOpen([V2("cap1", r)]);
    const card = cardOf("cap1");
    expect(approveBtn(card).disabled, "Approve enabled although entries are not all shown");
    expect(/aec-model-bridge-approve show/.test(card.textContent), "CLI not named");
  });

  test("review: an integer the page cannot show exactly blocks Approve", () => {
    fresh();
    const r = REVIEW();
    r.excluded = [{ element_id: 9007199254740992, reason: "x" }];
    plansOpen([V2("big1", r)]);
    expect(approveBtn(cardOf("big1")).disabled, "unsafe integer was shown");
  });

  test("review: hub output that redaction changed arrives as invalid and cannot be approved", () => {
    fresh();
    const p = V2("red1", null, { review_view: { status: "invalid", hash_version: null, reverts_plan_id: null, review: null, error: "This plan contains text the panel hides" } });
    plansOpen([p]);
    const card = cardOf("red1");
    expect(approveBtn(card).disabled, "Approve enabled for redacted content");
    expect(/the panel hides/.test(card.textContent), "reason not shown");
  });

  test("review: 200 plans of 100-entry reviews render within the time budget and are capped", () => {
    fresh();
    const many = [];
    for (let i = 0; i < 200; i++) {
      const r = REVIEW();
      r.conflicts = Array.from({ length: 100 }, (_, k) => ({ element_id: k, parameter: "P" + k, expected_current: "x".repeat(180), actual_current: "y".repeat(180), revert_to: "z".repeat(180) }));
      r.excluded = Array.from({ length: 100 }, (_, k) => ({ element_id: k, reason: "r".repeat(400) }));
      many.push(V2("m" + i, r));
    }
    const t0 = performance.now();
    plans(many);
    const ms = performance.now() - t0;
    expect(document.querySelectorAll("#plan-list > article").length === 50, "plan cap not applied");
    expect(/150 more pending plan/.test($("plan-list").textContent), "omitted plans not announced");
    expect(document.querySelectorAll(".plan-review-block").length === 0, "reviews built eagerly");
    expect(ms < 1500, "rendering 200 pending plans took " + Math.round(ms) + " ms (budget 1500)");
  });


  test("card: shows the plan id and a copyable aec-model-bridge-approve show command", () => {
    fresh();
    plans([PLAN("plan_0123456789ab", [SET([1], true)])]);
    const card = cardOf("plan_0123456789ab");
    expect(card.querySelector(".plan-cli code").textContent === "plan_0123456789ab", "plan id not shown");
    expect(card.querySelector(".plan-cli-command").textContent === "aec-model-bridge-approve show plan_0123456789ab", "command not shown");
    card.querySelector("[data-copy-command]").click();
    expect(window.__copied.includes("aec-model-bridge-approve show plan_0123456789ab"), "command not copied");
  });

  test("card: a blocked v1 plan says what is blocked without talking about a review", () => {
    fresh();
    const p = PLAN("plan_aaaaaaaaaaaa", [SET([1], true)]);
    p.review_view = { status: "invalid", hash_version: null, review: null, error: "Legacy plan with content outside the approval hash." };
    plans([p]);
    const t = cardOf("plan_aaaaaaaaaaaa").querySelector('[role="alert"]').textContent;
    expect(/cannot be shown completely/.test(t) && !/review could not/.test(t), "wording: " + t);
    expect(/aec-model-bridge-approve show plan_aaaaaaaaaaaa/.test(t), "no command with the plan id");
    expect(/Legacy plan/.test(t), "reason missing");
  });

  test("card: a long code argument is shown, clipped, and Show all actions reveals the end", () => {
    fresh();
    const code = "import os\n" + "x = 1\n".repeat(2000) + "THE_END";
    plans([PLAN("plan_bbbbbbbbbbbb", [{ tool: "rhino_run_python", arguments: { code } }])]);
    const card = cardOf("plan_bbbbbbbbbbbb");
    const pre = card.querySelector("pre.plan-review");
    expect(pre.textContent.includes("import os") && !pre.textContent.includes("THE_END"), "not clipped");
    const more = Array.from(card.querySelectorAll("button")).find((b) => /^Show all actions/.test(b.textContent));
    expect(more, "no Show all actions button");
    more.click();
    expect(pre.textContent.includes("THE_END"), "full action text not revealed");
  });

  test("card: plans the hub left out are announced with the CLI list command", () => {
    fresh();
    deliver({ type: "plans.updated", result: { plans: [PLAN("plan_cccccccccccc", [SET([1], true)])], omitted: 7 } });
    expect(/7 more pending plan/.test($("plan-list").textContent), "omitted count not shown");
    expect(/aec-model-bridge-approve list/.test($("plan-list").textContent), "list command not named");
  });

  // ---- Issue #151: bulk reject, bound document, expiry ----
  const tick = (id) => { const b = cardOf(id).querySelector("[data-select-plan]"); b.click(); return b; };
  const bulk = () => document.querySelector('[data-action="reject-selected"]');

  test("bulk reject: 3 ticked plans are rejected once each after a confirmation that shows the count; others stay pending", () => {
    fresh();
    plans(["b1", "b2", "b3", "b4", "b5"].map((id) => PLAN(id, [SET([1], true)])));
    expect(bulk().disabled, "Reject Selected should wait for a selection");
    ["b1", "b2", "b3"].forEach(tick);
    expect(!bulk().disabled, "Reject Selected should enable");
    sent().length = 0;
    bulk().click();
    expect(sentOf("plan.reject").length === 0, "rejected before the confirmation");
    const bar = $("reject-confirm");
    expect(!bar.hidden && /Reject 3 selected/.test($("reject-confirm-text").textContent), "confirmation line lacks the count");
    document.querySelector('[data-action="reject-confirm"]').click();
    const rej = sentOf("plan.reject");
    expect(rej.map((m) => m.planId).sort().join() === "b1,b2,b3", "wrong plans rejected: " + JSON.stringify(rej));
    expect(rej.every((m) => m.planHash === "abcdef0123456789" && Object.keys(m).sort().join() === "planHash,planId,type"), "payload differs from the single Reject");
    expect(sentOf("plan.approve").length === 0, "bulk reject sent an approval");
    expect(bar.hidden, "confirmation still open");
    expect(cardOf("b4") && cardOf("b5"), "unselected plans vanished");
    plans([PLAN("b4", [SET([1], true)]), PLAN("b5", [SET([1], true)])]);
    expect(document.querySelectorAll("#plan-list .badge").length === 2 && !cardOf("b1"), "list not refreshed");
    expect(sentOf("plan.reject").length === 3, "extra reject sent");
  });

  test("bulk reject: Cancel sends nothing", () => {
    fresh();
    plans([PLAN("c1", [SET([1], true)])]);
    tick("c1");
    sent().length = 0;
    bulk().click();
    document.querySelector('[data-action="reject-cancel"]').click();
    expect($("reject-confirm").hidden && sentOf("plan.reject").length === 0, "cancel did not stop the reject");
  });

  test("bound document: title and expiry are shown escaped; another document is hidden, and warns once shown", () => {
    fresh();
    const bound = { doc_title: "Other<img src=x onerror=window.__pwned=9>.rvt", doc_guid: "g" };
    plans([PLAN("d1", [SET([1], true)])].map((p) => Object.assign(p, { binding: bound, expires_at: "2030-01-02T03:04:05Z" })));
    expect(!cardOf("d1") && /1 plan for other models hidden/.test($("other-note").textContent), "other model's plan not collapsed");
    expect(!/Other/.test($("plan-list").textContent), "hidden plan details were rendered");
    document.querySelector('[data-action="toggle-other-plans"]').click();
    const card = cardOf("d1");
    expect(/Bound to document: Other/.test(card.textContent) && /Expires:/.test(card.textContent), "binding or expiry missing");
    expect(!card.querySelector("img"), "binding title was not escaped");
    const warn = card.querySelector('[role="alert"]');
    expect(warn && /active document is m\.rvt/.test(warn.textContent), "no mismatch warning");
    expect(approveBtn(card).getAttribute("aria-describedby") === warn.id, "Approve not tied to the warning");
    document.querySelector('[data-action="toggle-other-plans"]').click();
    expect(!cardOf("d1"), "Hide did not collapse the plan again");
    plans([PLAN("d2", [SET([1], true)])].map((p) => Object.assign(p, { binding: { doc_title: "M", doc_guid: "g1", revit_pid: 7 } })));
    expect(!cardOf("d2").querySelector('[id^="plan-warn-"]'), "warned although the document matches");
  });

  test("another Revit process with the same document is hidden, and warns about the pid once shown", () => {
    fresh();
    plans([PLAN("pid1", [SET([1], true)])].map((p) => Object.assign(p, { binding: { doc_title: "m.rvt", doc_guid: "g1", revit_pid: 8 } })));
    expect(!cardOf("pid1") && !$("other-bar").hidden, "same title, other pid was listed");
    document.querySelector('[data-action="toggle-other-plans"]').click();
    const warn = cardOf("pid1").querySelector('[id^="plan-warn-"]');
    expect(warn && /process 8/.test(warn.textContent) && /process 7/.test(warn.textContent), "no pid warning");
  });

  test("unbound plan: warning shown, Approve disabled until the confirm is ticked", () => {
    fresh();
    plans([Object.assign(PLAN("u1", [SET([1], true)]), { binding: null })]);
    const card = cardOf("u1");
    expect(card.querySelector('[id^="plan-unbound-"]') && !/Bound to document|Expires:/.test(card.textContent), "no unbound warning");
    expect(approveBtn(card).disabled, "unbound plan approvable before the confirm");
    approveBtn(card).click();
    expect(sentOf("plan.approve").length === 0, "approve sent without the confirm");
    const box = card.querySelector("[data-confirm-unbound]");
    box.checked = true;
    box.dispatchEvent(new Event("change", { bubbles: true }));
    expect(!approveBtn(cardOf("u1")).disabled, "confirm did not enable Approve");
    approveBtn(cardOf("u1")).click();
    expect(sentOf("plan.approve").length === 1, "approve not sent after the confirm");
  });

  test("expired plans: N hidden is announced, the toggle asks the host, expired plans cannot be approved but can be rejected in bulk", () => {
    fresh();
    deliver({ type: "plans.updated", result: { plans: [PLAN("e1", [SET([1], true)])], expired_hidden: 2 } });
    expect(!$("expired-bar").hidden && /2 expired plan\(s\) hidden/.test($("expired-note").textContent), "hidden count not shown");
    sent().length = 0;
    $("expired-toggle").click();
    const ask = sentOf("plans.refresh");
    expect(ask.length === 1 && ask[0].includeExpired === true, "toggle did not request expired plans: " + JSON.stringify(ask));
    deliver({ type: "plans.updated", result: { plans: [PLAN("e1", [SET([1], true)]), Object.assign(PLAN("e2", [SET([1], true)]), { expired: true })], expired_hidden: 0 } });
    const card = cardOf("e2");
    expect(approveBtn(card).disabled, "expired plan can be approved");
    approveBtn(card).click();
    expect(sentOf("plan.approve").length === 0, "approve sent for an expired plan");
    tick("e2");
    expect(document.querySelector('[data-action="approve-selected"]').disabled, "Approve Selected accepts an expired plan");
    expect(!bulk().disabled, "expired plan cannot be bulk-rejected");
    sent().length = 0;
    bulk().click();
    document.querySelector('[data-action="reject-confirm"]').click();
    expect(sentOf("plan.reject").map((m) => m.planId).join() === "e2" && sentOf("plan.approve").length === 0, "expired reject wrong");
  });

  // ---- layout: status strip, one Refresh per view, confirm bar trigger, footer, compact empty state ----
  const visible = (el) => !!el && getComputedStyle(el).display !== "none" && el.getClientRects().length > 0;
  const nav = (v) => document.querySelector('.nav[data-view="' + v + '"]').click();

  test("confirm bar: closed on load, on render and on view switches; opens only from Reject selected; Confirm alone sends nothing", () => {
    fresh();
    nav("plans");
    plans([PLAN("k1", [SET([1], true)]), PLAN("k2", [SET([1], true)])]);
    const bar = $("reject-confirm");
    expect(bar.hidden && !visible(bar), "confirm bar visible before any Reject selected click");
    tick("k1");
    tick("k2");
    nav("chat"); nav("plans");
    plans([PLAN("k1", [SET([1], true)]), PLAN("k2", [SET([1], true)])]);
    expect(!visible(bar), "bar opened by a render or a view switch");
    sent().length = 0;
    document.querySelector('[data-action="reject-confirm"]').click();
    expect(sentOf("plan.reject").length === 0, "Confirm rejected a plan although the bar was never opened");
    bulk().click();
    expect(visible(bar) && /Reject 2 selected/.test($("reject-confirm-text").textContent), "bar did not open from Reject selected");
    expect(!visible($("plan-bulk")), "bulk footer and confirm bar are both shown");
    document.querySelector('[data-action="reject-cancel"]').click();
    expect(!visible(bar) && sentOf("plan.reject").length === 0, "Cancel left the bar open or rejected");
  });

  test("confirm bar: a refreshed list closes it", () => {
    fresh();
    nav("plans");
    plans([PLAN("r1", [SET([1], true)]), PLAN("r2", [SET([1], true)])]);
    tick("r1"); tick("r2");
    bulk().click();
    expect(visible($("reject-confirm")), "bar did not open");
    plans([PLAN("r1", [SET([1], true)]), PLAN("r2", [SET([1], true)])]);
    expect(!visible($("reject-confirm")), "bar survived a list refresh");
    sent().length = 0;
    document.querySelector('[data-action="reject-confirm"]').click();
    expect(sentOf("plan.reject").length === 0, "stale Confirm rejected a plan");
  });

  test("bulk footer: hidden with fewer than two ticked plans, shown with two, one row", () => {
    fresh();
    nav("plans");
    plans([PLAN("f1", [SET([1], true)]), PLAN("f2", [SET([1], true)])]);
    expect(!visible($("plan-bulk")), "footer shown with nothing ticked");
    tick("f1");
    expect(!visible($("plan-bulk")), "footer shown for one plan; its card has the buttons");
    tick("f2");
    expect(visible($("plan-bulk")) && $("plan-selected-count").textContent === "2 selected", "footer missing for two");
    const tops = Array.from($("plan-bulk").children).filter(visible).map((n) => n.getBoundingClientRect().top);
    expect(Math.max(...tops) - Math.min(...tops) < 20, "footer is not one row");
  });

  test("one Refresh per view: Plans and Reports have no button of their own; the strip Refresh asks for the view's list", () => {
    fresh();
    ["plans", "reports", "findings", "log", "settings"].forEach((v) => {
      nav(v);
      const shown = Array.from(document.querySelectorAll("button")).filter((b) => visible(b) && /^refresh/i.test(b.textContent.trim()));
      expect(shown.length === 1 && shown[0].id === "setup-refresh", v + ": " + shown.length + " Refresh buttons");
    });
    nav("plans");
    sent().length = 0;
    $("setup-refresh").click();
    expect(sentOf("plans.refresh").length === 1 && sentOf("diagnostics.refresh").length === 1, "Plans refresh not sent: " + JSON.stringify(sent().map((m) => m.type)));
    nav("reports");
    sent().length = 0;
    $("setup-refresh").click();
    expect(sentOf("reports.refresh").length === 1 && sentOf("plans.refresh").length === 0, "Reports refresh wrong");
  });

  test("status strip: setup check and snapshot warning share one collapsed strip that expands on click", () => {
    fresh();
    nav("plans");
    host({ snapshotStale: true, dirtyElementCount: 3 });
    deliver({ type: "diagnostics.updated", diagnostics: { ok: false, approval_mode: "ask_first", checks: [
      { id: "mode", ok: false, detail: "Hub is in mock mode.", next_step: "Set MCP_REVIT_MODE=bridge." },
      { id: "hub", ok: true, detail: "Panel hub is running." }] } });
    const strip = $("setup-check");
    expect(strip.dataset.state === "blocked" && /2 to fix/.test($("setup-label").textContent), "label: " + $("setup-label").textContent);
    expect(/Live Revit mode/.test($("setup-summary").textContent) && /Snapshot stale/.test($("setup-summary").textContent), "summary: " + $("setup-summary").textContent);
    expect(!visible($("setup-body")) && !visible($("system-alerts")) && !visible($("setup-list")), "strip starts expanded");
    expect(strip.getBoundingClientRect().height < 60, "strip is " + strip.getBoundingClientRect().height + "px tall");
    $("setup-toggle").click();
    expect($("setup-toggle").getAttribute("aria-expanded") === "true" && visible($("setup-body")), "did not expand");
    expect(/Snapshot stale/.test($("system-alerts").textContent) && /MCP_REVIT_MODE=bridge/.test($("setup-list").textContent), "alert or step missing when expanded");
    $("setup-toggle").click();
    expect(!visible($("setup-body")), "did not collapse");
    host({ snapshotStale: false });
    diag("ask_first");
    expect(strip.dataset.state === "ready" && $("setup-label").textContent === "Ready", "did not return to Ready");
  });

  test("empty plans: one compact line, no second block of text", () => {
    fresh();
    nav("plans");
    plans([]);
    const empty = document.querySelector("#plan-list .empty");
    expect(empty && empty.classList.contains("is-compact") && /No pending plans/.test(empty.textContent), "compact empty state missing");
    expect(empty.getBoundingClientRect().height < 56 && empty.querySelectorAll("p").length === 0, "empty state is a box: " + empty.getBoundingClientRect().height);
    expect(!visible($("plan-bulk")), "footer shown with no plans");
  });

  test("plan card: Approve and Reject are sticky, so a long review cannot push them off screen", () => {
    fresh();
    nav("plans");
    const long = Array.from({ length: 60 }, (_, i) => "line " + i + " of the review").join("\n");
    plans([V2("s1", { summary: long, reasoning: long, citations: [], assumptions: [], excluded: [], warnings: [], conflicts: [] })]);
    const open = $("plan-list").querySelector("[data-open-review]");
    if (open) open.click();
    const card = cardOf("s1");
    const actions = card.querySelector(".item-actions");
    expect(getComputedStyle(actions).position === "sticky", "actions are " + getComputedStyle(actions).position);
    const list = $("plan-list");
    list.scrollTop = 0;
    expect(card.getBoundingClientRect().height > list.getBoundingClientRect().height, "card is not taller than the list; the test proves nothing");
    expect(actions.getBoundingClientRect().bottom <= list.getBoundingClientRect().bottom + 1, "Approve/Reject below the visible list at the top of a long card");
  });

  test("preview: no Element or Parameter column when the hub names neither (no repeated unknown cells)", () => {
    fresh();
    plans([V2("pn1", null, { review_view: { status: "none", hash_version: 1, reverts_plan_id: null, review: null, error: "" }, hash_version: undefined,
      preview: { rows: [ROW(1, { element_id: null, parameter: null, before: "(not captured)", after: "{}" })], row_count: 1, rows_omitted: 0 }, blast_radius: RADIUS })]);
    const cells = Array.from(cardOf("pn1").querySelectorAll(".plan-preview-table tr")).map((tr) => Array.from(tr.children).map((c) => c.textContent));
    expect(cells[0].join() === "Before,After,Tool" && cells[1][0] === "(not captured)" && cells[1][1] === "{}", "cells " + JSON.stringify(cells));
  });

  window.addEventListener("load", () => { runAll(); });
})();

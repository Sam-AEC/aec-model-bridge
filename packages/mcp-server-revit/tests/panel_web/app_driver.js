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
    deliver(Object.assign({ type: "host.status", serverRunning: true, activeDocument: "m.rvt", revitVersion: "2025", port: 1 }, extra));
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
  const PLAN = (id, actions, state) => ({ plan_id: id, plan_hash: "abcdef0123456789", state: state || "pending", actions });
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

  window.addEventListener("load", () => { runAll(); });
})();

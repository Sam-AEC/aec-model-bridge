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
    plan_id: id, plan_hash: "abcdef0123456789", state: "pending", hash_version: 2,
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

  window.addEventListener("load", () => { runAll(); });
})();

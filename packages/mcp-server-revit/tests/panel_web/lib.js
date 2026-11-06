/* Tiny in-page test runner for the panel browser tests (no npm dependencies).
 * Results are written to <pre id="amb-results"> as JSON so that
 * `chromium --headless --dump-dom` output can be parsed by tests/test_panel_chat_browser.py.
 * Plain classic script: the panel page CSP (script-src 'self') applies to the harness too. */
(function () {
  "use strict";
  const cases = [];
  window.test = function (name, fn) { cases.push({ name, fn }); };
  window.expect = function (cond, msg) { if (!cond) throw new Error(msg || "expectation failed"); };
  window.sleep = function (ms) { return new Promise((r) => setTimeout(r, ms)); };
  let current = "(none started)";
  let finished = false;
  function publish(results) {
    const pre = document.createElement("pre");
    pre.id = "amb-results";
    pre.textContent = JSON.stringify(results);
    document.body.appendChild(pre);
  }
  // Fail fast and say where: a case that never settles is reported, not left to hang.
  setTimeout(() => {
    if (finished) return;
    publish([{ name: "__watchdog__", ok: false, error: "page did not finish in 40s; stuck in case: " + current }]);
  }, 40000);
  window.runAll = async function () {
    const results = [];
    for (const c of cases) {
      current = c.name;
      try { await c.fn(); results.push({ name: c.name, ok: true }); }
      catch (e) { results.push({ name: c.name, ok: false, error: String((e && e.stack) || e).slice(0, 600) }); }
    }
    finished = true;
    publish(results);
  };
  window.addEventListener("error", (e) => {
    (window.__pageErrors = window.__pageErrors || []).push(String(e.message));
  });
})();

/* Stubs the WebView2 host for the real panel page. Loaded BEFORE panel scripts. */
(function () {
  "use strict";
  const handlers = [];
  window.__sent = [];
  window.__csp = [];
  window.__copied = [];
  document.addEventListener("securitypolicyviolation", (e) => {
    window.__csp.push(e.violatedDirective + " " + e.blockedURI);
  });
  window.chrome = {
    webview: {
      postMessage(text) { window.__sent.push(JSON.parse(text)); },
      addEventListener(type, fn) { if (type === "message") handlers.push(fn); },
    },
  };
  window.__deliver = function (data) { handlers.forEach((h) => h({ data })); };
  // Clipboard permission in WebView2 is UNVERIFIED; record what would be copied.
  Object.defineProperty(navigator, "clipboard", {
    configurable: true,
    value: { writeText(t) { window.__copied.push(String(t)); return Promise.resolve(); } },
  });
})();

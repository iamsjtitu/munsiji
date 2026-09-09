// PWA bootstrap (external file so a strict CSP without 'unsafe-inline' scripts can be used)
if ("serviceWorker" in navigator) {
  window.addEventListener("load", function () {
    navigator.serviceWorker.register("/sw.js").catch(function () {});
  });
}

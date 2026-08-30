// Embed boot: when framed by the dsh web shell, skin Studio with the dsh
// palette (embed-dsh.css) and follow the shell's light/dark theme
// (?theme= at load, then live via postMessage 'studio-theme' — handled by
// application.js applyShellTheme). Must be an EXTERNAL script: Studio's CSP
// is script-src 'self', so inline scripts never execute.
// Detection: an explicit ?embed=dsh, or simply being framed at all — the
// frame-ancestors allowlist already restricts embedding to the dsh shell.
// The mode is remembered in sessionStorage so in-app navigation that drops
// the query string cannot escape embed mode. Standalone visits unaffected.
(function () {
  var root = document.documentElement;
  var params = new URLSearchParams(location.search);
  var embedded = params.get('embed') === 'dsh' || window.self !== window.top;
  try {
    if (params.get('embed') === 'dsh') sessionStorage.setItem('openwrite-embed', 'dsh');
    embedded = embedded || sessionStorage.getItem('openwrite-embed') === 'dsh';
  } catch (storageError) { /* sessionStorage unavailable: param/frame detection still applies */ }
  if (!embedded) return;
  root.dataset.embed = 'dsh';
  var theme = params.get('theme');
  if (theme === 'dark' || theme === 'light') root.dataset.theme = theme;
})();

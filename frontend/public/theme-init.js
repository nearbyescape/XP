// Applies the saved theme before first paint (external file so the CSP can forbid inline scripts).
try {
  var t = localStorage.getItem("sd-theme");
  if (t === "light" || t === "dark") document.documentElement.dataset.theme = t;
} catch (e) {}

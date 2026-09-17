/* Apply appearance before the first stylesheet paints. */
(() => {
  try {
    const theme = localStorage.getItem("cellulary.theme");
    document.documentElement.dataset.theme = ["light", "dark", "system"].includes(theme) ? theme : "system";
    document.documentElement.lang = localStorage.getItem("cellulary.language") === "zh" ? "zh-CN" : "en";
  } catch { /* English and system appearance also work with storage disabled. */ }
})();

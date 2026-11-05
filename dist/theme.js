// Run before the stylesheet so a saved preference applies before first paint.
(() => {
  const key = "food-recalls-theme";
  const valid = (value) => ["light", "dark"].includes(value) ? value : "system";
  const apply = (value) => {
    if (value === "system") document.documentElement.removeAttribute("data-theme");
    else document.documentElement.dataset.theme = value;
  };
  let preference = "system";
  try { preference = valid(localStorage.getItem(key)); } catch { /* Storage may be unavailable. */ }
  apply(preference);

  document.addEventListener("DOMContentLoaded", () => {
    const select = document.getElementById("theme-select");
    if (!select) return;
    select.value = preference;
    select.addEventListener("change", () => {
      preference = valid(select.value);
      apply(preference);
      try { localStorage.setItem(key, preference); } catch { /* Theme still works for this page. */ }
    });
    window.addEventListener("storage", (event) => {
      if (event.key !== key && event.key !== null) return;
      preference = valid(event.newValue);
      apply(preference);
      select.value = preference;
    });
  });
})();

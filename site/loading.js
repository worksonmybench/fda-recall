// Match placeholders to the existing data containers; leave headings readable.
export function showPlaceholders() {
  const targets = [...document.querySelectorAll(".chart:empty, .tiles:empty, .recall-cards:empty, #results:empty")];
  for (const target of targets) {
    target.setAttribute("aria-busy", "true");
    const count = target.matches(".tiles, .recall-cards") ? 3 : 1;
    for (let i = 0; i < count; i++) {
      const placeholder = document.createElement("div");
      placeholder.className = "skeleton";
      placeholder.setAttribute("aria-hidden", "true");
      target.append(placeholder);
    }
  }
  const texts = [...document.querySelectorAll("#answer, #firm, #data-updated")]
    .filter((target) => target.textContent.startsWith("Loading"));
  texts.forEach((target) => target.classList.add("loading-text"));
  return () => {
    targets.forEach((target) => {
      target.removeAttribute("aria-busy");
      target.querySelectorAll(".skeleton").forEach((placeholder) => placeholder.remove());
    });
    texts.forEach((target) => target.classList.remove("loading-text"));
  };
}

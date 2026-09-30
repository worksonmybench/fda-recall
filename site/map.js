// Tile-grid map of US states: equal squares in a rough geographic layout, so
// small states (RI, DE, DC) are as visible and clickable as large ones.
import { formatNumber, hideTooltip, showTooltip } from "./charts.js";

const SVG_NS = "http://www.w3.org/2000/svg";

// [code, column, row]
const LAYOUT = [
  ["AK", 0, 0], ["ME", 11, 0],
  ["VT", 10, 1], ["NH", 11, 1],
  ["WA", 1, 2], ["ID", 2, 2], ["MT", 3, 2], ["ND", 4, 2], ["MN", 5, 2], ["IL", 6, 2], ["WI", 7, 2],
  ["MI", 8, 2], ["NY", 9, 2], ["RI", 10, 2], ["MA", 11, 2],
  ["OR", 1, 3], ["NV", 2, 3], ["WY", 3, 3], ["SD", 4, 3], ["IA", 5, 3], ["IN", 6, 3], ["OH", 7, 3],
  ["PA", 8, 3], ["NJ", 9, 3], ["CT", 10, 3],
  ["CA", 1, 4], ["UT", 2, 4], ["CO", 3, 4], ["NE", 4, 4], ["MO", 5, 4], ["KY", 6, 4], ["WV", 7, 4],
  ["VA", 8, 4], ["MD", 9, 4], ["DE", 10, 4],
  ["AZ", 2, 5], ["NM", 3, 5], ["KS", 4, 5], ["AR", 5, 5], ["TN", 6, 5], ["NC", 7, 5], ["SC", 8, 5], ["DC", 9, 5],
  ["OK", 4, 6], ["LA", 5, 6], ["MS", 6, 6], ["AL", 7, 6], ["GA", 8, 6],
  ["HI", 0, 7], ["TX", 4, 7], ["FL", 9, 7], ["PR", 11, 7],
  ["GU", 0, 8], ["MP", 1, 8], ["AS", 2, 8], ["VI", 11, 8],
];
const COLS = 12;
const ROWS = 9;
const BINS = 6; // --seq-1 .. --seq-6; zero gets --seq-0

function el(tag, attrs = {}, text) {
  const node = document.createElementNS(SVG_NS, tag);
  for (const [k, v] of Object.entries(attrs)) node.setAttribute(k, v);
  if (text !== undefined) node.textContent = text;
  return node;
}

function niceRound(v) {
  if (v < 10) return Math.max(1, Math.round(v));
  const pow = 10 ** Math.floor(Math.log10(v));
  return Math.round(v / (pow / 2)) * (pow / 2);
}

/** Upper bounds (exclusive) for bins 1..n, from quantiles of the non-zero values. */
export function computeBins(values) {
  const nonzero = values.filter((v) => v > 0).sort((a, b) => a - b);
  if (!nonzero.length) return [];
  const bounds = [];
  for (let i = 1; i < BINS; i++) {
    const q = nonzero[Math.floor((nonzero.length * i) / BINS)];
    const b = niceRound(q);
    // bins start at 1, so the first upper bound must be at least 2
    if (b > (bounds.at(-1) ?? 1) && b <= nonzero.at(-1)) bounds.push(b);
  }
  bounds.push(Infinity);
  return bounds;
}

const binOf = (v, bounds) => (v <= 0 ? 0 : bounds.findIndex((b) => v < b) + 1);

export function binLabels(bounds) {
  let lo = 1;
  return bounds.map((hi) => {
    const text = hi === Infinity ? `${formatNumber(lo)}+` : hi - 1 === lo ? formatNumber(lo) : `${formatNumber(lo)}–${formatNumber(hi - 1)}`;
    lo = hi;
    return text;
  });
}

/**
 * Render the map.
 * states: {CODE: {name, impacting: {...}, originating: {...}}}
 * view: "impacting" | "originating"; selected: code or "US"; onSelect(code)
 */
export function renderTileMap(container, { states, view, selected, metric = "ongoing", onSelect }) {
  const values = LAYOUT.map(([code]) => states[code]?.[view]?.[metric] ?? 0);
  const bounds = computeBins(values);

  const width = Math.max(300, container.clientWidth);
  const gap = 2;
  const size = Math.min(58, Math.floor((width - gap * (COLS - 1)) / COLS));
  const mapW = size * COLS + gap * (COLS - 1);
  const mapH = size * ROWS + gap * (ROWS - 1);
  const svg = el("svg", {
    width: mapW, height: mapH, viewBox: `0 0 ${mapW} ${mapH}`, class: "tile-map",
    role: "group", "aria-label": "Map of US states; select a state to see its recalls",
  });

  LAYOUT.forEach(([code, col, row], i) => {
    const info = states[code];
    if (!info) return;
    const stats = info[view];
    const bin = binOf(values[i], bounds);
    const x = col * (size + gap);
    const y = row * (size + gap);
    const g = el("g", {
      class: `tile${code === selected ? " selected" : ""}`,
      tabindex: 0, role: "button",
      "aria-pressed": code === selected ? "true" : "false",
      "aria-label": `${info.name}: ${formatNumber(values[i])} ongoing recall events`,
    });
    g.append(el("rect", { x, y, width: size, height: size, rx: 4, fill: `var(--seq-${bin})` }));
    const ink = `var(--seq-ink-${bin})`;
    const big = size >= 40;
    g.append(el("text", {
      x: x + size / 2, y: y + size / 2 + (big ? -5 : 0), fill: ink,
      "text-anchor": "middle", "dominant-baseline": "middle", class: "tile-code",
    }, code));
    if (big) {
      g.append(el("text", {
        x: x + size / 2, y: y + size / 2 + 10, fill: ink,
        "text-anchor": "middle", "dominant-baseline": "middle", class: "tile-value",
      }, formatNumber(values[i])));
    }

    const rows = () => {
      const r = [
        { label: "ongoing recall events", value: formatNumber(stats.ongoing) },
        { label: "recall events since 2012", value: formatNumber(stats.events) },
        { label: "Class I (most serious)", value: formatNumber(stats.class_1) },
        { label: "with illnesses reported", value: formatNumber(stats.illness) },
      ];
      if (view === "impacting" && stats.via_nationwide) {
        r.push({ label: "of all events were nationwide", value: formatNumber(stats.via_nationwide) });
      }
      return r;
    };
    const show = (e) => showTooltip(e, info.name, rows());
    g.addEventListener("pointermove", show);
    g.addEventListener("focus", show);
    g.addEventListener("pointerleave", hideTooltip);
    g.addEventListener("blur", hideTooltip);
    const choose = () => { hideTooltip(); onSelect(code === selected ? "US" : code); };
    g.addEventListener("click", choose);
    g.addEventListener("keydown", (e) => {
      if (e.key === "Enter" || e.key === " ") { e.preventDefault(); choose(); }
    });
    svg.append(g);
  });

  container.replaceChildren(svg);
  return { bounds, values };
}

export function renderMapLegend(container, bounds) {
  const items = [["0", 0], ...binLabels(bounds).map((text, i) => [text, i + 1])];
  container.replaceChildren(
    ...items.map(([text, bin]) => {
      const key = document.createElement("span");
      key.className = "key";
      const sw = document.createElement("span");
      sw.className = "swatch";
      sw.style.background = `var(--seq-${bin})`;
      key.append(sw, document.createTextNode(text));
      return key;
    })
  );
}

export const MAP_CODES = LAYOUT.map(([code]) => code);

/** Small static map highlighting the states one recall reached. */
export function renderReachMap(container, { states = [], nationwide = false, names = {} }) {
  const reached = new Set(states);
  const width = Math.min(420, Math.max(240, container.clientWidth));
  const gap = 2;
  const size = Math.floor((width - gap * (COLS - 1)) / COLS);
  const mapW = size * COLS + gap * (COLS - 1);
  const mapH = size * ROWS + gap * (ROWS - 1);
  const svg = el("svg", {
    width: mapW, height: mapH, viewBox: `0 0 ${mapW} ${mapH}`, class: "tile-map reach-map", role: "img",
    "aria-label": nationwide ? "Distributed nationwide" : `Distributed to ${reached.size} states and territories`,
  });
  for (const [code, col, row] of LAYOUT) {
    // Nationwide covers the 50 states + DC, not the territories.
    const on = reached.has(code) || (nationwide && !["PR", "GU", "VI", "AS", "MP"].includes(code));
    const x = col * (size + gap);
    const y = row * (size + gap);
    const g = el("g", { class: "tile" });
    g.append(el("title", {}, `${names[code] ?? code}: ${on ? "reached" : "not listed"}`));
    g.append(el("rect", { x, y, width: size, height: size, rx: 3, fill: on ? "var(--seq-5)" : "var(--seq-0)" }));
    if (size >= 22) {
      g.append(el("text", {
        x: x + size / 2, y: y + size / 2, fill: on ? "var(--seq-ink-5)" : "var(--seq-ink-0)",
        "text-anchor": "middle", "dominant-baseline": "middle", class: "tile-code small",
      }, code));
    }
    svg.append(g);
  }
  container.replaceChildren(svg);
}

// Small, dependency-free chart helpers. All text goes in via textContent.

const SVG_NS = "http://www.w3.org/2000/svg";
const fmt = new Intl.NumberFormat("en-US");
export const formatNumber = (n) => fmt.format(n ?? 0);

function el(tag, attrs = {}, text) {
  const node = tag.startsWith("svg:") ? document.createElementNS(SVG_NS, tag.slice(4)) : document.createElement(tag);
  for (const [k, v] of Object.entries(attrs)) node.setAttribute(k, v);
  if (text !== undefined) node.textContent = text;
  return node;
}

// --- tooltip ---------------------------------------------------------------

const tooltip = () => document.getElementById("tooltip");

export function showTooltip(event, title, rows) {
  const tip = tooltip();
  tip.replaceChildren(el("div", { class: "title" }, title));
  for (const { label, value, color } of rows) {
    const row = el("div", { class: "row" });
    if (color) row.append(el("span", { class: "linekey", style: `background:${color}` }));
    row.append(el("strong", {}, value), el("span", {}, label));
    tip.append(row);
  }
  tip.hidden = false;
  let x, y;
  if (event.clientX !== undefined && event.type.startsWith("pointer")) {
    x = event.clientX; y = event.clientY;
  } else {
    const r = event.currentTarget.getBoundingClientRect();
    x = r.left + r.width / 2; y = r.top;
  }
  const { width, height } = tip.getBoundingClientRect();
  tip.style.left = `${Math.min(Math.max(8, x + 12), window.innerWidth - width - 8)}px`;
  tip.style.top = `${Math.max(8, y - height - 12)}px`;
}

export function hideTooltip() {
  tooltip().hidden = true;
}

function bindTooltip(node, title, rows) {
  node.setAttribute("tabindex", "0");
  const show = (e) => showTooltip(e, title, rows());
  node.addEventListener("pointermove", show);
  node.addEventListener("focus", show);
  node.addEventListener("pointerleave", hideTooltip);
  node.addEventListener("blur", hideTooltip);
}

// --- tables (the always-available view of every chart) -------------------

export function renderTable(container, columns, rows) {
  const table = el("table");
  const head = el("tr");
  for (const c of columns) head.append(el("th", c.numeric ? { class: "num" } : {}, c.label));
  table.append(el("thead"), el("tbody"));
  table.tHead.append(head);
  for (const r of rows) {
    const tr = el("tr");
    for (const c of columns) {
      const v = c.value(r);
      tr.append(el("td", c.numeric ? { class: "num" } : {}, c.numeric ? formatNumber(v) : v ?? ""));
    }
    table.tBodies[0].append(tr);
  }
  container.replaceChildren(table);
}

// --- horizontal bars (single series) ----------------------------------------

export function renderHBars(container, rows, { label, value, unit = "events" }) {
  const max = Math.max(1, ...rows.map(value));
  const grid = el("div", { class: "hbars" });
  for (const r of rows) {
    const name = label(r);
    const v = value(r);
    const bar = el("div", {
      class: "bar",
      style: `width:${(v / max) * 100}%`,
      "aria-label": `${name}: ${formatNumber(v)} ${unit}`,
    });
    bindTooltip(bar, name, () => [{ label: unit, value: formatNumber(v) }]);
    const track = el("div", { class: "track" });
    track.append(bar, el("span", { class: "val" }, formatNumber(v)));
    grid.append(el("div", { class: "name" }, name), track);
  }
  container.replaceChildren(grid);
}

// --- stacked columns (few series, fixed order) ------------------------------

function niceMax(v) {
  if (v <= 0) return 1;
  const pow = 10 ** Math.floor(Math.log10(v));
  const step = [1, 2, 2.5, 5, 10].find((s) => s * pow >= v / 4) * pow;
  return Math.ceil(v / step) * step;
}

export function renderStackedColumns(container, rows, { x, series }) {
  const width = Math.max(280, container.clientWidth);
  const height = 240;
  const m = { top: 8, right: 4, bottom: 24, left: 40 };
  const innerW = width - m.left - m.right;
  const innerH = height - m.top - m.bottom;
  const totals = rows.map((r) => series.reduce((s, sr) => s + (r[sr.key] || 0), 0));
  const yMax = niceMax(Math.max(...totals, 1));
  const y = (v) => innerH - (v / yMax) * innerH;
  const band = innerW / Math.max(1, rows.length);
  const barW = Math.min(24, band * 0.7);
  const GAP = 2; // surface gap between stacked segments
  const R = 4;   // rounded data end

  const svg = el("svg:svg", { width, height, role: "img", "aria-label": "Stacked column chart; see the table for values" });
  const g = el("svg:g", { transform: `translate(${m.left},${m.top})` });
  svg.append(g);

  // gridlines + y ticks
  const axis = el("svg:g", { class: "axis" });
  for (let i = 0; i <= 4; i++) {
    const v = (yMax / 4) * i;
    const yy = y(v);
    if (i > 0) g.append(el("svg:line", { class: "gridline", x1: 0, x2: innerW, y1: yy, y2: yy }));
    axis.append(el("svg:text", { x: -8, y: yy, "text-anchor": "end", "dominant-baseline": "middle" }, formatNumber(v)));
  }
  g.append(el("svg:line", { class: "baseline", x1: 0, x2: innerW, y1: innerH, y2: innerH }));

  // x labels: thin out when crowded
  const every = Math.ceil(rows.length / Math.max(1, Math.floor(innerW / 44)));
  rows.forEach((r, i) => {
    if (i % every === 0 || i === rows.length - 1) {
      axis.append(el("svg:text", { x: band * i + band / 2, y: innerH + 16, "text-anchor": "middle" }, r[x]));
    }
  });
  g.append(axis);

  rows.forEach((r, i) => {
    const cx = band * i + band / 2;
    const group = el("svg:g", { class: "col-group" });
    let acc = 0;
    const visible = series.filter((s) => (r[s.key] || 0) > 0);
    visible.forEach((s, j) => {
      const v = r[s.key];
      const y0 = y(acc), y1 = y(acc + v);
      acc += v;
      const isTop = j === visible.length - 1;
      // leave the surface gap above every segment except the top one
      const top = y1 + (isTop ? 0 : GAP / 2);
      const bottom = y0 - (j === 0 ? 0 : GAP / 2);
      const h = Math.max(0, bottom - top);
      if (h <= 0) return;
      const left = cx - barW / 2;
      const r4 = isTop ? Math.min(R, h, barW / 2) : 0;
      const d = `M${left},${bottom}V${top + r4}Q${left},${top} ${left + r4},${top}H${left + barW - r4}Q${left + barW},${top} ${left + barW},${top + r4}V${bottom}Z`;
      group.append(el("svg:path", { class: "seg", d, fill: `var(${s.color})` }));
    });
    // hit target: the whole band, taller than the marks
    const hit = el("svg:rect", {
      class: "hit", x: band * i, y: 0, width: band, height: innerH,
      "aria-label": `${r[x]}: ` + series.map((s) => `${s.label} ${formatNumber(r[s.key] || 0)}`).join(", "),
    });
    const styles = getComputedStyle(container);
    bindTooltip(hit, `${r[x]} · ${formatNumber(totals[i])} total`, () =>
      series.map((s) => ({ label: s.label, value: formatNumber(r[s.key] || 0), color: styles.getPropertyValue(s.color) }))
    );
    group.append(hit);
    g.append(group);
  });

  container.replaceChildren(svg);
}

export function renderLegend(container, series) {
  container.replaceChildren(
    ...series.map((s) => {
      const key = el("span", { class: "key" });
      key.append(el("span", { class: "swatch", style: `background:var(${s.color})` }), document.createTextNode(s.label));
      return key;
    })
  );
}

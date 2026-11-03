// Small, dependency-free chart helpers. All text goes in via textContent.

const SVG_NS = "http://www.w3.org/2000/svg";
const fmt = new Intl.NumberFormat("en-US");
export const formatNumber = (n) => fmt.format(n ?? 0);

function el(tag, attrs = {}, text) {
  const node = tag.startsWith("svg:") ? document.createElementNS(SVG_NS, tag.slice(4)) : document.createElement(tag);
  // style goes through the CSSOM, which a CSP without 'unsafe-inline' still allows.
  for (const [k, v] of Object.entries(attrs)) k === "style" ? (node.style.cssText = v) : node.setAttribute(k, v);
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
      const text = c.numeric ? formatNumber(v) : v ?? "";
      const td = el("td", c.numeric ? { class: "num" } : {});
      const href = c.href?.(r);
      if (href) td.append(el("a", { href }, text));
      else td.textContent = text;
      tr.append(td);
    }
    table.tBodies[0].append(tr);
  }
  container.replaceChildren(table);
}

// --- horizontal bars (single series) ----------------------------------------

export function renderHBars(container, rows, { label, value, unit = "events", href }) {
  const max = Math.max(1, ...rows.map(value));
  const grid = el("div", { class: "hbars" });
  for (const r of rows) {
    const name = label(r);
    const v = value(r);
    const link = href?.(r);
    // With an href, the name and the bar both link (e.g. to search, pre-filtered).
    const bar = el(link ? "a" : "div", {
      class: "bar",
      style: `width:${(v / max) * 100}%`,
      "aria-label": `${name}: ${formatNumber(v)} ${unit}`,
      ...(link ? { href: link } : {}),
    });
    bindTooltip(bar, name, () => [{ label: unit, value: formatNumber(v) }]);
    const track = el("div", { class: "track" });
    track.append(bar, el("span", { class: "val" }, formatNumber(v)));
    const nameCell = el("div", { class: "name" });
    if (link) nameCell.append(el("a", { href: link, tabindex: "-1" }, name));
    else nameCell.textContent = name;
    grid.append(nameCell, track);
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

// --- lines (a few series on one axis, with a crosshair) -------------------------

/**
 * rows: [{[x]: label, [series.key]: number|null, ...}]
 * series: [{key, label, color: "--css-var"}]
 * hollow(row): optional; true draws that point hollow (e.g. a partial year)
 * reference: optional y value drawn as a labelled hairline (e.g. 100 for an index)
 */
export function renderLines(container, rows, { x, series, hollow = () => false, reference, referenceLabel }) {
  const width = Math.max(280, container.clientWidth);
  const height = 260;
  const m = { top: 12, right: 92, bottom: 24, left: 40 };
  const innerW = width - m.left - m.right;
  const innerH = height - m.top - m.bottom;
  const values = rows.flatMap((r) => series.map((s) => r[s.key])).filter((v) => v != null);
  const yMax = niceMax(Math.max(...values, reference ?? 0, 1));
  const y = (v) => innerH - (v / yMax) * innerH;
  const step = rows.length > 1 ? innerW / (rows.length - 1) : 0;
  const xPos = (i) => (rows.length > 1 ? i * step : innerW / 2);
  const styles = getComputedStyle(container);

  const svg = el("svg:svg", { width, height, role: "img", "aria-label": "Line chart; see the table for values" });
  const g = el("svg:g", { transform: `translate(${m.left},${m.top})` });
  svg.append(g);

  const axis = el("svg:g", { class: "axis" });
  for (let i = 0; i <= 4; i++) {
    const v = (yMax / 4) * i;
    if (i > 0) g.append(el("svg:line", { class: "gridline", x1: 0, x2: innerW, y1: y(v), y2: y(v) }));
    axis.append(el("svg:text", { x: -8, y: y(v), "text-anchor": "end", "dominant-baseline": "middle" }, formatNumber(v)));
  }
  g.append(el("svg:line", { class: "baseline", x1: 0, x2: innerW, y1: innerH, y2: innerH }));
  if (reference != null) {
    g.append(el("svg:line", { class: "reference", x1: 0, x2: innerW, y1: y(reference), y2: y(reference) }));
    if (referenceLabel) {
      // Left end, just above the line, so it never meets the series end labels on the right.
      axis.append(el("svg:text", { x: 4, y: y(reference) - 6, class: "reference-label" }, referenceLabel));
    }
  }
  const every = Math.ceil(rows.length / Math.max(1, Math.floor(innerW / 44)));
  rows.forEach((r, i) => {
    if (i % every === 0 || i === rows.length - 1) {
      axis.append(el("svg:text", { x: xPos(i), y: innerH + 16, "text-anchor": "middle" }, r[x]));
    }
  });
  g.append(axis);

  const ends = [];
  for (const s of series) {
    const pts = rows.map((r, i) => (r[s.key] == null ? null : [xPos(i), y(r[s.key]), r])).filter(Boolean);
    if (!pts.length) continue;
    const d = pts.map(([px, py], i) => `${i ? "L" : "M"}${px},${py}`).join("");
    g.append(el("svg:path", { class: "line", d, stroke: `var(${s.color})` }));
    for (const [px, py, r] of pts) {
      const open = hollow(r);
      g.append(el("svg:circle", {
        class: `dot${open ? " hollow" : ""}`, cx: px, cy: py, r: 4,
        fill: open ? "var(--surface-1)" : `var(${s.color})`, stroke: open ? `var(${s.color})` : "var(--surface-1)",
      }));
    }
    const [lx, ly] = pts.at(-1);
    ends.push({ s, lx, ly });
  }
  // End labels only when they don't collide; otherwise the legend carries identity.
  ends.sort((a, b) => a.ly - b.ly);
  if (ends.every((e, i) => i === 0 || e.ly - ends[i - 1].ly >= 14)) {
    for (const { s, lx, ly } of ends) {
      axis.append(el("svg:text", { x: lx + 8, y: ly, "dominant-baseline": "middle", class: "end-label" }, s.label));
    }
  }

  // Crosshair: a hairline that snaps to the nearest year; the tooltip lists every series.
  const cross = el("svg:line", { class: "crosshair", x1: 0, x2: 0, y1: 0, y2: innerH, visibility: "hidden" });
  g.append(cross);
  const overlay = el("svg:rect", {
    class: "hit", x: -step / 2, y: 0, width: innerW + step, height: innerH, tabindex: 0,
    "aria-label": "Chart values by year; use the arrow keys",
  });
  let current = rows.length - 1;
  const show = (i, event) => {
    current = Math.max(0, Math.min(rows.length - 1, i));
    const r = rows[current];
    cross.setAttribute("x1", xPos(current));
    cross.setAttribute("x2", xPos(current));
    cross.setAttribute("visibility", "visible");
    showTooltip(event, `${r[x]}${hollow(r) ? " (partial year)" : ""}`, series.map((s) => ({
      label: s.label, value: r[s.key] == null ? "—" : formatNumber(Math.round(r[s.key])), color: styles.getPropertyValue(s.color),
    })));
  };
  const hide = () => { cross.setAttribute("visibility", "hidden"); hideTooltip(); };
  overlay.addEventListener("pointermove", (e) => {
    const box = overlay.getBoundingClientRect();
    const px = ((e.clientX - box.left) / box.width) * (innerW + step) - step / 2;
    show(step ? Math.round(px / step) : 0, e);
  });
  overlay.addEventListener("focus", (e) => show(current, e));
  overlay.addEventListener("keydown", (e) => {
    if (e.key === "ArrowLeft" || e.key === "ArrowRight") {
      e.preventDefault();
      show(current + (e.key === "ArrowRight" ? 1 : -1), { type: "focus", currentTarget: overlay });
    }
  });
  overlay.addEventListener("pointerleave", hide);
  overlay.addEventListener("blur", hide);
  g.append(overlay);

  container.replaceChildren(svg);
}

export function renderLineLegend(container, series) {
  container.replaceChildren(
    ...series.map((s) => {
      const key = el("span", { class: "key" });
      key.append(el("span", { class: "linekey", style: `background:var(${s.color})` }), document.createTextNode(s.label));
      return key;
    })
  );
}

// Home page: the "are recalls rising?" story, national only. Every section
// links somewhere deeper (state page, search, event pages).
import {
  formatNumber, renderHBars, renderLegend, renderLineLegend, renderLines, renderStackedColumns, renderTable,
} from "./charts.js";
import { label } from "./labels.js";
import { renderMapLegend, renderTileMap } from "./map.js";
import { showPlaceholders } from "./loading.js";

const clearPlaceholders = showPlaceholders();

const $ = (id) => document.getElementById(id);
const pct = (share) => `${Math.round(share * 100)}%`;
// "The New York Times" reads badly mid-sentence ("all The New York Times articles").
const outlet = (name) => name.replace(/^The /, "");
const CLASS_SERIES = [
  { key: "class_1", label: "Class I", color: "--class-1" },
  { key: "class_2", label: "Class II", color: "--class-2" },
  { key: "class_3", label: "Class III", color: "--class-3" },
  { key: "unclassified", label: "No class (incl. USDA alerts)", color: "--unclassified" },
];
// Fixed color per series: FDA blue, news orange, USDA aqua.
const TREND_SERIES = [
  { key: "fda_index", label: "FDA recalls", color: "--series-1" },
  { key: "usda_index", label: "USDA recalls", color: "--series-3" },
  { key: "media_index", label: "News coverage", color: "--series-2" },
];

async function getJSON(path) {
  const res = await fetch(`api/${path}.json`);
  if (!res.ok) throw new Error(`${path}: ${res.status}`);
  return res.json();
}

function node(tag, attrs = {}, text) {
  const n = document.createElement(tag);
  for (const [k, v] of Object.entries(attrs)) n.setAttribute(k, v);
  if (text !== undefined && text !== null) n.textContent = text;
  return n;
}

// --- the answer ---------------------------------------------------------------

function change(from, to) {
  const d = Math.round(((to - from) / from) * 100);
  return d === 0 ? "about the same as" : `${Math.abs(d)}% ${d > 0 ? "above" : "below"}`;
}

function agencySentence(t, key, name) {
  const full = t.years.filter((y) => !y.partial && y[`${key}_events`] != null);
  const latest = full.at(-1);
  const base = full.find((y) => y.year === t.base_year);
  const peak = full.reduce((a, b) => (b[`${key}_events`] > a[`${key}_events`] ? b : a));
  return {
    latest, base, peak,
    text: `${name} reported ${formatNumber(latest[`${key}_events`])} recall events in ${latest.year}, ` +
      `${change(peak[`${key}_events`], latest[`${key}_events`])} its ${peak.year} peak of ${formatNumber(peak[`${key}_events`])} ` +
      `and ${change(base[`${key}_events`], latest[`${key}_events`])} ${base.year}.`,
  };
}

function renderAnswer(t) {
  const fda = agencySentence(t, "fda", "FDA, which covers most foods,");
  const usda = agencySentence(t, "usda", "USDA, which covers meat, poultry and egg products,");
  // The one-line verdict comes from the data too: all recalls in the latest full
  // year vs the base year, per month.
  const combined = (y) => (y.fda_per_month ?? 0) + (y.usda_per_month ?? 0);
  const ratio = combined(fda.latest) / combined(fda.base);
  const verdict = ratio > 1.05 ? "Yes, by the official counts."
    : ratio < 0.95 ? "Not by the official counts."
    : "Not much, by the official counts.";
  let text = `${verdict} ${fda.text} ${usda.text}`;
  const latestMedia = t.years.filter((y) => !y.partial && y.media_index != null).at(-1);
  if (t.media_source && latestMedia) {
    text += ` Over the same years, ${outlet(t.media_source)} coverage of food safety was ` +
      `${change(100, latestMedia.media_index)} its ${t.base_year} level.`;
  }
  $("answer").textContent = text;

  const latest = fda.latest;
  const tiles = [
    [`Recall events in ${latest.year}`, formatNumber(latest.events),
     `FDA ${formatNumber(latest.fda_events)} · USDA ${formatNumber(latest.usda_events ?? 0)}`],
    ["Most serious (Class I)", pct(latest.fda_class_1_share),
     `of ${latest.year} FDA recalls, vs ${pct(fda.base.fda_class_1_share)} in ${fda.base.year}`],
    ["Ongoing now", formatNumber(t.ongoing_now.fda + t.ongoing_now.usda),
     `recall events not yet closed (FDA ${formatNumber(t.ongoing_now.fda)} · USDA ${formatNumber(t.ongoing_now.usda)})`],
  ];
  $("hero-tiles").replaceChildren(...tiles.map(([name, value, sub]) => {
    const tile = node("div", { class: "tile" });
    tile.append(node("div", { class: "label" }, name), node("div", { class: "value" }, value), node("div", { class: "sub" }, sub));
    return tile;
  }));
}

// --- recalls vs news coverage ------------------------------------------------------

function trendRows(t) {
  return t.years.filter((y) => y.year >= t.base_year);
}

function renderTrend(t) {
  const hasMedia = t.years.some((y) => y.media_index != null);
  const series = hasMedia ? TREND_SERIES : TREND_SERIES.filter((s) => s.key !== "media_index");
  const rows = trendRows(t);
  const partial = rows.filter((y) => y.partial).map((y) => `${y.year} runs through ${t.last_report}`);
  $("trend-note").textContent =
    `Each line is indexed to ${t.base_year} = 100 (the first year with both agencies' data), so they can share one scale. ` +
    "Recalls are counted per month so partial years compare fairly" +
    (hasMedia ? `; news coverage is the share of all ${outlet(t.media_source)} articles the paper tagged as food contamination or food recalls.` : ".") +
    (partial.length ? ` Hollow points are partial years (${partial.join("; ")}).` : "");
  $("media-missing").hidden = hasMedia;
  $("media-credit").textContent = hasMedia ? `News coverage data provided by ${t.media_source}.` : "";
  renderLineLegend($("trend-legend"), series);
  renderLines($("trend-chart"), rows, {
    x: "year", series, hollow: (r) => r.partial, reference: 100, // labelled in the note: every line starts at 100
  });
  renderTable($("trend-table"), [
    { label: "Year", value: (r) => `${r.year}${r.partial ? " (partial)" : ""}` },
    { label: "FDA recalls", value: (r) => r.fda_events ?? 0, numeric: true },
    { label: "FDA index", value: (r) => r.fda_index ?? "—" },
    { label: "USDA recalls", value: (r) => r.usda_events ?? 0, numeric: true },
    { label: "USDA index", value: (r) => r.usda_index ?? "—" },
    ...(hasMedia ? [
      { label: "News articles", value: (r) => r.media_articles ?? 0, numeric: true },
      { label: "News index", value: (r) => r.media_index ?? "—" },
    ] : []),
  ], rows);
}

// --- everything else -------------------------------------------------------------------

function renderYears(d, t) {
  renderLegend($("year-legend"), CLASS_SERIES);
  $("year-note").textContent = "FDA and USDA recall events by the most serious class among each event's products. " +
    "Class I is the most serious; USDA public health alerts have no class. " +
    `FDA data starts ${t.first_report.fda} and USDA ${t.first_report.usda}; ${t.last_report.slice(0, 4)} runs through ${t.last_report}.`;
  renderStackedColumns($("year-chart"), d.by_year, { x: "year", series: CLASS_SERIES });
  renderTable($("year-table"), [
    { label: "Year", value: (r) => r.year },
    ...CLASS_SERIES.map((s) => ({ label: s.label, value: (r) => r[s.key], numeric: true })),
  ], d.by_year);
}

function renderMap(states) {
  const { bounds } = renderTileMap($("map"), {
    states, view: "impacting", selected: null,
    onSelect: (code) => { location.href = `state.html#${encodeURIComponent(code)}`; },
  });
  renderMapLegend($("map-legend"), bounds);
}

function renderBreakdowns(d) {
  const top = (rows) => rows.filter((r) => r.key !== "other" && r.key !== "unknown").slice(0, 8);
  renderHBars($("reason-chart"), top(d.by_reason), {
    label: (r) => label(r.key), value: (r) => r.events, href: (r) => `search.html?reason=${encodeURIComponent(r.key)}`,
  });
  renderHBars($("product-chart"), top(d.by_product), {
    label: (r) => label(r.key), value: (r) => r.events, href: (r) => `search.html?category=${encodeURIComponent(r.key)}`,
  });
}

function reach(r) {
  if (r.is_nationwide) return "Nationwide";
  return r.state_count ? `${r.state_count} state${r.state_count === 1 ? "" : "s"}` : "Reach not stated";
}

function renderLatest(d) {
  $("latest").replaceChildren(...d.recent.slice(0, 6).map((r) => {
    const card = node("article", { class: "recall-card" });
    const title = node("h3");
    title.append(node("a", { href: `event.html?id=${encodeURIComponent(r.event_id)}` }, r.recalling_firm));
    const meta = [r.report_date, r.most_severe_class ?? "Not yet classified", r.size ? `Size ${r.size}` : null, reach(r)]
      .filter(Boolean).join(" · ");
    const reason = (r.reason ?? "").length > 140 ? `${r.reason.slice(0, 137)}…` : r.reason;
    const tags = node("div", { class: "chips" });
    tags.append(node("span", { class: "agency-tag" }, r.agency), node("span", { class: "chip" }, label(r.reason_category)));
    if (r.recall_type === "public_health_alert") tags.append(node("span", { class: "chip" }, "Public health alert"));
    card.append(
      tags,
      title,
      node("p", { class: "reason" }, reason),
      node("p", { class: "recall-meta small" }, meta),
    );
    return card;
  }));
}

async function init() {
  const [trends, dashboard, states] = await Promise.all([
    getJSON("trends"), getJSON("dashboard/all/impacting/US"), getJSON("states/all").then((d) => d.states),
  ]);
  renderAnswer(trends);
  renderTrend(trends);
  renderYears(dashboard, trends);
  renderMap(states);
  renderBreakdowns(dashboard);
  renderLatest(dashboard);

  let lastWidth = $("content").clientWidth;
  new ResizeObserver(() => {
    const width = $("content").clientWidth;
    if (width === lastWidth) return;
    lastWidth = width;
    renderTrend(trends);
    renderStackedColumns($("year-chart"), dashboard.by_year, { x: "year", series: CLASS_SERIES });
    renderMap(states);
  }).observe($("content"));
}

init().catch((err) => {
  $("answer").textContent = `Couldn't load data: ${err.message}`;
}).finally(clearPlaceholders);

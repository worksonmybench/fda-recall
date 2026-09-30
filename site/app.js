// Fetches api/*.json - live from the dev server, or pre-built static files
// when deployed. Paths are relative so the site works under any base URL.
import {
  formatNumber, renderHBars, renderLegend, renderStackedColumns, renderTable,
} from "./charts.js";
import { MAP_CODES, renderMapLegend, renderTileMap } from "./map.js";

const LABELS = {
  // recall reasons
  pathogen: "Pathogen", undeclared_allergen: "Undeclared allergen", foreign_material: "Foreign material",
  processing: "Processing / spoilage", labeling: "Other labeling", chemical: "Chemical contaminant",
  sanitation: "Sanitation / GMP", temperature_abuse: "Temperature abuse", unapproved_drug: "Unapproved drug",
  supplier_recall: "Supplier recall", regulatory_order: "Court order", other: "Other / unclear",
  // product categories
  produce: "Produce", bakery: "Bakery", prepared_foods: "Prepared foods", dairy: "Dairy",
  sauces_condiments: "Sauces & condiments", dietary_supplements: "Dietary supplements",
  grains_pasta_cereal: "Grains, pasta & cereal", spices_seasonings: "Spices & seasonings",
  nuts_seeds: "Nuts & seeds", seafood: "Seafood", frozen_dessert: "Ice cream & frozen desserts",
  candy_chocolate: "Candy & chocolate", snacks: "Snacks", beverages: "Beverages", meat_poultry: "Meat & poultry",
  infant_formula_baby_food: "Infant formula & baby food", eggs: "Eggs", unknown: "Unknown",
};
const label = (key) => LABELS[key] ?? key;

const CLASS_SERIES = [
  { key: "class_1", label: "Class I", color: "--class-1" },
  { key: "class_2", label: "Class II", color: "--class-2" },
  { key: "class_3", label: "Class III", color: "--class-3" },
];

const VIEW_TEXT = {
  impacting: {
    heading: (name) => `Recalls impacting ${name}`,
    mapNote: "Recall events not yet closed by FDA whose distribution reached each state. Nationwide recalls (including online sales) count in every state. Select a state to see its recalls.",
  },
  originating: {
    heading: (name) => `Recalls originating from ${name}`,
    mapNote: "Recall events not yet closed by FDA, by the state where the recalling firm is located. Firms outside the US aren't shown. Select a state to see its recalls.",
  },
};

const $ = (id) => document.getElementById(id);
const state = { view: "impacting", scope: "US", meta: null, states: null, dashboard: null };

async function getJSON(path) {
  const res = await fetch(`api/${path}.json`);
  if (!res.ok) throw new Error(`${path}: ${res.status}`);
  return res.json();
}

const scopeName = (code) => state.meta.scopes.find((s) => s.code === code)?.name ?? code;

// --- URL <-> state (#originating/TX, #TX, or nothing for the default) ---------

function readHash() {
  const parts = decodeURIComponent(location.hash.slice(1)).split("/").filter(Boolean);
  const view = parts.find((p) => VIEW_TEXT[p]) ?? "impacting";
  const scope = parts.find((p) => state.meta.scopes.some((s) => s.code === p)) ?? "US";
  return { view, scope };
}

function writeHash() {
  const parts = [];
  if (state.view !== "impacting") parts.push(state.view);
  if (state.scope !== "US") parts.push(state.scope);
  history.replaceState(null, "", parts.length ? `#${parts.join("/")}` : location.pathname + location.search);
}

// --- rendering ---------------------------------------------------------------

function renderTiles(t) {
  const tiles = [
    ["Recall events", formatNumber(t.events), `${t.first_report ?? ""} to ${t.last_report ?? ""}`],
    ["Products recalled", formatNumber(t.products), "one recall event can cover many products"],
    ["Still ongoing", formatNumber(t.ongoing_events), "events with products not yet closed"],
    ["Illnesses reported", formatNumber(t.illness_events), "events whose reason mentions actual illnesses"],
  ];
  $("tiles").replaceChildren(
    ...tiles.map(([name, value, sub]) => {
      const tile = document.createElement("div");
      tile.className = "tile";
      for (const [cls, text] of [["label", name], ["value", value], ["sub", sub]]) {
        const d = document.createElement("div");
        d.className = cls;
        d.textContent = text;
        tile.append(d);
      }
      return tile;
    })
  );
}

function renderMap() {
  const { bounds } = renderTileMap($("map"), {
    states: state.states, view: state.view, selected: state.scope, onSelect: selectScope,
  });
  renderMapLegend($("map-legend"), bounds);
  $("map-note").textContent = VIEW_TEXT[state.view].mapNote;
  const rows = MAP_CODES.filter((c) => state.states[c]).map((c) => ({ code: c, ...state.states[c] }));
  rows.sort((a, b) => b[state.view].ongoing - a[state.view].ongoing || a.name.localeCompare(b.name));
  renderTable($("map-table"), [
    { label: "State", value: (r) => r.name },
    { label: "Ongoing", value: (r) => r[state.view].ongoing, numeric: true },
    { label: "Since 2012", value: (r) => r[state.view].events, numeric: true },
    { label: "Class I", value: (r) => r[state.view].class_1, numeric: true },
    { label: "Illnesses reported", value: (r) => r[state.view].illness, numeric: true },
  ], rows);
}

function renderCharts() {
  renderStackedColumns($("year-chart"), state.dashboard.by_year, { x: "year", series: CLASS_SERIES });
}

function renderDashboard(d) {
  state.dashboard = d;
  $("scope-heading").textContent = d.scope === "US" ? "All US recalls" : VIEW_TEXT[d.view].heading(scopeName(d.scope));
  renderTiles(d.totals);
  renderLegend($("year-legend"), CLASS_SERIES);
  const lastYear = d.by_year.at(-1)?.year;
  $("year-note").textContent = "By the most serious class among the event's products. Class I is the most serious."
    + (lastYear && d.totals.last_report && !d.totals.last_report.endsWith("12-31") ? ` ${lastYear} is partial, through ${d.totals.last_report}.` : "");
  renderCharts();
  renderTable($("year-table"), [
    { label: "Year", value: (r) => r.year },
    ...CLASS_SERIES.map((s) => ({ label: s.label, value: (r) => r[s.key], numeric: true })),
  ], d.by_year);

  const byKey = { label: (r) => label(r.key), value: (r) => r.events };
  renderHBars($("reason-chart"), d.by_reason, byKey);
  renderTable($("reason-table"), [{ label: "Reason", value: byKey.label }, { label: "Events", value: byKey.value, numeric: true }], d.by_reason);
  renderHBars($("product-chart"), d.by_product, byKey);
  renderTable($("product-table"), [{ label: "Kind of food", value: byKey.label }, { label: "Events", value: byKey.value, numeric: true }], d.by_product);
  const sizeRows = d.by_size.map((r) => ({ ...r, key: r.key === "unknown" ? "Unknown" : r.key }));
  renderHBars($("size-chart"), sizeRows, { label: (r) => r.key, value: (r) => r.events });
  renderTable($("size-table"), [{ label: "Size", value: (r) => r.key }, { label: "Events", value: (r) => r.events, numeric: true }], sizeRows);

  renderTable($("recent-table"), [
    { label: "Reported", value: (r) => r.report_date },
    { label: "Firm", value: (r) => r.recalling_firm },
    { label: "Reason", value: (r) => label(r.reason_category) },
    { label: "Class", value: (r) => r.most_severe_class ?? "Not yet classified" },
    { label: "Size", value: (r) => r.size ?? "Unknown" },
    { label: "Reach", value: (r) => (r.is_nationwide ? "Nationwide" : r.state_count ? `${r.state_count} state${r.state_count === 1 ? "" : "s"}` : "Not stated") },
  ], d.recent);
}

// --- actions -----------------------------------------------------------------

async function loadDashboard() {
  const main = $("content");
  main.classList.add("loading"); // keep the previous render visible while fetching
  try {
    renderDashboard(await getJSON(`dashboard/${state.view}/${state.scope}`));
  } finally {
    main.classList.remove("loading");
  }
}

function syncControls() {
  $("scope").value = state.scope;
  for (const input of document.querySelectorAll('input[name="view"]')) input.checked = input.value === state.view;
}

function selectScope(scope) {
  state.scope = scope;
  syncControls();
  writeHash();
  renderMap();
  loadDashboard();
  if (scope !== "US") $("scope-heading").scrollIntoView({ behavior: "smooth", block: "start" });
}

function selectView(view) {
  state.view = view;
  syncControls();
  writeHash();
  renderMap();
  loadDashboard();
}

async function init() {
  [state.meta, state.states] = await Promise.all([getJSON("meta"), getJSON("states").then((d) => d.states)]);
  if (state.meta.data_last_updated) $("data-updated").textContent = `Data as of ${state.meta.data_last_updated}.`;

  const select = $("scope");
  for (const s of state.meta.scopes) {
    const opt = document.createElement("option");
    opt.value = s.code;
    opt.textContent = s.code === "US" ? "All US" : `${s.name} (${s.code})`;
    select.append(opt);
  }
  Object.assign(state, readHash());
  syncControls();

  select.addEventListener("change", () => selectScope(select.value));
  for (const input of document.querySelectorAll('input[name="view"]')) {
    input.addEventListener("change", () => input.checked && selectView(input.value));
  }
  window.addEventListener("hashchange", () => {
    const next = readHash();
    if (next.view !== state.view || next.scope !== state.scope) {
      Object.assign(state, next);
      syncControls();
      renderMap();
      loadDashboard();
    }
  });

  renderMap();
  await loadDashboard();
  let lastWidth = $("content").clientWidth;
  new ResizeObserver(() => {
    const width = $("content").clientWidth;
    if (width === lastWidth) return; // height changes come from our own renders
    lastWidth = width;
    renderMap();
    if (state.dashboard) renderCharts();
  }).observe($("content"));
}

init().catch((err) => {
  $("content").textContent = `Couldn't load data: ${err.message}`;
});

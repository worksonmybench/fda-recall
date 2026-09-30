// Client-side recall search: loads api/search_index.json once, then every
// filter, sort and page change runs in the browser. Filter state lives in the
// URL query string so searches can be shared and bookmarked.
import { formatNumber } from "./charts.js";
import { LABELS, label } from "./labels.js";

const PAGE_SIZE = 50;
const SIZES = ["XS", "S", "M", "L", "XL", "XXL", "unknown"];
// The 50 states + DC (what "nationwide" covers).
const NATIONWIDE_STATES = new Set(
  "AL AK AZ AR CA CO CT DE FL GA HI ID IL IN IA KS KY LA ME MD MA MI MN MS MO MT NE NV NH NJ NM NY NC ND OH OK OR PA RI SC SD TN TX UT VT VA WA WV WI WY DC".split(" ")
);
const REASON_KEYS = ["pathogen", "undeclared_allergen", "foreign_material", "chemical", "unapproved_drug", "processing",
  "temperature_abuse", "sanitation", "labeling", "regulatory_order", "supplier_recall", "other"];

const $ = (id) => document.getElementById(id);
const form = () => $("filters");
let events = [];
let lastReported = null;
let page = 1;

async function getJSON(path) {
  const res = await fetch(`api/${path}.json`);
  if (!res.ok) throw new Error(`${path}: ${res.status}`);
  return res.json();
}

// --- index ---------------------------------------------------------------

function loadIndex({ columns, rows }) {
  const idx = Object.fromEntries(columns.map((c, i) => [c, i]));
  return rows.map((r) => {
    const e = Object.fromEntries(columns.map((c) => [c, r[idx[c]]]));
    e.states = new Set(e.states.match(/../g) ?? []);
    e.size = e.size ?? "unknown";
    e.haystack = `${e.firm} ${e.snippet ?? ""}`.toLowerCase();
    return e;
  });
}

// --- filters <-> URL ---------------------------------------------------------

function readFilters() {
  const f = form();
  return {
    q: f.q.value.trim(),
    date: f.date.value,
    from: f.from.value,
    to: f.to.value,
    agency: f.agency.value,
    reason: f.reason.value,
    category: f.category.value,
    state: f.state.value,
    view: f.view.value,
    status: f.status.value,
    classes: [...f.querySelectorAll('input[name="class"]:checked')].map((i) => i.value),
    sizes: [...f.querySelectorAll('input[name="size"]:checked')].map((i) => i.value),
    illness: f.illness.checked,
    nationwide: f.nationwide.checked,
    sort: $("sort").value,
  };
}

function writeURL(filters) {
  const p = new URLSearchParams();
  for (const [k, v] of Object.entries(filters)) {
    if (Array.isArray(v)) v.forEach((x) => p.append(k, x));
    else if (v === true) p.set(k, "1");
    else if (v && !(k === "date" && v === "reported") && !(k === "view" && v === "impacting") && !(k === "sort" && v === "newest")) p.set(k, v);
  }
  if (page > 1) p.set("page", page);
  const qs = p.toString();
  history.replaceState(null, "", qs ? `?${qs}` : location.pathname);
}

function applyURL() {
  const p = new URLSearchParams(location.search);
  const f = form();
  for (const name of ["q", "from", "to", "agency", "reason", "category", "state", "status"]) f[name].value = p.get(name) ?? "";
  f.date.value = p.get("date") ?? "reported";
  f.view.value = p.get("view") ?? "impacting";
  $("sort").value = p.get("sort") ?? "newest";
  const classes = p.getAll("classes"), sizes = p.getAll("sizes");
  for (const i of f.querySelectorAll('input[name="class"]')) i.checked = classes.includes(i.value);
  for (const i of f.querySelectorAll('input[name="size"]')) i.checked = sizes.includes(i.value);
  f.illness.checked = p.has("illness");
  f.nationwide.checked = p.has("nationwide");
  page = Math.max(1, parseInt(p.get("page") ?? "1", 10) || 1);
}

// --- matching --------------------------------------------------------------------

function matches(e, f, terms) {
  const date = f.date === "started" ? e.started : e.reported;
  if (f.from && (!date || date < f.from)) return false;
  if (f.to && (!date || date > f.to)) return false;
  if (f.agency && e.agency !== f.agency.toUpperCase()) return false;
  if (f.reason && !e.reasons.includes(f.reason)) return false;
  if (f.category && !e.categories.includes(f.category)) return false;
  if (f.status === "open" && !e.open) return false;
  if (f.status === "closed" && e.open) return false;
  if (f.classes.length && !f.classes.includes(e.class ?? "none")) return false;
  if (f.sizes.length && !f.sizes.includes(e.size)) return false;
  if (f.illness && !e.illness) return false;
  if (f.nationwide && !e.nationwide) return false;
  if (f.state) {
    if (f.view === "originating") {
      if (e.origin !== f.state) return false;
    } else if (!e.states.has(f.state) && !(e.nationwide && NATIONWIDE_STATES.has(f.state))) {
      return false;
    }
  }
  return terms.every((t) => e.haystack.includes(t));
}

const SORTS = {
  newest: (a, b) => (b.reported ?? "").localeCompare(a.reported ?? "") || b.id.localeCompare(a.id),
  oldest: (a, b) => (a.reported ?? "").localeCompare(b.reported ?? "") || a.id.localeCompare(b.id),
  largest: (a, b) => (b.units ?? -1) - (a.units ?? -1),
  products: (a, b) => b.products - a.products,
};

// --- rendering ---------------------------------------------------------------------

function node(tag, attrs = {}, text) {
  const n = document.createElement(tag);
  for (const [k, v] of Object.entries(attrs)) n.setAttribute(k, v);
  if (text !== undefined && text !== null) n.textContent = text;
  return n;
}

function reach(e) {
  if (e.nationwide) return "Nationwide";
  const n = e.states.size;
  return n ? `${n} state${n === 1 ? "" : "s"}` : "Not stated";
}

function renderResults(results) {
  const f = readFilters();
  const pages = Math.max(1, Math.ceil(results.length / PAGE_SIZE));
  page = Math.min(page, pages);
  const shown = results.slice((page - 1) * PAGE_SIZE, page * PAGE_SIZE);

  $("result-count").textContent = results.length
    ? `${formatNumber(results.length)} recall event${results.length === 1 ? "" : "s"}` +
      (pages > 1 ? ` · showing ${formatNumber((page - 1) * PAGE_SIZE + 1)}–${formatNumber((page - 1) * PAGE_SIZE + shown.length)}` : "")
    : "No recall events match these filters.";

  const table = node("table", { class: "results" });
  const head = node("tr");
  for (const [h, cls] of [["Reported", ""], ["Agency", ""], ["Firm and product", ""], ["Reason", ""], ["Class", ""], ["Size", ""], ["Reach", ""], ["Products", "num"]]) {
    head.append(node("th", cls ? { class: cls } : {}, h));
  }
  table.append(node("thead"), node("tbody"));
  table.tHead.append(head);
  for (const e of shown) {
    const tr = node("tr");
    const firm = node("td");
    firm.append(node("a", { href: `event.html?id=${encodeURIComponent(e.id)}` }, e.firm));
    if (e.snippet) firm.append(node("div", { class: "snippet" }, e.snippet));
    tr.append(
      node("td", { class: "nowrap" }, (f.date === "started" ? e.started : e.reported) ?? ""),
      node("td", {}, e.agency),
      firm,
      node("td", {}, e.reasons.filter((r) => r !== "other").map(label).join(", ") || label("other")),
      node("td", { class: "nowrap" }, e.class ? `Class ${e.class}` : e.type === "public_health_alert" ? "Public health alert" : "Not yet"),
      node("td", {}, e.size === "unknown" ? "Unknown" : e.size),
      node("td", { class: "nowrap" }, reach(e)),
      node("td", { class: "num" }, formatNumber(e.products)),
    );
    table.tBodies[0].append(tr);
  }
  $("results").replaceChildren(results.length ? table : node("p", { class: "muted empty" }, "Try widening the date range or removing a filter."));
  renderPager(pages);
}

function renderPager(pages) {
  const pager = $("pager");
  if (pages <= 1) return pager.replaceChildren();
  const button = (text, target, disabled, current) => {
    const b = node("button", { type: "button" }, text);
    b.disabled = disabled;
    if (current) b.setAttribute("aria-current", "page");
    b.addEventListener("click", () => { page = target; update(); $("result-count").scrollIntoView({ block: "start" }); });
    return b;
  };
  const nums = [...new Set([1, page - 1, page, page + 1, pages])].filter((n) => n >= 1 && n <= pages).sort((a, b) => a - b);
  const items = [button("‹ Previous", page - 1, page === 1)];
  nums.forEach((n, i) => {
    if (i && n - nums[i - 1] > 1) items.push(node("span", { class: "muted" }, "…"));
    items.push(button(String(n), n, false, n === page));
  });
  items.push(button("Next ›", page + 1, page === pages));
  pager.replaceChildren(...items);
}

function update() {
  const f = readFilters();
  const terms = f.q.toLowerCase().split(/\s+/).filter(Boolean);
  const results = events.filter((e) => matches(e, f, terms)).sort(SORTS[f.sort]);
  renderResults(results);
  writeURL(f);
}

// --- setup ---------------------------------------------------------------------------

function fillSelect(select, keys) {
  for (const key of keys) select.append(new Option(label(key), key));
}

function setPreset(preset) {
  const end = lastReported; // relative to the data, not today's date
  const shift = (days) => new Date(Date.parse(end) - days * 864e5).toISOString().slice(0, 10);
  const f = form();
  f.from.value = { "30d": shift(30), "12m": shift(365), ytd: `${end.slice(0, 4)}-01-01`, all: "" }[preset];
  f.to.value = preset === "all" ? "" : end;
}

async function init() {
  const [index, meta] = await Promise.all([getJSON("search_index"), getJSON("meta")]);
  events = loadIndex(index);
  lastReported = events.map((e) => e.reported).filter(Boolean).sort().at(-1);
  $("data-updated").textContent =
    `${formatNumber(events.length)} recall events, ${events.at(-1)?.reported ?? ""} to ${lastReported}. Data as of ${meta.data_last_updated}.`;

  const present = (key) => [...new Set(events.flatMap((e) => e[key]))];
  fillSelect($("reason"), REASON_KEYS.filter((k) => present("reasons").includes(k)));
  fillSelect($("category"), Object.keys(LABELS).filter((k) => present("categories").includes(k)));
  for (const s of meta.scopes.filter((s) => s.code !== "US")) $("state").append(new Option(s.name, s.code));
  $("size-checks").append(...SIZES.map((s) => {
    const l = node("label");
    l.append(node("input", { type: "checkbox", name: "size", value: s }), ` ${s === "unknown" ? "Unknown" : s}`);
    return l;
  }));

  applyURL();
  const onChange = () => { page = 1; update(); };
  form().addEventListener("input", onChange);
  form().addEventListener("change", onChange);
  form().addEventListener("submit", (e) => e.preventDefault());
  $("sort").addEventListener("change", onChange);
  $("date-presets").addEventListener("click", (e) => {
    const preset = e.target.dataset?.preset;
    if (preset) { setPreset(preset); onChange(); }
  });
  $("clear-filters").addEventListener("click", () => {
    form().reset();
    $("sort").value = "newest";
    onChange();
  });
  update();
}

init().catch((err) => {
  $("data-updated").textContent = `Couldn't load the recall index: ${err.message}`;
});

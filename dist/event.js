// Recall event details: event.html?id=<event_id>, optionally #<recall_number>
// to jump to one product. Data comes from api/event/<id>.json.
import { formatNumber, renderTable } from "./charts.js";
import { label, titleCase } from "./labels.js";
import { renderReachMap } from "./map.js";
import { showPlaceholders } from "./loading.js";

const clearPlaceholders = showPlaceholders();

const $ = (id) => document.getElementById(id);

function node(tag, attrs = {}, text) {
  const n = document.createElement(tag);
  for (const [k, v] of Object.entries(attrs)) n.setAttribute(k, v);
  if (text !== undefined && text !== null) n.textContent = text;
  return n;
}

async function getJSON(path) {
  const res = await fetch(`api/${path}.json`);
  if (!res.ok) throw new Error(res.status === 404 ? "No recall event with that ID." : `${path}: ${res.status}`);
  return res.json();
}

const plural = (n, word) => `${formatNumber(n)} ${word}${n === 1 ? "" : "s"}`;
const unique = (xs) => [...new Set(xs.filter(Boolean))];

function reachText(e) {
  if (e.is_nationwide) return e.is_online ? "Nationwide (sold online)" : "Nationwide";
  if (e.state_count) return plural(e.state_count, "state");
  return "Not stated";
}

function renderBadges(e, products) {
  const open = e.ongoing_product_count;
  const isAlert = e.recall_type === "public_health_alert";
  const badges = [
    ["Agency", e.agency === "USDA" ? "USDA (FSIS)" : "FDA"],
    [isAlert ? "Type" : "Class", isAlert ? "Public health alert" : e.most_severe_class ?? "Not yet classified"],
    ["Status", !open ? "Closed" : e.agency === "USDA" ? "Ongoing"
      : `Ongoing: ${formatNumber(open)} of ${plural(products.length, "product")} open`],
    // USDA notices give pounds; show FSIS's own wording rather than our unit estimate.
    ["Size", !e.size ? "Unknown" : e.agency === "USDA" && products[0]?.product_quantity
      ? `${e.size} · ${products[0].product_quantity}`
      : `${e.size} · about ${formatNumber(Math.round(e.est_units))} retail units`],
    ["Reach", reachText(e) + (e.is_foreign ? " + outside the US" : "")],
  ];
  if (e.illness_reported) badges.push(["Illnesses", "Reported"]);
  $("badges").replaceChildren(...badges.map(([k, v]) => {
    const b = node("div", { class: "badge" });
    b.append(node("span", { class: "badge-label" }, k), node("span", { class: "badge-value" }, v));
    return b;
  }));
}

function renderFacts(e, products) {
  const dates = (key, pick) => {
    const vals = products.map((p) => p[key]).filter(Boolean).sort();
    return vals.length ? pick(vals) : null;
  };
  const allClosed = products.every((p) => p.termination_date);
  const sources = unique(products.flatMap((p) => p.detection_sources));
  const location = [e.city, e.state, e.country !== "United States" ? e.country : null].filter(Boolean).join(", ");
  const found = sources.length ? sources.map(label).join("; ") : "Not stated";
  // FSIS notices have no classification date, initiation type or notification method,
  // and record only the year a recall closed, so USDA recalls get a shorter list.
  const facts = e.agency === "USDA" ? [
    ["Firm", e.recalling_firm],
    ["Location", location || "Not stated"],
    ["Announced by FSIS", e.report_date],
    ["Closed", e.ongoing_product_count ? "Not yet" : "Yes"],
    ["How the problem was found", found],
    ["FSIS number", products[0]?.recall_number],
  ] : [
    ["Firm", e.recalling_firm],
    ["Location", location],
    ["Recall started", e.recall_initiation_date],
    ["Classified by FDA", dates("center_classification_date", (v) => v[0])],
    ["Reported by FDA", e.report_date],
    ["Closed", allClosed ? dates("termination_date", (v) => v.at(-1)) : "Not yet"],
    ["Initiated", e.voluntary_mandated],
    ["Firm notified customers by", e.initial_firm_notification],
    ["How the problem was found", found],
    ["FDA event ID", e.event_id],
  ];
  $("facts").replaceChildren(...facts.flatMap(([k, v]) => [node("dt", {}, k), node("dd", {}, v ?? "Not stated")]));
}

function tagText(t) {
  return t.detail === "unspecified" || t.detail === "other" ? label(t.category) : `${label(t.category)}: ${titleCase(t.detail)}`;
}

function renderReasons(products) {
  // Group products by reason text; most events have exactly one.
  const groups = new Map();
  for (const p of products) {
    if (!groups.has(p.reason_for_recall)) groups.set(p.reason_for_recall, []);
    groups.get(p.reason_for_recall).push(p);
  }
  const blocks = [...groups.entries()].map(([text, ps]) => {
    const block = node("div", { class: "reason-block" });
    const chips = node("div", { class: "chips" });
    const tags = unique(ps.flatMap((p) => p.reason_tags.map(tagText)));
    for (const t of tags.length ? tags : ["Other / unclear"]) chips.append(node("span", { class: "chip" }, t));
    if (ps.some((p) => p.illness_reported)) chips.append(node("span", { class: "chip chip-strong" }, "Illnesses reported"));
    block.append(chips, node("p", { class: "raw-text" }, text));
    if (groups.size > 1) block.append(node("p", { class: "muted small" }, `Applies to ${plural(ps.length, "product")}: ${ps.map((p) => p.recall_number).join(", ")}`));
    return block;
  });
  $("reasons").replaceChildren(...blocks);
}

function renderProducts(products) {
  $("products-title").textContent = products.length === 1 ? "Product" : `Products (${formatNumber(products.length)})`;
  const cards = products.map((p) => {
    const card = node("article", { class: "product", id: p.recall_number });
    const head = node("div", { class: "product-head" });
    const anchor = node("a", { href: `#${encodeURIComponent(p.recall_number)}`, class: "recall-number" }, p.recall_number);
    head.append(anchor);
    for (const bit of [p.classification, p.status, p.product_category ? label(p.product_category) : null].filter(Boolean)) {
      head.append(node("span", { class: "muted" }, bit));
    }
    card.append(head, node("p", { class: "product-desc" }, p.product_description));
    const dl = node("dl", { class: "facts compact" });
    const add = (k, v) => v && dl.append(node("dt", {}, k), node("dd", {}, v));
    add("Quantity", p.product_quantity);
    add("UPCs", p.upcs.join(", "));
    add("Closed", p.termination_date);
    card.append(dl);
    const codes = [p.code_info, p.more_code_info].filter(Boolean).join("\n");
    if (codes) {
      const d = node("details");
      d.append(node("summary", {}, "Lot codes and dates"), node("p", { class: "raw-text" }, codes));
      card.append(d);
    }
    return card;
  });
  $("products").replaceChildren(...cards);
}

async function init() {
  const id = new URLSearchParams(location.search).get("id");
  if (!id) throw new Error("No recall event selected.");
  const [data, meta] = await Promise.all([getJSON(`event/${encodeURIComponent(id)}`), getJSON("meta")]);
  const { event: e, products } = data;
  const names = Object.fromEntries(meta.scopes.map((s) => [s.code, s.name]));

  // Unnamed-firm public health alerts: FSIS's own title makes a better heading.
  const heading = e.recalling_firm.startsWith("Firm not named") && data.notice_title ? data.notice_title : e.recalling_firm;
  document.title = `${heading} · US Food Recalls`;
  $("firm").textContent = heading;
  $("event-subtitle").textContent =
    `${e.agency} ${e.recall_type === "public_health_alert" ? "public health alert" : "recall"} · reported ${e.report_date}` +
    (e.agency === "FDA" ? ` · ${plural(products.length, "product")}` : "");
  renderBadges(e, products);
  renderFacts(e, products);

  let reach;
  if (e.is_nationwide) reach = `Distributed nationwide${e.is_online ? ", including online sales" : ""}.`;
  else if (e.state_count) reach = `Distributed to ${formatNumber(e.state_count)} ${e.state_count === 1 ? "state or territory" : "states or territories"}.`;
  else reach = "FDA's record doesn't name specific states.";
  if (e.is_foreign) reach += " Also distributed outside the US.";
  $("reach-note").textContent = reach;
  renderReachMap($("reach-map"), { states: e.states, nationwide: !!e.is_nationwide, names });
  $("distribution-text").textContent = e.distribution_pattern ?? "Not stated";

  renderReasons(products);
  renderProducts(products);

  // USDA: FSIS's own notice text, and a link to its page.
  if (data.notice) {
    $("notice-card").hidden = false;
    $("notice-text").textContent = data.notice;
    if (e.source_url) {
      const link = $("notice-link");
      link.href = e.source_url.replace(/^http:/, "https:");
      link.hidden = false;
    }
  }

  if (data.firm_history.length) {
    $("history-card").hidden = false;
    renderTable($("firm-history"), [
      { label: "Reported", value: (r) => r.report_date, href: (r) => `event.html?id=${encodeURIComponent(r.event_id)}` },
      { label: "Reason", value: (r) => label(r.reason_category) },
      { label: "Class", value: (r) => r.most_severe_class ?? "Not yet classified" },
      { label: "Size", value: (r) => r.size ?? "Unknown" },
    ], data.firm_history);
  }

  // Jump to a product if the URL names one. The cards didn't exist at page
  // load, so :target never matched them - highlight explicitly.
  const highlight = () => {
    document.querySelector(".product.highlight")?.classList.remove("highlight");
    const card = location.hash && document.getElementById(decodeURIComponent(location.hash.slice(1)));
    if (card) {
      card.classList.add("highlight");
      card.scrollIntoView({ block: "start" });
    }
  };
  highlight();
  window.addEventListener("hashchange", highlight);
}

init().catch((err) => {
  $("firm").textContent = "Recall not found";
  $("event-subtitle").textContent = err.message;
  for (const id of ["badges", "reason-card", "history-card"]) $(id).hidden = true;
  document.querySelector(".event-top").hidden = true;
  $("products").closest(".card").hidden = true;
}).finally(clearPlaceholders);

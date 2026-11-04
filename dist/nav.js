// Site nav, shared by every page: highlights the current page and runs the
// "find a recall" box (recall number, UPC or event ID -> event page).
// The lookup file behind it is only fetched when someone actually searches.

const eventUrl = (id) => `event.html?id=${encodeURIComponent(id)}`;
let lookupPromise = null;

async function getJSON(path) {
  const res = await fetch(`api/${path}.json`);
  if (!res.ok) throw new Error(`${path}: ${res.status}`);
  return res.json();
}

export async function findEvents(query) {
  lookupPromise ??= getJSON("lookup");
  const { recalls, upcs } = await lookupPromise;
  const q = query.trim().toUpperCase();
  if (recalls[q]) return [recalls[q]];
  if (new Set(Object.values(recalls)).has(q)) return [q];
  const digits = q.replace(/\D/g, "");
  if (digits.length >= 8) {
    // UPCs are stored as printed, so compare without leading zeros, then without the check digit.
    const strip = (s) => s.replace(/^0+/, "");
    for (const target of [strip(digits), strip(digits.slice(0, -1))]) {
      const hits = Object.entries(upcs).filter(([upc]) => strip(upc) === target || strip(upc.slice(0, -1)) === target);
      if (hits.length) return [...new Set(hits.flatMap(([, ids]) => ids))];
    }
  }
  return [];
}

async function runSearch(query, out) {
  if (!query.trim()) return out.replaceChildren();
  out.textContent = "Searching…";
  const ids = await findEvents(query);
  if (ids.length === 1) {
    const recall = query.trim().toUpperCase();
    location.href = eventUrl(ids[0]) + (/[A-Z]/.test(recall) ? `#${encodeURIComponent(recall)}` : "");
    return;
  }
  if (!ids.length) {
    out.textContent = "No recall found. Try a recall number like F-1234-2020, a UPC, or an FDA event ID. To search by firm or product, use Search.";
    return;
  }
  // Several events share this UPC: list them with firm and date.
  const events = await Promise.all(ids.slice(0, 20).map((id) => getJSON(`event/${id}`)));
  const list = document.createElement("ul");
  for (const { event: e } of events) {
    const li = document.createElement("li");
    const a = document.createElement("a");
    a.href = eventUrl(e.event_id);
    a.textContent = `${e.recalling_firm}, reported ${e.report_date}`;
    li.append(a);
    list.append(li);
  }
  out.replaceChildren(`${ids.length} recall events include this UPC:`, list);
}

function init() {
  // Mark the current page in the nav.
  const here = location.pathname.split("/").pop() || "index.html";
  for (const a of document.querySelectorAll(".site-nav .nav-links a")) {
    const target = a.getAttribute("href").replace(/^\.\/$/, "index.html");
    if (target === here) a.setAttribute("aria-current", "page");
  }
  const form = document.getElementById("nav-search");
  const out = document.getElementById("nav-search-results");
  if (!form || !out) return;
  form.addEventListener("submit", (e) => {
    e.preventDefault();
    runSearch(form.querySelector("input").value, out).catch((err) => { out.textContent = err.message; });
  });
}

init();

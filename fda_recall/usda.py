"""USDA FSIS recall data: normalise the Recall API feed into a committed file.

FSIS's Recall API (https://www.fsis.usda.gov/fsis/api/recall/v/1) sits behind
bot protection that rejects scripts, but answers normal browser requests.
So a browser fetches it (the dev server's /dev/usda.html page, or you
saving it by hand) and this module turns that raw feed into
sources/usda/fsis_recalls.json, which is committed to the repo.

Usage:
    python -m fda_recall.usda import PATH_TO_DOWNLOADED.json

Normalising:
- English records only (the feed also has a Spanish copy of many notices)
- the HTML summary becomes plain text
- personal media-contact names, emails and phone numbers are dropped
- one record per line, sorted, with sorted keys, so a refresh commits as a
  small, readable diff
"""

import argparse
import html
import json
import re
import sys
from datetime import datetime, timezone
from html.parser import HTMLParser
from pathlib import Path

API_URL = "https://www.fsis.usda.gov/fsis/api/recall/v/1"
DEFAULT_PATH = Path(__file__).resolve().parent.parent / "sources" / "usda" / "fsis_recalls.json"

# Fields kept from each record, without the "field_" prefix. Contact fields
# (people's names, emails, phone numbers) are deliberately left out.
KEEP = [
    "recall_number", "title", "recall_date", "year", "recall_type", "recall_classification", "risk_level",
    "recall_reason", "processing", "product_items", "states", "establishment", "related_to_outbreak",
    "active_notice", "archive_recall", "closed_year", "qty_recovered", "last_modified_date", "recall_url",
    "summary",
]


class _TextExtractor(HTMLParser):
    BLOCK = {"p", "li", "br", "div", "ul", "ol", "h1", "h2", "h3", "h4", "tr"}

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.parts = []

    def handle_starttag(self, tag, attrs):
        if tag in self.BLOCK:
            self.parts.append("\n")

    def handle_data(self, data):
        self.parts.append(data)


def html_to_text(value):
    """'<p>A&nbsp;b</p><ul><li>c</li></ul>' -> 'A b\\nc'."""
    if not value:
        return ""
    parser = _TextExtractor()
    parser.feed(value)
    text = html.unescape("".join(parser.parts)).replace("\xa0", " ")
    lines = (re.sub(r"[ \t]+", " ", line).strip() for line in text.splitlines())
    return "\n".join(line for line in lines if line)


def _clean(value):
    if isinstance(value, list):
        return [_clean(v) for v in value if str(v).strip()]
    if isinstance(value, str):
        return value.strip()
    return value


def normalize(raw):
    """Raw API feed (a list of records) -> the committed file's structure."""
    if not isinstance(raw, list) or not all(isinstance(r, dict) for r in raw):
        raise ValueError("expected the FSIS feed: a JSON list of recall records")
    if raw and "field_recall_number" not in raw[0]:
        raise ValueError(f"doesn't look like the FSIS Recall API feed (first record keys: {sorted(raw[0])[:8]})")
    records = []
    for r in raw:
        if r.get("langcode", "English") != "English":
            continue
        rec = {k: _clean(r.get(f"field_{k}")) for k in KEEP}
        rec["summary"] = html_to_text(r.get("field_summary"))
        records.append(rec)
    records.sort(key=lambda r: (r["recall_date"] or "", r["recall_number"] or "", r["title"] or ""), reverse=True)
    return {
        "source": API_URL,
        "fetched_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "record_count": len(records),
        "records": records,
    }


def dumps(data):
    """Stable, diff-friendly JSON: header fields, then one record per line."""
    head = {k: v for k, v in data.items() if k != "records"}
    lines = [json.dumps(r, sort_keys=True, ensure_ascii=False) for r in data["records"]]
    body = ",\n".join(f"  {line}" for line in lines)
    header = json.dumps(head, ensure_ascii=False)[:-1]  # drop the closing brace, records follow
    return f"{header},\n\"records\": [\n{body}\n]}}\n"


def save(raw, path=DEFAULT_PATH):
    """Normalise a raw feed and write it. Returns a summary of what changed."""
    path = Path(path)
    data = normalize(raw)
    previous = {}
    if path.exists():
        previous = {r["recall_number"]: r for r in json.loads(path.read_text(encoding="utf-8"))["records"]}
    current = {r["recall_number"]: r for r in data["records"]}
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(dumps(data), encoding="utf-8", newline="\n")
    tmp.replace(path)
    return {
        "path": str(path),
        "records": len(current),
        "new": sorted(set(current) - set(previous)),
        "changed": sorted(k for k in set(current) & set(previous) if current[k] != previous[k]),
        "removed": sorted(set(previous) - set(current)),
        "skipped_non_english": len(raw) - len(data["records"]),
    }


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="command", required=True)
    p = sub.add_parser("import", help="normalise a feed you downloaded in a browser")
    p.add_argument("file", type=Path)
    p.add_argument("--out", type=Path, default=DEFAULT_PATH)
    args = parser.parse_args(argv)
    result = save(json.loads(args.file.read_text(encoding="utf-8")), args.out)
    print(f"Wrote {result['records']} USDA recalls to {result['path']}: "
          f"{len(result['new'])} new, {len(result['changed'])} changed, {len(result['removed'])} removed")


if __name__ == "__main__":
    sys.exit(main())


# --- reading a notice (used by the clean layer) --------------------------------------
#
# FSIS notices follow a template: an opening paragraph (who, what, how much,
# why), the product list, "The problem was discovered ..." and "There have
# been no confirmed reports ...", then standard closing paragraphs that are
# the same in every notice ("Anyone concerned about an injury or illness
# should contact a healthcare provider", the complaint-system link, ...).
# The shared text rules (reasons, illness, how-it-was-found) must only see
# the parts that vary, or that boilerplate trips them on every notice.

AP_STATES = {
    "Ala.": "AL", "Ariz.": "AZ", "Ark.": "AR", "Calif.": "CA", "Cal.": "CA", "Colo.": "CO", "Conn.": "CT",
    "Del.": "DE", "Fla.": "FL", "Ga.": "GA", "Ill.": "IL", "Ind.": "IN", "Kan.": "KS", "Kans.": "KS",
    "Ky.": "KY", "La.": "LA", "Md.": "MD", "Mass.": "MA", "Mich.": "MI", "Minn.": "MN", "Miss.": "MS",
    "Mo.": "MO", "Mont.": "MT", "Neb.": "NE", "Nebr.": "NE", "Nev.": "NV", "N.H.": "NH", "N.J.": "NJ",
    "N.M.": "NM", "N.Y.": "NY", "N.C.": "NC", "N.D.": "ND", "Okla.": "OK", "Ore.": "OR", "Oreg.": "OR",
    "Pa.": "PA", "Penn.": "PA", "R.I.": "RI", "S.C.": "SC", "S.D.": "SD", "Tenn.": "TN", "Tex.": "TX",
    "Vt.": "VT", "Va.": "VA", "Wash.": "WA", "W.Va.": "WV", "W. Va.": "WV", "Wis.": "WI", "Wisc.": "WI",
    "Wyo.": "WY", "D.C.": "DC", "P.R.": "PR", "Col.": "CO", "Ida.": "ID",
}

_LEAD_PREFIX_RE = re.compile(r"^WASHINGTON,?\s+[A-Z][a-z]+\.?\s+\d{1,2},\s+\d{4}\s*[-–—]*\s*")
_TITLE_FIRM_RE = re.compile(r"^(.+?)\s+(?:Voluntarily\s+)?(?:Expands\s+)?(?:Recalls?|Is Recalling)\b")
_GENERIC_FIRM_RE = re.compile(r"(?:[A-Z][a-z.]+\s){1,3}(?:Firm|Establishment)s?")
_LEAD_FIRM_RE = re.compile(r"^(.+?),?\s+(?:(?:a|an|the)\s[^,]*?,\s*)?(?:(?:a|an)\s+[^,]+,[^,]*?\s+(?:establishment|firm|company|importer|facility)\b|is\s+recalling)")
_BY_FIRM_RE = re.compile(r"\b(?:produced|imported|packaged|distributed|sold|manufactured)\s+by\s+([A-Z][^,.;]{2,80}?)(?:,|\.|\s+(?:a|an)\s)")
CANADIAN_PROVINCES = {
    "ontario", "quebec", "québec", "british columbia", "alberta", "manitoba", "saskatchewan", "nova scotia",
    "new brunswick", "newfoundland", "prince edward island", "ont.", "que.", "b.c.", "alta.", "man.", "n.s.", "n.b.",
}
# "…, a Harvey, Ill., establishment" (older notices) or "…, located in Cerritos, Calif.," (newer).
_ORIGIN_RE = re.compile(
    r"(?:a|an)\s+([A-Z][\w .'-]{1,40}?),\s+([A-Z][A-Za-z. ]{1,20}?),?\s+"
    r"(?:establishment|firm|company|importer|facility|business|distributor|processor)"
    r"|located in\s+([A-Z][\w .'-]{1,40}?),\s+([A-Z][A-Za-z. ]{1,20}?)(?:,|\s+is\b)"
)
_POUNDS_RE = re.compile(r"(?:approximately\s+)?[\d,.]+\s*(?:million\s+)?(?:pounds|lbs)\b", re.IGNORECASE)
_SHIPPED_RE = re.compile(r"(?:were|was)\s+(?:shipped|distributed|sold)\s+(?:to|in|at|through)\s+([^.]{3,300})\.", re.IGNORECASE)
_DISCOVERY_RE = re.compile(r"\b(?:discovered|was found|were found|identified|notified FSIS|learned)\b", re.IGNORECASE)
# Illness comes only from the "There have been (no) ... reports" sentence and
# sentences describing an actual outbreak / sick people - not the standard
# health-education lines ("Some illnesses last longer ...").
_ILLNESS_RE = re.compile(
    r"^There (?:have|has) been|\b(?:sickened|became ill|illnesses? (?:linked|associated|reported)|outbreak strain|"
    r"linked to (?:an|the) outbreak|part of (?:an|the) outbreak|case-patients?)\b"
)
_HEALTH_EDUCATION_RE = re.compile(
    r"^(?:Consumption of|Some illnesses|Most people|Older adults|Listeriosis|Salmonellosis|The illness|Symptoms|"
    r"Individuals|Less commonly|Persons|Infants|People|Pregnant|E\. coli O157|Anyone)", re.IGNORECASE)
_BOILERPLATE_RE = re.compile(
    r"^(?:Anyone concerned|FSIS routinely|FSIS is concerned|Consumers (?:who|with|that)|For consumers|Retailers|"
    r"Media and consumers|Members of the media|The online Electronic|FSIS advises|When available|Consumers are urged)",
    re.IGNORECASE,
)


def unescape(value):
    return html.unescape(value).strip() if isinstance(value, str) else value


def lead_paragraph(summary):
    """The notice's opening paragraph, skipping editor's notes."""
    paragraphs = [p for p in (summary or "").split("\n") if p.strip()]
    for p in paragraphs:
        if p.startswith("WASHINGTON"):
            return _LEAD_PREFIX_RE.sub("", p)
    return next((p for p in paragraphs if not p.lower().startswith("editor")), "")


# A period after these isn't a sentence end: "on Oct. 3", "the U.S. Department", "E. coli".
_ABBREV_END_RE = re.compile(
    r"(?:\b(?:Jan|Feb|Mar|Apr|Jun|Jul|Aug|Sept?|Oct|Nov|Dec|Inc|Co|Corp|Ltd|St|Dr|No|Mr|Mrs|Ms|Jr|Sr|Mt|Ft|approx|vs|etc)"
    r"|\b[A-Z]|" + "|".join(re.escape(a[:-1]) for a in AP_STATES) + r")\.$"
)


def split_sentences(text):
    pieces = re.split(r"(?<=[.!?])\s+", text or "")
    out = []
    for piece in pieces:
        if out and (_ABBREV_END_RE.search(out[-1]) or not piece[:1].isupper()):
            out[-1] += " " + piece
        elif piece:
            out.append(piece)
    return out


def _sentences(summary):
    """The notice's sentences minus boilerplate, checked per sentence: older
    notices put the standard lines in the same paragraph as the real ones."""
    text = " ".join(p.strip() for p in (summary or "").split("\n"))
    return [s for s in split_sentences(text) if not _BOILERPLATE_RE.match(s)]


# How FSIS words the ways a problem is found; layered on detection.py's shared rules.
FSIS_SOURCES = {
    "regulator_inspection": re.compile(
        r"\bFSIS\b[^.]{0,80}?(?:surveillance|inspect|in-plant|verification|label review|import staff|reinspection|personnel|"
        r"records? review|reviewed records)|(?:surveillance|verification|inspection|label review) (?:activities|by FSIS)|"
        r"routine (?:label review|verification|surveillance)|\bPHIS\b|import shipment|recall effectiveness|\bCFIA\b|"
        r"Canadian Food Inspection", re.IGNORECASE),
    "firm_testing": re.compile(
        r"\b(?:establishment|firm|company)(?:['’]s)?\b[^.]{0,60}?(?:test|sampl|laborator)", re.IGNORECASE),
    "consumer_complaint": re.compile(
        r"\b(?:consumers?|customers?|restaurants?|retailers?)\b[^.]{0,40}?\b(?:reported|discovered|found|notified|complain)",
        re.IGNORECASE),
    "regulator_testing": re.compile(
        r"\b(?:FSIS|state|department|public health)\b[^.]{0,80}?(?:sampl|test)|\bsample\b[^.]{0,80}?(?:tested|positive|confirmed)",
        re.IGNORECASE),
}


def fsis_detection_sources(discovery):
    from . import detection
    found = set(detection.detection_sources(discovery))
    for source, pattern in FSIS_SOURCES.items():
        if discovery and pattern.search(discovery):
            found.add(source)
    if "regulator_testing" in found:
        found.discard("firm_testing")
    return sorted(found)


def firm_name(rec):
    title = unescape(rec.get("title") or "")
    if not title.startswith("FSIS "):
        m = _TITLE_FIRM_RE.match(title)
        # Older titles name a place, not the firm: "California Firm Recalls ..."
        if m and not _GENERIC_FIRM_RE.fullmatch(m.group(1).strip()):
            return m.group(1).strip(" ,")
    lead = lead_paragraph(rec.get("summary"))
    for pattern in (_LEAD_FIRM_RE, _BY_FIRM_RE):
        m = pattern.search(lead)
        if m and not m.group(1).startswith(("The U.S.", "The United States", "FSIS")):
            return m.group(1).strip(" ,")
    return None


def origin(rec):
    """(state code, country) of the recalling firm, from 'a Harvey, Ill., establishment'."""
    m = _ORIGIN_RE.search(lead_paragraph(rec.get("summary")))
    if not m:
        return None, None
    place = (m.group(2) or m.group(4)).strip().rstrip(",")
    key = place if place.endswith(".") else place + "."
    if key in AP_STATES or place in AP_STATES:
        return AP_STATES.get(key) or AP_STATES[place], "United States"
    from .distribution import ALL_CODES
    by_name = {v.lower(): k for k, v in ALL_CODES.items()}
    if place.lower() in by_name:
        return by_name[place.lower()], "United States"
    if place.rstrip(".").upper() in ALL_CODES:  # "TX", "AR.", "Wa."
        return place.rstrip(".").upper(), "United States"
    if place.split(",")[0].strip().lower() in CANADIAN_PROVINCES:
        return None, "Canada"
    # A capture that ran on ("Tenn. retail", "Texas and in Tracy"): use the state it starts with.
    first = place.split()[0]
    if first in AP_STATES:
        return AP_STATES[first], "United States"
    if first.lower() in by_name:
        return by_name[first.lower()], "United States"
    return None, place  # outside the US


def notice_parts(rec):
    """Everything the clean layer needs from one committed USDA record."""
    summary = rec.get("summary") or ""
    lead = lead_paragraph(summary)
    sentences = _sentences(summary)
    body = " ".join(sentences)
    discovery = next((s for s in sentences if _DISCOVERY_RE.search(s)), None)
    illness = [s for s in sentences if _ILLNESS_RE.search(s) and not _HEALTH_EDUCATION_RE.match(s)]
    pounds = _POUNDS_RE.search(lead) or _POUNDS_RE.search(body)
    states = [unescape(s) for s in rec.get("states") or []]
    shipped = _SHIPPED_RE.search(body)
    distribution = ", ".join(states) if states else (shipped.group(1) if shipped else None)
    state, country = origin(rec)
    items = [unescape(i) for i in rec.get("product_items") or []]
    return {
        "firm": firm_name(rec),
        "state": state,
        "country": country,
        "title": unescape(rec.get("title")),
        "lead": lead,
        # reason text for the shared rules: the title says why ("Due to Possible
        # Listeria Contamination"), the lead says what and how much
        "reason": f"{unescape(rec.get('title') or '')}. {lead}".strip(),
        "discovery": discovery,
        "illness_text": " ".join(illness) or None,
        "quantity": pounds.group(0) if pounds else None,
        "distribution": distribution,
        "product_description": "\n".join(items) or unescape(rec.get("title")),
        "is_alert": rec.get("recall_type") == "Public Health Alert",
        "ongoing": rec.get("active_notice") == "True" or rec.get("recall_type") == "Active Recall",
        "outbreak": rec.get("related_to_outbreak") == "True",
    }


# FSIS's own reason field, used when the shared text rules find nothing:
# (reasons.py category, detail) per FSIS reason.
FSIS_REASON_TAGS = {
    "Produced Without Benefit of Inspection": ("sanitation", "unlicensed_or_uninspected"),
    "Import Violation": ("sanitation", "unlicensed_or_uninspected"),
    "Insanitary Conditions": ("sanitation", "insanitary"),
    "Misbranding": ("labeling", "other"),
    "Mislabeling": ("labeling", "wrong_label"),
    "Unreported Allergens": ("undeclared_allergen", "unspecified"),
    "Processing Defect": ("processing", "under_processing"),
    "Unfit for Human Consumption": ("processing", "spoilage"),
}

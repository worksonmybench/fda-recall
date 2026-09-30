"""Parse free-text `distribution_pattern` into US states and flags.

Returns the states/territories named (as 2-letter codes), whether the text
says the recall was nationwide, and whether it mentions distribution outside
the US. "Nationwide" recalls usually don't list states, so analysis that
asks "did this reach Texas?" should treat is_nationwide as "every state"
(the clean layer's `event_state_reach` view does this).
"""

import re

STATES = {
    "AL": "Alabama", "AK": "Alaska", "AZ": "Arizona", "AR": "Arkansas", "CA": "California",
    "CO": "Colorado", "CT": "Connecticut", "DE": "Delaware", "FL": "Florida", "GA": "Georgia",
    "HI": "Hawaii", "ID": "Idaho", "IL": "Illinois", "IN": "Indiana", "IA": "Iowa",
    "KS": "Kansas", "KY": "Kentucky", "LA": "Louisiana", "ME": "Maine", "MD": "Maryland",
    "MA": "Massachusetts", "MI": "Michigan", "MN": "Minnesota", "MS": "Mississippi", "MO": "Missouri",
    "MT": "Montana", "NE": "Nebraska", "NV": "Nevada", "NH": "New Hampshire", "NJ": "New Jersey",
    "NM": "New Mexico", "NY": "New York", "NC": "North Carolina", "ND": "North Dakota", "OH": "Ohio",
    "OK": "Oklahoma", "OR": "Oregon", "PA": "Pennsylvania", "RI": "Rhode Island", "SC": "South Carolina",
    "SD": "South Dakota", "TN": "Tennessee", "TX": "Texas", "UT": "Utah", "VT": "Vermont",
    "VA": "Virginia", "WA": "Washington", "WV": "West Virginia", "WI": "Wisconsin", "WY": "Wyoming",
    "DC": "District of Columbia",
}
TERRITORIES = {
    "PR": "Puerto Rico", "GU": "Guam", "VI": "Virgin Islands", "AS": "American Samoa",
    "MP": "Northern Mariana Islands",
}
ALL_CODES = {**STATES, **TERRITORIES}
FIFTY_PLUS_DC = set(STATES)

# Extra names seen in the data.
ALIASES = {
    "washington dc": "DC", "washington d.c.": "DC", "washington, dc": "DC", "washington, d.c.": "DC",
    "d.c.": "DC", "us virgin islands": "VI", "u.s. virgin islands": "VI",
}

# Codes that are also ordinary words. In all-caps text they only count
# inside a list of states ("IL, IN, MI"); written in lower case they never
# count ("sold in CA, or NV").
WORD_CODES = {"IN", "OR", "ME", "OK", "HI", "DE", "ID", "AS", "CO", "LA", "AL", "MA", "PA", "OH", "NE", "MO", "MS", "GA"}

_NAME_RE = re.compile(
    r"\b(" + "|".join(
        re.escape(n) for n in sorted([*(v.lower() for v in ALL_CODES.values()), *ALIASES], key=len, reverse=True)
    ) + r")(?![a-z])",
    re.IGNORECASE,
)
_NAME_TO_CODE = {**{v.lower(): k for k, v in ALL_CODES.items()}, **ALIASES}
_CODE_RE = re.compile(r"(?<![A-Za-z.])([A-Za-z]{2})(?![A-Za-z])")
# What may sit between two items of a state list. Word-like codes in
# all-caps text need real punctuation ("IN, OH"), not just a space ("IN CA").
_LIST_SEP_RE = re.compile(r"\s*(?:[,;/&]|\band\b)?\s*", re.IGNORECASE)
_STRICT_LIST_SEP_RE = re.compile(r"\s*[,;/&]\s*")
# "DC" also abbreviates distribution center: "CO DC's", "with DCs", "their DC", "2 DC".
_DISTRIBUTION_CENTER_RE = re.compile(r"DC\s*['’]s|\b(?:with|their|its|our|the|one|two|three|\d+)\s+DC\b", re.IGNORECASE)

NATIONWIDE_RE = re.compile(
    r"nation\s*-?\s*wide|nationally|national distribution|throughout the (?:us|u\.s\.?|united states|country)"
    r"|all 50 states|all fifty states|all states\b(?!:)|across the (?:us|u\.s\.?|united states|country)"
    r"|entire (?:us|u\.s\.?|united states|country)|every state|all over the (?:us|country)|world\s*-?\s*wide",
    re.IGNORECASE,
)

# Online / mail-order sales. Amazon Fresh / Go / physical Amazon stores are
# local retail, so bare "Amazon" only counts when not followed by those.
ONLINE_RE = re.compile(
    r"\bon\s*-?\s*line\b|\binternet\b|\bweb\s*-?\s*site|\bweb\s+(?:sales|store|orders?)|\be\s*-?\s*commerce"
    r"|\bamazon(?:\.com)?\b(?!\s+(?:fresh|go|stores?|locations?|books))|\bmail[\s-]*orders?|\bby mail\b"
    r"|\bebay\b|\betsy\b|\bshopify\b|\bwww\.|https?://|\.com\b",
    re.IGNORECASE,
)

COUNTRIES = [
    "canada", "mexico", "bahamas", "bermuda", "cayman", "jamaica", "haiti", "dominican republic",
    "trinidad", "barbados", "aruba", "curacao", "panama", "costa rica", "guatemala", "honduras", "el salvador",
    "nicaragua", "belize", "colombia", "venezuela", "ecuador", "peru", "chile", "brazil", "argentina",
    "united kingdom", "england", "scotland", "ireland", "france", "germany", "netherlands", "belgium", "spain",
    "portugal", "italy", "switzerland", "austria", "sweden", "norway", "denmark", "finland", "poland", "greece",
    "israel", "lebanon", "jordan", "saudi arabia", "kuwait", "qatar", "united arab emirates", "uae", "dubai",
    "egypt", "south africa", "nigeria", "india", "pakistan", "china", "hong kong", "taiwan", "japan", "korea",
    "philippines", "vietnam", "thailand", "singapore", "malaysia", "indonesia", "australia", "new zealand",
]
FOREIGN_RE = re.compile(
    r"\b(?:foreign|international(?:ly)?|export(?:ed|s)?|overseas|world\s*-?\s*wide|outside (?:the )?(?:us|u\.s\.?|united states))\b",
    re.IGNORECASE,
)
_COUNTRY_RE = re.compile(r"\b(" + "|".join(re.escape(c) for c in COUNTRIES) + r")\b", re.IGNORECASE)
# "No foreign distribution", "Foreign: Not applicable", "no international / military ..."
NO_FOREIGN_RE = re.compile(
    r"\b(?:no|not|none|without)\s+(?:\w+\s+){0,2}?(?:foreign|international|export|overseas)"
    r"|(?:foreign|international|export|overseas)(?:\s+(?:distribution|consignees|accounts|customers))?\s*[:\-]?\s*"
    r"(?:none|no\b|not\s|n/?a\b|was not|were not|0\b)",
    re.IGNORECASE,
)


def _mostly_upper(text):
    """True for all-caps prose. Two-letter words are ignored: state-code lists are upper case anyway."""
    words = [w for w in re.findall(r"[A-Za-z]{3,}", text)]
    return len(words) >= 2 and sum(w.isupper() for w in words) / len(words) > 0.8


def find_states(text):
    """Return the sorted list of state/territory codes named in the text."""
    if not text:
        return []
    found = set()

    # Full names first, blanked out so "New Mexico" isn't also read as
    # Mexico and "West Virginia" isn't also read as Virginia.
    def take_name(m):
        found.add(_NAME_TO_CODE[m[1].lower()])
        return " , "

    remaining = _NAME_RE.sub(take_name, text)
    all_caps = _mostly_upper(text)
    tokens = [t for t in _CODE_RE.finditer(remaining) if t[1].upper() in ALL_CODES]

    def in_list(i, sep_re=_LIST_SEP_RE):
        """True if token i is next to another code, separated only by list punctuation."""
        neighbours = [(tokens[i - 1], tokens[i])] if i > 0 else []
        neighbours += [(tokens[i], tokens[i + 1])] if i + 1 < len(tokens) else []
        return any(sep_re.fullmatch(remaining[a.end():b.start()]) for a, b in neighbours)

    for i, tok in enumerate(tokens):
        raw, code = tok[1], tok[1].upper()
        if code == "DC" and _DISTRIBUTION_CENTER_RE.search(remaining[max(0, tok.start() - 12):tok.end() + 2]):
            continue  # "DC's" / "their DC" = distribution center(s)
        if raw == code:
            ok = not all_caps or code not in WORD_CODES or in_list(i, _STRICT_LIST_SEP_RE)
        elif raw.islower():
            ok = code not in WORD_CODES and in_list(i)
        else:  # title case, e.g. "TX, Ok, KS"
            ok = in_list(i)
        if ok:
            found.add(code)
    return sorted(found)


def parse_distribution(text):
    """Return (states, is_nationwide, is_foreign, is_online) for a distribution_pattern.

    Online / mail-order sales count as nationwide, since anyone in the
    country could have bought the product.
    """
    if not text:
        return [], False, False, False
    states = find_states(text)
    online = bool(ONLINE_RE.search(text))
    nationwide = bool(NATIONWIDE_RE.search(text)) or online or len(set(states) & FIFTY_PLUS_DC - {"DC"}) == 50
    without_negations = NO_FOREIGN_RE.sub(" ", text)
    without_us_names = _NAME_RE.sub(" ", without_negations)  # "New Mexico" isn't Mexico
    foreign = bool(FOREIGN_RE.search(without_us_names) or _COUNTRY_RE.search(without_us_names))
    return states, nationwide, foreign, online

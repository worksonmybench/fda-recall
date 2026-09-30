"""Parse free-text `product_quantity` into a rough size estimate.

The FDA text mixes cases, units, pounds, gallons, pallets, etc. We can't
compare those exactly, so everything is converted to *estimated retail
units* using deliberately rough factors (a case = 12 units, 1 lb = 1 unit,
volumes via the weight of water) and then bucketed by order of magnitude
into t-shirt sizes. The sizes are meant for "is this recall big or small",
not for precise totals.
"""

import re

# unit word -> (family, retail units per 1 of this unit)
EACH = 1.0
CASE = 12.0  # typical retail case pack; rough
UNITS = {}


def _add(family, factor, *words):
    for w in words:
        UNITS[w] = (family, factor)


_add("each", EACH,
     "unit", "units", "retail units", "each", "eaches", "ea", "ct", "count", "pc", "pcs", "piece", "pieces",
     "item", "items", "product", "products", "bottle", "bottles", "bag", "bags", "bg", "package", "packages",
     "pkg", "pkgs", "pack", "packs", "pk", "packet", "packets", "box", "boxes", "carton", "cartons", "tub", "tubs",
     "container", "containers", "jar", "jars", "can", "cans", "tray", "trays", "cup", "cups", "pouch", "pouches",
     "bar", "bars", "loaf", "loaves", "sandwich", "sandwiches", "cookie", "cookies", "cake", "cakes", "pie",
     "pies", "cheesecake", "cheesecakes", "kit", "kits", "jug", "jugs", "pail", "pails", "basket", "baskets",
     "wheel", "wheels", "clamshell", "clamshells", "bunch", "bunches", "head", "heads", "bundle", "bundles",
     "sleeve", "sleeves", "tube", "tubes", "bucket", "buckets", "drum", "drums", "tote", "totes", "sack", "sacks",
     "block", "blocks", "roll", "rolls", "egg", "eggs", "dozen eggs", "croissants", "bowls", "meals", "boxes",
     "individual units", "consumer units", "retail packages", "salads", "wraps", "burritos", "pizzas")
_add("each", 12.0, "dozen", "doz")
_add("each", 1 / 60, "capsule", "capsules", "caps", "tablet", "tablets", "softgel", "softgels")
_add("case", CASE, "case", "cases", "cs", "casaes", "cases-total", "master case", "master cases", "shipper", "shippers")
_add("case", 50 * CASE, "pallet", "pallets", "skid", "skids")
_add("weight", 1.0, "lb", "lbs", "pound", "pounds", "#")
_add("weight", 1 / 16, "oz", "ounce", "ounces")
_add("weight", 2.2046, "kg", "kgs", "kilogram", "kilograms", "kilo", "kilos")
_add("weight", 1 / 453.6, "g", "gram", "grams")
_add("weight", 2000.0, "ton", "tons")
_add("weight", 2204.6, "mt", "metric ton", "metric tons", "tonne", "tonnes")
_add("weight", 100.0, "cwt", "cwts")
_add("volume", 8.34, "gallon", "gallons", "gal", "gals")
_add("volume", 2.09, "quart", "quarts", "qt", "qts")
_add("volume", 1.04, "pint", "pints", "pt", "pts")
_add("volume", 0.065, "fl oz", "fl. oz", "fluid ounces")
_add("volume", 2.2, "liter", "liters", "litre", "litres", "l")
_add("volume", 0.0022, "ml")

# Longest first so "fl oz" wins over "oz", "master cases" over "cases".
_UNIT_ALT = "|".join(sorted((re.escape(u) for u in UNITS), key=len, reverse=True))
NUMBER = r"\d{1,3}(?:,\s?\d{3})+(?:\.\d+)?|\d+(?:\.\d+)?"
PAIR_RE = re.compile(
    rf"(?P<num>{NUMBER})\s*(?P<mult>million|thousand|k\b)?\s*(?P<unit>{_UNIT_ALT})(?![a-z])",
    re.IGNORECASE,
)
# A number + weight/volume followed by a container word is a pack size
# ("500 12-oz bottles", "1-lb: 500 bags"), not the recalled amount.
SIZE_UNIT = r"(?:fl\.?\s*oz|oz|ounces?|lbs?|pounds?|g|grams?|kg|gal|gallons?|qt|pt|ml|l|liters?|ct|count)\b\.?"
_NOT_CONTAINERS = {"product", "products", "item", "items"}  # "20,000 lbs of product" is an amount
_CONTAINER_ALT = "|".join(sorted(
    (re.escape(u) for u, (fam, _) in UNITS.items()
     if fam in ("each", "case") and " " not in u and u not in _NOT_CONTAINERS),
    key=len, reverse=True,
))
# Lot / item / UPC numbers aren't amounts: "Lot# 100420218 = 23,223".
IDENTIFIER_RE = re.compile(
    r"\b(?:lot|item|upc|sku|code|batch|model|style|ref)s?\s*(?:no\.?|number|nos\.?|#|code)?\s*[:#]?\s*\d[\w]*",
    re.IGNORECASE,
)
PACK_SIZE_RE = re.compile(
    rf"(?:{NUMBER})\s*-?\s*{SIZE_UNIT}"
    # followed by a container within two words ("2 lb mesh bags", "14 oz. plastic jars"), or a colon ("1-lb: 500 bags")
    rf"(?:(?:\s*-\s*|\s+)(?=(?:[a-z&]+\s+){{0,2}}(?:{_CONTAINER_ALT})\b)|\s*:)",
    re.IGNORECASE,
)
# "5,391/1.6oz bags", "1142/40 lbs. boxes": a count, then the size of each.
COUNT_SLASH_SIZE_RE = re.compile(rf"({NUMBER})\s*/\s*(?:{NUMBER})\s*-?\s*{SIZE_UNIT}", re.IGNORECASE)
# Per-case pack descriptions: "12/23oz", "6/2 lb", "12 x 14 oz".
PACK_SPEC_RE = re.compile(rf"/\s*(?:{NUMBER})\s*(?:/\s*(?:{NUMBER}))?|\b(?:{NUMBER})\s*x\s*(?:{NUMBER})", re.IGNORECASE)
TOTAL_RE = re.compile(rf"\btotal(?:\s+(?:quantity|distributed|amount|of))?\s*[:=\-]?\s*(?:approx\w*\.?\s*)?(?={NUMBER})", re.IGNORECASE)
PARENS_RE = re.compile(r"\([^)]*\)|\[[^\]]*\]")
# Marks a quantity that covers the whole event rather than one product.
EVENT_TOTAL_RE = re.compile(r"total|all (products|varieties|items|skus|flavors|lots|sizes|codes)|combined", re.IGNORECASE)

# --- how many retail units are in one case / box / pallet ---------------------
# Containers that hold several retail units. Only these get multiplied by a
# stated pack count: "bottles of 40 count" means 40 pills, not 40 bottles.
MULTIPACK = {"case", "cases", "cs", "casaes", "cases-total", "master case", "master cases", "shipper", "shippers",
             "pallet", "pallets", "skid", "skids", "box", "boxes", "carton", "cartons", "tray", "trays",
             "display", "displays", "bundle", "bundles", "crate", "crates", "flat", "flats"}
_WEIGHT_WORDS = {u for u, (fam, _) in UNITS.items() if fam in ("weight", "volume")}
_SIZE = rf"(?:{NUMBER})\s*-?\s*(?:fl\.?\s*oz|oz|ounces?|lbs?|pounds?|g|grams?|kg|ml|l|liters?|gal|gallons?)\b\.?"
_PER_CONTAINER = (
    # "each" as an adverb ("477 containers each weighing 44 lbs") isn't a pack description
    r"(?:\beach\b(?!\s+(?:weigh|contain|hold|with|of|having|measur))|\bper\s+(?:master\s+)?(?:case|cs|box|carton|pack(?:age)?|shipper|tray|display|bundle|pallet|skid|container|bag)\b"
    r"|/\s*(?:case|cs|box|ctn|carton)\b|\bin\s+(?:each|every|a)\s+(?:case|box|carton)\b)"
)
# Tried in order; each captures the units per container in group "n", and
# optionally the words between the number and "each"/"per case" in "words".
PACK_PATTERNS = [
    # "each case has 24 cans", "each case contains 6 boxes", "1 case = 42 potatoes"
    re.compile(rf"\beach\s+(?:case|box|carton)\s+(?:has|contains|holds|with|of)\s+(?P<n>{NUMBER})", re.IGNORECASE),
    re.compile(r"\b1\s*(?:case|cs|box|carton)\s*=\s*(?P<n>\d+)", re.IGNORECASE),
    # "cases consisting of 25 tins", "10 cases with 12 packages", "2449 Cases x 6 bags"
    re.compile(rf"\b(?:cases?|cs|boxes|cartons?)\s*(?P<drop>(?:consisting of|containing|contain|with|holding|x)\s*(?P<n>\d+))"
               rf"(?!\s*(?:\.\d|{SIZE_UNIT}))", re.IGNORECASE),
    # "6/2 lb. bags per case", "8/7.1oz units per case", "6-50oz units/case", "200 ct/9 gram pack per case"
    re.compile(rf"(?P<n>\d+)\s*(?:ct|count)?\s*[/\-]\s*(?:{_SIZE}|\d+(?:\.\d+)?)\s*(?:[a-z.\-]+\s*){{0,3}}?{_PER_CONTAINER}", re.IGNORECASE),
    # "cases of 12 units", "cases of 12/ 9 oz", "cases of 12 x 16 oz" - plural only: "per case of
    # 17,208 units" is a total
    re.compile(rf"\b(?:cases|cs|boxes|cartons)\s+(?P<drop>of\s+(?P<n>{NUMBER})(?!\s*(?:\.\d|{SIZE_UNIT})))", re.IGNORECASE),
    # "93cs/12/23oz", "700/cs/24/17.9oz"
    re.compile(rf"(?:\bcs|cases?)(?P<drop>\s*/\s*(?P<n>\d+)\s*/)", re.IGNORECASE),
    # "12 x 14 oz. plastic jars"
    re.compile(rf"\b(?P<n>\d+)\s*x\s*{_SIZE}", re.IGNORECASE),
    # "144 units per case", "(12 per case)", "(12/case)", "(54 units each)", "(5 pounds each)", "20 lbs/case"
    re.compile(rf"(?P<n>{NUMBER})\s*(?P<words>(?:[a-z.\-]+\s*){{0,3}}?)\s*{_PER_CONTAINER}", re.IGNORECASE),
]
# "179 cases (1,432 bottles)": the unit total FDA already worked out for the cases.
PAREN_UNIT_TOTAL_RE = re.compile(
    rf"\(\s*(?:approx\w*\.?\s*)?(?P<n>{NUMBER})\s*(?:total\s+)?(?:retail |individual |consumer )?"
    r"(?:units|pieces|bottles|packages|jars|cans|bags|cartons|tubs|cups|containers|pouches|bars|eaches|each|ct)\s*(?:total)?\s*\)",
    re.IGNORECASE,
)


_NOT_PACK_WORDS = {"for", "to", "from", "of", "in", "on", "at", "and", "or", "total", "distributed", "shipped", "sold"}
# "bottles of 40 count" / "boxes of 24 ct": describes what's inside each unit, not an amount.
OF_COUNT_RE = re.compile(r"\bof\s+\d+\s*-?\s*(?:count|ct)\b", re.IGNORECASE)


# "41,436 x 6 x 5 lb": 41,436 cases of 6. "2,166 x 16 oz": 2,166 units of 16 oz.
# Also "86,817 20 x 16 oz" (86,817 cases of 20).
COUNT_X_COUNT_X_SIZE_RE = re.compile(rf"(?P<a>{NUMBER})\s*(?:x\s*|\s)(?P<b>\d+)\s*x\s*{_SIZE}", re.IGNORECASE)
COUNT_X_SIZE_RE = re.compile(rf"(?P<a>{NUMBER})\s*x\s*{_SIZE}", re.IGNORECASE)
_MULTIPACK_WORD_RE = re.compile(r"\b(?:cases?|cs|boxes|cartons?|pallets?|trays?|displays?|shippers?|master)\b", re.IGNORECASE)


def _expand_multiplied_counts(text):
    """Rewrite 'N x M x size' as N*M units, and 'N x size' as N units when no case is mentioned."""
    text = COUNT_X_COUNT_X_SIZE_RE.sub(lambda m: f"{_to_float(m['a']) * int(m['b']):.0f} units ", text)
    if not _MULTIPACK_WORD_RE.search(text):
        text = COUNT_X_SIZE_RE.sub(lambda m: f"{m['a']} units ", text)
    return text


MAX_PACK_COUNT = 5_000  # nobody packs more retail units than this into one case / pallet
MIN_CASE_WEIGHT = 3     # lb; "N oz each" below this describes a retail unit, not a case
_N_X_SIZE = next(p for p in PACK_PATTERNS if p.pattern.startswith(r"\b(?P<n>\d+)\s*x"))
_PALLETS = {"pallet", "pallets", "skid", "skids"}


def _units_per_container(text):
    """Find how many retail units one multi-pack container holds.

    Returns (units, applies_to_pallets, text with that phrase removed), or
    (None, False, text). A per-case count isn't applied to pallets and vice
    versa ("10 pallets - 6x 4 pks per case").
    """
    for pattern in PACK_PATTERNS:
        for m in pattern.finditer(text):
            n = _to_float(m["n"])
            words = (m.groupdict().get("words") or "").strip().lower().rstrip(".")
            first = words.split(" ")[0] if words else ""
            if not words and re.search(r"each\W*$", m[0], re.IGNORECASE):
                continue  # "20,520 each" is an amount, not "20,520 per container"
            if pattern is _N_X_SIZE and n > 200:
                continue  # "9964 x 25 lb. boxes" is a count of boxes, not a pack size
            if first in _WEIGHT_WORDS:  # "(5 pounds each)": a weight per container
                family, factor = UNITS[first]
                units = n * factor
                if units < MIN_CASE_WEIGHT:
                    continue  # "1792 pouches, 1.2 oz each": the size of each unit, not of a case
            elif set(words.split()) & _NOT_PACK_WORDS:
                continue  # "3,000 packages for each product": not a pack description
            elif n != int(n):
                continue  # a count of things per case is a whole number ("5/1.25 Pkgs per case")
            else:
                units = n
            if 1 < units < MAX_PACK_COUNT:
                # Remove just the pack phrase, never the container word before it.
                start, end = m.span("drop") if m.groupdict().get("drop") else m.span()
                applies_to_pallets = bool(re.search(r"pallet|skid", m[0], re.IGNORECASE))
                return units, applies_to_pallets, text[:start] + " " + text[end:]
    return None, False, text


SIZES = [  # (label, upper bound in estimated retail units, exclusive)
    ("XS", 100),
    ("S", 1_000),
    ("M", 10_000),
    ("L", 100_000),
    ("XL", 1_000_000),
    ("XXL", float("inf")),
]


def _to_float(num):
    return float(num.replace(",", "").replace(" ", ""))


def _pairs(text):
    pairs = []
    for m in PAIR_RE.finditer(text):
        value = _to_float(m["num"])
        mult = (m["mult"] or "").lower()
        value *= {"million": 1e6, "thousand": 1e3, "k": 1e3}.get(mult, 1)
        family, factor = UNITS[m["unit"].lower()]
        pairs.append((m.start(), value, m["unit"].lower(), family, value * factor))
    return pairs


def parse_quantity(text):
    """Return (estimated_units, family, is_event_total) or None if unparseable.

    Strategy: read how many units a case/box holds if the text says so
    ("12 units per case", "(6/2 lb bags per case)"), drop parenthesised
    notes and pack-size descriptions, then use the amount right after
    "total" if there is one, otherwise add up every amount of the same unit
    family as the first one found. Multi-pack containers use the stated
    pack count, or failing that a unit total FDA gave in parentheses
    ("179 cases (1,432 bottles)"), or failing that 12 per case.
    """
    if not text or not re.search(r"\d", text):
        return None
    is_total = bool(EVENT_TOTAL_RE.search(text))

    text = _expand_multiplied_counts(IDENTIFIER_RE.sub(" ", text))
    per_container, for_pallets, text = _units_per_container(text)
    text = OF_COUNT_RE.sub(" ", text)
    for candidate in (PARENS_RE.sub(" ", text), text):  # fall back to text inside parens
        stripped = COUNT_SLASH_SIZE_RE.sub(r"\1 units ", candidate)
        stripped = PACK_SIZE_RE.sub(" ", PACK_SPEC_RE.sub(" ", stripped))
        pairs = _pairs(stripped)
        if pairs and per_container:
            pairs = [(pos, value, unit, family,
                      value * per_container if unit in MULTIPACK and (unit in _PALLETS) == for_pallets else units)
                     for pos, value, unit, family, units in pairs]
        elif pairs and pairs[0][3] == "case" and sum(p[3] == "case" for p in pairs) == 1:
            stated = PAREN_UNIT_TOTAL_RE.search(text)
            if stated:
                return _to_float(stated["n"]), "each", is_total
        if not pairs:
            # No recognised unit ("10693", "833 strips"): count the first number as units.
            bare = re.search(NUMBER, stripped)
            if bare:
                return _to_float(bare[0]), "each", is_total
            continue

        total = TOTAL_RE.search(stripped)
        if total:
            after = [p for p in pairs if p[0] >= total.end()]
            if after:
                _, _, _, family, units = after[0]
                return units, family, True

        family = pairs[0][3]
        return sum(p[4] for p in pairs if p[3] == family), family, is_total
    return None


def size_bucket(units):
    """T-shirt size for an estimated retail-unit count, or None if unknown."""
    if units is None:
        return None
    return next(label for label, upper in SIZES if units < upper)


def event_units(parsed_quantities):
    """Combine the parsed quantities of one event's products.

    `parsed_quantities` is a list of (text, parse_quantity(text)) for each
    product. Identical texts are counted once (they're usually the same
    event total copied onto every product). Quantities marked as a total
    are compared against the sum of the per-product ones, and the larger
    wins.
    """
    per_product, totals = 0.0, []
    seen = set()
    for text, parsed in parsed_quantities:
        if parsed is None or text in seen:
            continue
        seen.add(text)
        units, _, is_total = parsed
        if is_total:
            totals.append(units)
        else:
            per_product += units
    if not seen:
        return None
    return max([per_product, *totals])

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

    Strategy: drop parenthesised notes and pack-size descriptions, then use
    the amount right after "total" if there is one, otherwise add up every
    amount of the same unit family as the first one found.
    """
    if not text or not re.search(r"\d", text):
        return None
    is_total = bool(EVENT_TOTAL_RE.search(text))

    text = IDENTIFIER_RE.sub(" ", text)
    for candidate in (PARENS_RE.sub(" ", text), text):  # fall back to text inside parens
        stripped = COUNT_SLASH_SIZE_RE.sub(r"\1 units ", candidate)
        stripped = PACK_SIZE_RE.sub(" ", PACK_SPEC_RE.sub(" ", stripped))
        pairs = _pairs(stripped)
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

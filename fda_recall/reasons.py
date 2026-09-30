"""Rule-based tagging of `reason_for_recall` text.

A reason can get several tags (e.g. Listeria *and* undeclared milk), each a
(category, detail) pair such as ("pathogen", "listeria") or
("undeclared_allergen", "peanut"). Rules are plain regexes so they're easy
to read and adjust; anything no rule matches is left untagged for review.

Reason texts often name the product or its packaging ("Hot Smoked Salmon",
"plastic clamshell", "Wood-Ear mushroom"), so the allergen and foreign
material rules need supporting wording (see CONTEXT), which is stricter when
the text already matched another category.
"""

import re

# (detail, pattern) per category. Patterns are matched case-insensitively
# against the whole reason text.
PATHOGENS = [
    ("listeria", r"listeria|monocytogenes|\bl\.?\s*mono\b"),
    ("salmonella", r"salmonell"),
    ("e_coli", r"\be[.\s-]*coli\b|\bstec\b|o157|shiga"),
    ("c_botulinum", r"botulin|\bc\.?\s*bot\b"),
    ("cyclospora", r"cyclospora"),
    ("hepatitis_a", r"hepatitis\s*a\b|\bhav\b"),
    ("norovirus", r"norovirus"),
    ("vibrio", r"vibrio"),
    ("staph_aureus", r"staph|aureus"),
    ("bacillus_cereus", r"cereus"),
    ("c_perfringens", r"perfringens"),
    ("campylobacter", r"campylobacter"),
    ("shigella", r"shigella"),
    ("cronobacter", r"cronobacter|sakazakii"),
    ("yersinia", r"yersinia"),
    ("burkholderia", r"burkholderia|\bb\.?\s*cepacia"),
]

DECLARE_PREFIX = r"(undeclared|not declare[ds]?|does not declare|did not declare|omitted)\s+(the\s+)?"

ALLERGENS = [
    ("milk", r"\bmilk\b|casein|undeclared\s+dairy|\bwhey\b|(?<!peanut )(?<!nut )(?<!cocoa )\bbutter\b"),
    ("egg", r"\beggs?\b"),
    ("peanut", r"peanut"),
    ("tree_nut", r"tree\s*nut|almond|cashew|walnut|pecan|hazelnut|filbert|pistachio|macadamia|brazil\s*nut|pine\s*nut|coconut"),
    ("soy", r"\bsoy"),
    ("wheat", r"wheat"),
    # Species names (salmon, tuna, shrimp...) usually name the product, so
    # they only count directly after "undeclared" / "does not declare".
    ("fish", r"\bfish\b|anchov|pollock|" + DECLARE_PREFIX + r"(salmon|tuna|cod|tilapia|catfish|trout|sardine|mackerel|swordfish|halibut|snapper)\b"),
    ("shellfish", r"shellfish|crustacean|" + DECLARE_PREFIX + r"(shrimp|prawns?|crab|lobster|crawfish|crayfish)\b"),
    ("sesame", r"sesame"),
    ("sulfites", r"sulfit|sulphit"),
]
ALLERGEN_CONTEXT = (
    r"undeclared|allergen|allergy|allergic|declar|not list|mislabel|omit|missing from"
    r"|cross.?contact|same equipment|shared equipment"
    r"|\b(milk|peanut|egg|soy|wheat|nut|sesame)\s+(protein\s+)?(contamination|residue)"
)
GENERIC_ALLERGEN = (
    r"undeclared\s+(major\s+)?(food\s+)?allergen|allergen\s+cross.?contact|allergic reaction"
    r"|(not|did not|does not|failed to)\s+declare\s+(the\s+)?(major\s+)?allergens"
)

# Packaging words after a material ("glass bottles", "plastic tubs") mean
# the text is describing the container, not something in the food.
NOT_PACKAGING = r"(?!\s+(bottles?|jars?|tubs?|containers?|bags?|clamshells?|cups?|jugs?|trays?|cans?|lids?|packag))"

FOREIGN_MATERIALS = [
    ("metal", r"\bmetal(?!lic)" + NOT_PACKAGING + r"|metallic\s+(mesh|piece|fragment|object|material|particle)"
              r"|alumin(i)?um\s+(fragment|piece|shaving|particle)|pieces of alumin|\bwire\b|stainless|\bsteel\b|\bnails?\b"),
    ("plastic", r"plastic" + NOT_PACKAGING),
    ("glass", r"\bglass\b" + NOT_PACKAGING),
    ("wood", r"\bwood(en)?\b"),
    ("rubber", r"rubber|gasket"),
    ("stone", r"\bstones\b|\brocks\b|pebble"),
    ("bone", r"\bbones?\b"),
    ("other", r"foreign\s*(material|object|matter|body|bodies)|extraneous|\bcloth\b|fib(er|re)s\b|\bcotton\b"
              r"|packing material|pieces of material|floating objects|trim ring|fingertip"),
]
FOREIGN_CONTEXT = (
    r"foreign|extraneous|fragment|piece|shaving|chip|shard|sliver|particle"
    r"|filing|debris|flake|\bbits?\b|\bstones\b|\brocks\b|\bwire\b|breakage"
)


CHEMICALS = [
    ("heavy_metal", r"(?<!may )(?<!could )(?<!can )\blead\b(?! to)|arsenic|cadmium|mercury"),
    ("pfas", r"pfas|pfoa|pfos|perfluoro"),
    ("pesticide", r"pesticide|herbicide|insecticide|fungicide|chlorpyrifos|haloxyfop"),
    ("mycotoxin", r"aflatoxin|patulin|ochratoxin|mycotoxin|vomitoxin|deoxynivalenol|fumonisin"),
    ("histamine", r"histamine|scombro"),
    ("drug_residue", r"chloramphenicol|antibiotic|beta.?lactam|nitrofuran|malachite|sulfonamide|veterinary drug"),
    ("radiological", r"cesium|radioactiv|radiation|\bcs-?137"),
    ("natural_toxin", r"oleander|muscimol|ciguatoxin|tetrodotoxin|solanine|cyanide|amygdalin|pyrrolizidine|tropane|jimson"),
    ("excess_nutrient", r"(excess(ive)?|elevated|high|toxic)\s+(levels?\s+of\s+|amounts?\s+of\s+)?(vitamin|iron|selenium|iodine|niacin|zinc)"
                        r"|(vitamin\s+[a-e]\d*|selenium|iron|iodine|niacin|zinc)\s+(levels?\s+)?(above|exceed|in excess|too high|toxicity)"),
    ("cleaning_or_industrial", r"detergent|cleaning (solution|chemical|agent|compound)|lubricant|hydraulic|\bink\b|caustic|bleach|ammonia|chlorine|reach truck"),
    ("other", r"\bchemicals?\b|\btoxic\b|dimethyl yellow|sudan (dye|red)|erucic|\btbhq\b"),
]

UNAPPROVED_DRUGS = [
    ("pharmaceutical", r"sildenafil|tadalafil|vardenafil|sibutramine|phenolphthalein|fluoxetine|dexamethasone|diclofenac"
                       r"|pharmaceutical|drug ingredient|\bhcg\b|chorionic|dmaa|dimethylamylamine|dmha|ephedr|yohimbine"
                       r"|phenibut|tianeptine|kratom|cannabidiol|\bcbd\b|\bthc\b|delta.?8"),
    ("steroid", r"steroid|anabolic|\bsarms?\b|prohormone"),
    ("drug_claims", r"unapproved\s+(new\s+)?drugs?|\bnew drugs?\b|drug claims|disease claims|deemed\s+(to be\s+)?(unapproved\s+)?drugs?"),
    ("unapproved_ingredient", r"unapproved\s+(food\s+|color\s+|dietary\s+)?(additive|ingredient|substance|color)|not approved (for|as)"
                              r"|new dietary ingredient|cyclamate|picamilon|not generally recognized|\bgras\b|illegal (dye|colou?r)"),
]

PROCESSING = [
    ("under_processing", r"under.?process|process(ing)? deviation|inadequate(ly)? process|improper(ly)? process"
                         r"|not (properly )?processed|acidified|low.?acid|\bph\b|water activity|thermal process"
                         r"|scheduled process|retort|insufficient(ly)? (heat|cook)|under.?cook|not (fully )?cooked|commercial(ly)? steril"),
    # "Pasteurized" on its own is usually part of the product name.
    ("pasteurization", r"unpasteuri|(not|improper(ly)?|inadequate(ly)?|insufficient(ly)?|under)[\s-]+(been\s+|properly\s+|adequately\s+|fully\s+)?pasteuri"
                       r"|pasteuri[sz]ation|failed\s+pasteuri"),  # the noun is always about the process
    ("spoilage", r"spoil|\bmou?ld(s|y|ing)?\b|\bapc\b|yeast(?!\s+(extract|ingredient))|swell|swollen|bloat|ferment|off.?odou?r|foul odou?r"
                 r"|decompos|rancid|coliform|aerobic plate|plate count"),
    ("packaging_defect", r"\bseal|leak|\bseams?\b|container integrity|packaging (defect|failure|integrity)|air space"
                         r"|sharp edge|pinhole|puncture|nozzle|dislodge|chok(e|ing)"),
]

TEMPERATURE = [
    ("temperature_abuse", r"temperature|refrigerat|\bcooler\b|freezer|thaw|temp\.? abuse|out of temp|reefer|cold chain|power outage"),
]

SANITATION = [
    ("gmp", r"\bc?gmp'?s?\b|good manufacturing|manufacturing practice|haccp|process authority|unapproved source"),
    ("insanitary", r"insanitary|unsanitary|sanitation|sanitary condition|sanitizer|unclean|hygien"),
    ("pests", r"rodent|\bmice\b|\bmouse\b|\brats?\b|insect|beetle|\bpests?\b|\bflies\b|cockroach|roach|dropping|feces|fecal"
              r"|excreta|infest|larva|weevil|\bmoths?\b|filth"),
    ("unlicensed_or_uninspected", r"unlicensed|without (a )?licen|not licensed|uninspected|without (the )?(benefit of )?inspection"
                                  r"|unregistered|not registered|without registration|without (a )?permit|no permit"),
]

LABELING = [
    ("undeclared_color", r"yellow\s*(#|no\.?)?\s*[56]\b|red\s*(#|no\.?)?\s*(3|40)\b|blue\s*(#|no\.?)?\s*[12]\b|fd&c|tartrazine"
                         r"|undeclared\s+(food\s+)?colou?r|colou?rs?\s+(were\s+|was\s+)?not declared"),
    ("gluten", r"gluten"),
    ("wrong_label", r"mislabel|wrong label|incorrect(ly)? label|labels? (for|from) (a )?(different|another)|wrong (package|packaging|container|product)"
                    r"|packaged in (the )?(wrong|incorrect)"),
    ("missing_label_info", r"no labels?|without (a |any )?labels?|unlabeled|not labeled|not properly labeled"
                           r"|(missing|lacks?|lacking|no|without|does not (have|contain|include)|do not (have|contain|include))\s+(an?\s+|the\s+)?(ingredient|nutrition|english|allergen)"),
    ("claims", r"misbrand|\bclaims?\b"),
    ("undeclared_ingredient", DECLARE_PREFIX + r"\w+|did not list|not list(ed)? (the )?sub.?ingredients|phenylketon"),
    ("other", r"(?<!private )label"),
]
# Generic labeling details that are just the wording of an allergen recall
# ("mislabeled", "not on the label") rather than a separate labeling problem.
ALLERGEN_LABEL_WORDING = {"wrong_label", "missing_label_info", "claims", "undeclared_ingredient", "other"}

REGULATORY = [
    ("court_order", r"consent decree|injunction|court order|order of (permanent|preliminary)"),
]

# Generic microbial wording, used only when no specific pathogen is named.
GENERIC_MICROBIAL = r"(microbial|microbiological|bacterial)\s+contamination|contaminated with (bacteria|microorganisms)|microorganisms"

# Last resort: the recall only says an upstream ingredient was itself recalled.
SUPPLIER_RECALL = (
    r"(supplier|ingredient|raw material|flour|powder)\b.{0,120}\b(recall|recalled)\b"
    r"|\b(recall|recalled)\b.{0,60}\b(ingredient|flour|powder)|subject to .{0,60}recall"
)


def _compile(rules):
    return [(detail, re.compile(pattern, re.IGNORECASE)) for detail, pattern in rules]


# Order matters: allergen and foreign-material rules get stricter when an
# earlier category already matched (see CONTEXT), and it's also the priority
# order used by primary_category().
RULES = {
    "pathogen": _compile(PATHOGENS),
    "undeclared_allergen": _compile(ALLERGENS),
    "foreign_material": _compile(FOREIGN_MATERIALS),
    "chemical": _compile(CHEMICALS),
    "unapproved_drug": _compile(UNAPPROVED_DRUGS),
    "processing": _compile(PROCESSING),
    "temperature_abuse": _compile(TEMPERATURE),
    "sanitation": _compile(SANITATION),
    "labeling": _compile(LABELING),
    "regulatory_order": _compile(REGULATORY),
}
CATEGORY_PRIORITY = [*RULES, "supplier_recall"]
# Context each category needs. The strict version applies when the text is
# already about something else (a pathogen, or an allergen for foreign
# material), since that's when product names cause false matches; the loose
# version applies otherwise.
CONTEXT = {
    "undeclared_allergen": {
        "strict": re.compile(ALLERGEN_CONTEXT, re.IGNORECASE),
        "loose": re.compile(ALLERGEN_CONTEXT + r"|protein|contamina|positive for|trace", re.IGNORECASE),
    },
    "foreign_material": {
        "strict": re.compile(FOREIGN_CONTEXT, re.IGNORECASE),
        "loose": None,
    },
}
_GENERIC_ALLERGEN_RE = re.compile(GENERIC_ALLERGEN, re.IGNORECASE)
_GENERIC_MICROBIAL_RE = re.compile(GENERIC_MICROBIAL, re.IGNORECASE)
_SUPPLIER_RECALL_RE = re.compile(SUPPLIER_RECALL, re.IGNORECASE)


def tag_reason(text):
    """Return a sorted list of (category, detail) tags for a reason text."""
    if not text:
        return []
    tags = set()
    for category, rules in RULES.items():
        if category in CONTEXT:
            strict = bool(tags)  # an earlier category already matched
            context = CONTEXT[category]["strict" if strict else "loose"]
            if context is not None and not context.search(text):
                continue
        for detail, pattern in rules:
            if pattern.search(text):
                tags.add((category, detail))

    categories = {c for c, _ in tags}

    # Fall back to generic tags when nothing specific is named.
    if "undeclared_allergen" not in categories and _GENERIC_ALLERGEN_RE.search(text):
        tags.add(("undeclared_allergen", "unspecified"))
    if "pathogen" not in categories and _GENERIC_MICROBIAL_RE.search(text):
        tags.add(("pathogen", "unspecified"))

    # Labeling words in an allergen recall just describe the allergen problem.
    if "undeclared_allergen" in {c for c, _ in tags}:
        tags -= {("labeling", d) for d in ALLERGEN_LABEL_WORDING}

    # Drop catch-all details when a specific one in the same category matched.
    for category, catch_alls in (
        ("foreign_material", {"other"}),
        ("chemical", {"other"}),
        ("labeling", {"other", "undeclared_ingredient"}),
    ):
        details = {d for c, d in tags if c == category}
        if details - catch_alls:
            tags -= {(category, d) for d in catch_alls}

    if not tags and _SUPPLIER_RECALL_RE.search(text):
        tags.add(("supplier_recall", "unspecified"))
    return sorted(tags)


def primary_category(tags):
    """The single most important category, by CATEGORY_PRIORITY, or 'other'."""
    categories = {c for c, _ in tags}
    return next((c for c in CATEGORY_PRIORITY if c in categories), "other")

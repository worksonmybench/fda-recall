"""How a recall problem was found, and whether illnesses were reported.

Both come from `reason_for_recall`. The text is read clause by clause so
boilerplate ("Salmonella ... can cause serious and sometimes fatal
infections") and negations ("No illnesses have been reported") don't count.
"""

import re

# Clauses that talk about what *could* happen, or that deny something.
HYPOTHETICAL_RE = re.compile(
    r"\b(?:can|could|would|might|may cause|run the risk|risk of|if (?:they|consumed|eaten|ingested)|susceptible"
    r"|sometimes fatal|potentially fatal|life[- ]threatening|precaution\w*)\b",
    re.IGNORECASE,
)
NEGATION_RE = re.compile(r"\b(?:no|not|none|zero|nor|never|without)\b|n't\b", re.IGNORECASE)

ILLNESS_RE = re.compile(
    r"\billness(?:es)?\b|\bill\b|\bsick|hospitali[sz]|\bdeaths?\b|\bdied\b|outbreak|allergic reactions?"
    r"|adverse (?:events?|reactions?|effects?)|food ?poisoning|\bpatients?\b|\binfected\b|\binfections\b"
    r"|salmonellosis|listeriosis|botulism|scombroid|methemoglobin\w*|gastrointestinal|gastroenteritis"
    r"|epidemiolog\w*|vomit\w*|diarrh\w*|nausea|upset stomach|flushing (?:reaction|condition)|reactions? after",
    re.IGNORECASE,
)

# source -> pattern. A recall can have several sources.
SOURCES = {
    "illness_investigation": r"outbreak|epidemiolog|\bcdc\b|traceback|trace ?back|illness(?:es)? (?:linked|associated|reported)"
                             r"|linked to (?:illness|an outbreak|cases)|cases of \w*(?:osis|illness)|public health (?:officials|investigation)",
    "regulator_testing": r"(?:\bfda\b|\busda\b|\bstate\b|department|dept\.?|\bcfia\b|food inspection agency|agriculture|public health"
                         r"|health (?:department|dept)|\bnysdam\b|\bfdacs\b|\bmdard\b|\bcdph\b|\bodaf?\b|\bagency\b|regulatory|government)"
                         r"[^.;]{0,80}?(?:sampl|test|analy|lab\b|laborator|surveillance)"
                         r"|(?:sampl|test|analy)\w*[^.;]{0,40}?(?:by|from) (?:the )?(?:fda|usda|state|department|dept|cfia|agency)",
    # "Canadian Food Inspection Agency" / "Food Safety and Inspection Service" are names, not inspections
    "regulator_inspection": r"inspection(?!\s+(?:agency|service))|inspector|investigator|\b483\b|warning letter|(?:fda|state|department|dept\.?|agency)[^.;]{0,40}?(?:visit|audit|investigat)",
    "firm_testing": r"(?:firm|company|internal|routine|in-house|in house|finished product|environmental|our|its|their|third[- ]party|private lab)"
                    r"[^.;]{0,50}?(?:test|sampl|swab|analy|lab\b|laborator|verification|monitoring)"
                    r"|(?:test|sampl|swab)\w*[^.;]{0,30}?(?:by|from) (?:the )?(?:firm|company|manufacturer|customer|retailer|distributor)"
                    r"|metal detector|x-?ray",
    "customer_testing": r"(?:customer|retailer|distributor|consignee|buyer|importer|co-?packer)[^.;]{0,50}?(?:test|sampl|analy|lab\b|laborator)",
    "consumer_complaint": r"complain|consumer (?:report|contact|call|found|discovered|notified)|customer (?:report|found|discovered)"
                          r"|reported by (?:a )?(?:consumer|customer)|(?:consumer|customer) who",
    "supplier_notification": r"supplier|vendor|(?:ingredient|raw material)[^.;]{0,60}?recall|(?:notified|informed|advised) by (?:the |their |its )?"
                             r"(?:manufacturer|co-?packer|producer|grower|processor)|upstream|(?:manufacturer|co-?packer)[^.;]{0,30}?(?:notified|informed|recall)",
    "label_or_record_review": r"label review|review of (?:the )?label|labeling review|internal review|record review|review of records|audit"
                              r"|discovered (?:during|upon) (?:a )?review|noticed (?:that )?the label",
}
_SOURCE_RES = {k: re.compile(v, re.IGNORECASE) for k, v in SOURCES.items()}
# Regulator testing wins over "firm" wording that happens to be nearby, and
# customer testing is more specific than generic firm testing.
_OVERRIDES = [("regulator_testing", "firm_testing"), ("customer_testing", "firm_testing")]


def _clauses(text):
    # Split on sentence punctuation, but not inside abbreviations like "E. coli" / "L. mono".
    return re.split(r"(?<!\b[A-Za-z])[.;!?](?:\s+|$)|\n", text)


def illness_reported(text):
    """True if the reason text says illnesses/reactions actually occurred.

    Within each clause, anything after a hypothetical word ("can cause",
    "run the risk") is ignored, and an illness word preceded by a negation
    ("No illnesses have been reported") doesn't count.
    """
    if not text:
        return False
    for clause in _clauses(text):
        hypothetical = HYPOTHETICAL_RE.search(clause)
        factual = clause[: hypothetical.start()] if hypothetical else clause
        for m in ILLNESS_RE.finditer(factual):
            if not NEGATION_RE.search(factual[: m.start()]):
                return True
    return False


def detection_sources(text):
    """Return the sorted list of ways the problem was found, per the reason text."""
    if not text:
        return []
    found = set()
    for clause in _clauses(text):
        if NEGATION_RE.search(clause) and re.search(r"complain|illness|report", clause, re.IGNORECASE):
            clause = re.sub(r"\b(?:no|not|none|zero)\b[^.;]*", " ", clause, flags=re.IGNORECASE)
        for source, pattern in _SOURCE_RES.items():
            if pattern.search(clause):
                found.add(source)
    for keep, drop in _OVERRIDES:
        if keep in found:
            found.discard(drop)
    return sorted(found)

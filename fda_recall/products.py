"""Product category and UPC extraction from `product_description`.

Category: descriptions often carry ingredient lists and packaging details,
so we look only at the product *name* (the text before markers like
"Ingredients", "Net Wt", "UPC", "Packaged"...), find every food keyword in
it, and use the last one, since English product names end with the head
noun ("Chocolate Chip Cookie Dough Ice Cream", "Peanut Butter Cookies").
Multi-word keywords win over their parts ("peanut butter" over "butter").
"""

import re

# category -> keywords (regex fragments). Plurals are handled by the
# optional "s"/"es" added when compiling.
CATEGORIES = {
    "frozen_dessert": [
        "ice cream", "ice cream sandwich", "ice cream bar", "ice cream cone", "gelato", "sorbet", "sherbet",
        "frozen yogurt", "frozen dessert", "italian ice", "popsicle", "ice pop", "frozen confection", "soft serve",
        "ice cream mix", "shake mix", "frozen pops?", "dairy dessert", "frozen dairy dessert", "frozen custard", "sherbert",
    ],
    "dairy": [
        "milk", "cheese", "cheddar", "mozzarella", "parmesan", "brie", "feta", "ricotta", "queso", "cream cheese",
        "cottage cheese", "yogurt", "yoghurt", "kefir", "butter", "sour cream", "cream", "half and half",
        "creamer", "buttermilk", "ghee", "curds?", "paneer", "skyr", "egg ?nog", "requeson", "custard",
    ],
    "eggs": ["eggs?", "egg whites?", "liquid eggs?", "egg product", "shell eggs?"],
    "meat_poultry": [
        "chicken", "turkey", "beef", "pork", "ham", "bacon", "sausage", "salami", "pepperoni", "jerky", "meatballs?",
        "hot dogs?", "franks", "bologna", "prosciutto", "chorizo", "lamb", "venison", "bison", "duck", "meat",
        "mortadella", "pate", "chicharron", "capicol+a", "coppa", "soppressata",
    ],
    "seafood": [
        "fish", "salmon", "tuna", "shrimp", "prawns?", "crab", "lobster", "oysters?", "clams?", "mussels?",
        "scallops?", "sardines?", "anchov(y|ies)", "cod", "tilapia", "catfish", "mackerel", "herring", "trout",
        "pollock", "halibut", "swordfish", "snapper", "squid", "octopus", "caviar", "roe", "seafood", "surimi",
        "fish balls?", "smoked fish", "seaweed", "crawfish", "bonito", "oyster meat", "crab ?meat", "lobster meat",
        "clam meat", "fillets?", "whiting", "flounder", "sole", "mahi mahi", "grouper",
    ],
    "produce": [
        "lettuce", "romaine", "spinach", "kale", "arugula", "cabbage", "salad mix", "salad kit", "garden salad",
        "spring mix", "greens", "leafy greens", "sprouts", "cilantro", "parsley", "basil", "herbs?",
        "onions?", "tomato(es)?", "peppers?", "jalapenos?", "cucumbers?", "carrots?", "celery", "broccoli",
        "cauliflower", "zucchini", "squash", "corn", "peas", "green beans?", "potato(es)?", "sweet potato(es)?",
        "mushrooms?", "garlic", "ginger", "avocados?", "vegetables?", "veggies?", "stir fry", "coleslaw mix",
        "cantaloupes?", "melons?", "honeydew", "watermelon", "papayas?", "mangos?|mangoes", "pineapples?",
        "apples?", "pears?", "peaches", "peach", "nectarines?", "plums?", "cherries", "cherry", "grapes?",
        "berries", "strawberries", "blueberries", "raspberries", "blackberries", "cranberries", "bananas?",
        "oranges?", "lemons?", "limes?", "citrus", "kiwi", "pomegranate arils?", "fruit", "fruit mix",
        "fruit cup", "fruit salad", "cut fruit", "fresh cut", "florets", "cactus", "nopales", "okra", "leeks?",
        "scallions?", "green onions?", "shallots?", "radish(es)?", "beets?", "edamame", "peas and carrots",
        "mixed vegetables?", "salad", "salads", "apricots?", "figs?", "persimmons?", "guavas?", "tamarind", "pumpkins?", "fajita blend", "cacao nibs",
    ],
    "nuts_seeds": [
        "nuts?", "peanuts?", "almonds?", "walnuts?", "pecans?", "cashews?", "pistachios?", "hazelnuts?",
        "macadamias?", "pine nuts?", "brazil nuts?", "trail mix", "nut mix", "mixed nuts", "seeds?",
        "sunflower seeds?", "pumpkin seeds?", "chia", "flax(seed)?", "sesame seeds?", "peanut butter",
        "almond butter", "nut butter", "cashew butter", "sunflower butter", "tahini", "hemp hearts",
    ],
    "bakery": [
        "bread", "breads", "loaf", "loaves", "rolls?", "buns?", "bagels?", "croissants?", "muffins?", "cakes?",
        "cupcakes?", "cheesecakes?", "pies?", "tarts?", "pastr(y|ies)", "danish", "donuts?", "doughnuts?",
        "brownies?", "cookies?", "biscuits?", "scones?", "tortillas?", "pita", "naan", "flatbreads?",
        "baguettes?", "bialys?", "english muffins?", "cinnamon rolls?", "cookie dough", "pizza dough", "dough",
        "coffee cake", "pound cake", "stollen", "baklava", "macarons?", "eclairs?", "strudel", "churros?",
        "waffles?", "pancakes?", "crepes?", "texas toast", "croutons?", "stuffing", "bakery", "sourdough",
        "pizza crusts?", "pie crusts?", "conchas?", "pan dulce", "desserts?", "turnovers?", "empanadillas?",
    ],
    "snacks": [
        "chips", "crisps", "crackers?", "pretzels?", "popcorn", "snack mix", "snacks?", "puffs", "rice cakes?",
        "granola bars?", "protein bars?", "snack bars?", "bars?", "energy bites", "trail bars?", "pork rinds",
        "tortilla chips", "potato chips", "cheese puffs", "plantain chips", "fruit snacks", "fruit leather",
        "dried fruit", "raisins", "dates", "dried (mango|apricots?|cranberries|cherries|apples?)",
    ],
    "candy_chocolate": [
        "candy", "candies", "chocolates?", "truffles?", "fudge", "toffee", "caramels?", "confection(s|ery)?",
        "gum", "gummies", "gummy", "lollipops?", "marshmallows?", "mints", "jelly beans", "licorice", "brittle",
        "bonbons?", "pralines?", "nougat", "halva", "chocolate bars?", "cocoa", "chocolate covered", "espresso beans",
        "coffee beans chocolate",
    ],
    "grains_pasta_cereal": [
        "cereal", "granola", "oats", "oatmeal", "flour", "rice", "pasta", "noodles?", "spaghetti", "macaroni",
        "ravioli", "tortellini", "gnocchi", "lasagna", "couscous", "quinoa", "grains?", "cornmeal", "grits",
        "polenta", "masa", "baking mix", "pancake mix", "cake mix", "muffin mix", "bread mix", "mix",
        "wheat germ", "bran", "barley", "tofu", "tempeh", "beans", "lentils", "chickpeas", "legumes",
    ],
    "spices_seasonings": [
        "spices?", "seasonings?", "cumin", "paprika", "turmeric", "cinnamon", "oregano", "black pepper",
        "ground pepper", "chili powder", "curry", "garlic powder", "onion powder", "rub", "salt", "masala",
        "coriander", "nutmeg", "cloves", "cardamom", "saffron", "fenugreek", "sumac", "za'?atar", "bay leaves",
        "dried herbs", "herb blend", "spice blend", "seasoning mix", "breader", "breading", "batter mix", "batter mx", "bttr mx",
        "marinade mix", "extract", "vanilla",
    ],
    "sauces_condiments": [
        "sauces?", "dressings?", "salsas?", "dips?", "hummus", "guacamole", "pesto", "ketchup", "mayonnaise",
        "mayo", "mustard", "relish", "spreads?", "jam", "jams", "jelly", "jellies", "preserves", "marmalade",
        "honey", "syrups?", "vinegar", "oils?", "olive oil", "marinades?", "gravy", "soy sauce", "hot sauce",
        "sriracha", "chutney", "pickles?", "olives", "kimchi", "sauerkraut", "tapenade", "aioli", "glaze",
        "icing", "frosting", "fillings?", "toppings?", "condiments?", "bouillon", "broth", "stock", "paste",
        "miso", "fish sauce", "pico de gallo", "tzatziki", "queso dip", "cheese dip", "peanut sauce",
    ],
    "beverages": [
        "juices?", "water", "sparkling water", "spring water", "soda", "tea", "teas", "coffee", "drinks?",
        "beverages?", "lemonade", "kombucha", "smoothies?", "cider", "energy drink", "sports drink", "cold brew",
        "almond milk", "oat milk", "soy milk", "rice milk", "coconut water", "coconut milk", "shakes?",
        "nectar", "punch", "ginger beer", "drink mix", "cocktail mix", "mixer", "horchata", "latte",
    ],
    # Bare "formula" is often a recipe code ("Salsa, Formula SA.40") and bare
    # "baby" a size ("Baby Spinach", "baby carrots"), so only specific infant
    # wording and the big formula / baby food brands count.
    "infant_formula_baby_food": [
        "infant formula", "baby formula", "infant milk formula", "follow-on formula", "toddler formula",
        "infant milk", "baby food", "baby cereal", "baby cookies", "baby snacks?", "baby puffs", "infant cereal",
        "toddler", "teething", "for babies", "similac", "enfamil",
        "elecare", "alimentum", "nutramigen", "pediasure", "gerber",
    ],
    "dietary_supplements": [
        "supplements?", "dietary supplements?", "capsules?", "caps", "tablets?", "softgels?", "vitamins?",
        "multivitamins?", "probiotics?", "protein powder", "whey protein", "powder", "drops", "tinctures?",
        "kratom", "herbal", "extract capsules", "gummies vitamins?", "hcg", "pre-?workout", "fat burner",
        "weight loss", "enzymes?", "collagen", "fish oil", "omega-?3", "elixir", "botanical", "protein", "bee pollen", "ferrous", "iron", "zinc", "magnesium", "calcium", "melatonin", "biotin",
    ],
    "prepared_foods": [
        "sandwich(es)?", "wraps?", "burritos?", "tacos?", "quesadillas?", "enchiladas?", "tamales?", "pizzas?",
        "calzones?", "soups?", "chili", "stew", "entrees?", "meals?", "dinners?", "bowls?", "kits?",
        "dumplings?", "pot ?stickers?", "egg rolls?", "spring rolls?", "sushi", "empanadas?", "pierogi",
        "samosas?", "casseroles?", "quiche", "lunch kits?", "snack packs?", "trays?", "platters?",
        "potato salad", "pasta salad", "macaroni salad", "chicken salad", "tuna salad", "egg salad",
        "ham salad", "seafood salad", "crab salad", "cole ?slaw", "slaw", "deli salads?", "macaroni and cheese",
        "mac (and|&) cheese", "fried rice", "spring roll", "set ups?", "hoagies?", "subs?", "paninis?",
        "flatbread pizza", "pizza kit", "meal kit", "ready meals?", "frozen meals?", "pot pies?", "nuggets",
        "tenders", "patt(y|ies)", "burgers?", "cheeseburgers?", "ravioli bake", "lasagna", "frittata",
        "cobb salad", "caesar salad", "chef salad", "grab and go", "bento", "california rolls?", "sushi rolls?",
        "onion rings", "heros?", "heroes", "cheesesteaks?", "sliders?", "noodle bowls?", "rice bowls?",
    ],
}
# When two categories tie (can't happen with last-match, but for fallbacks)
# this order decides; also the order of the category list in the README.
CATEGORY_ORDER = list(CATEGORIES)

# Where the product name ends and the rest of the description starts.
NAME_END_RE = re.compile(
    r"ingredients?\b|net\.?\s*w(?:t|eight)|\bnet\s+\d|\bupc\b|\bsku\b|\bitem\s*(?:#|no|number|code)|packaged\b|packed\b"
    r"|distributed\b|manufactured\b|made (?:by|for|in)\b|keep\s+(?:refrigerated|frozen)|sold\s+(?:in|under|as)\b"
    r"|product of\b|contains\b|\s(?:is|are|was|were|has|have)\s|\bin (?:a |an )?(?:clear |plastic |glass |paper )?(?:bags?|boxes|bottles?|jars?|cans?|tubs?|cups?|containers?|trays?|cartons?|pouch(?:es)?)\b"
    r"|\d+(?:\.\d+)?\s*(?:oz|lb|lbs|g|kg|ml|fl)\b|\bexp(?:iration)?\b|\bbest by\b|\blot\b|\s[-–]\s",
    re.IGNORECASE,
)


def _compile_keywords():
    entries = [(kw, cat) for cat, kws in CATEGORIES.items() for kw in kws]
    # Longest literal first so "peanut butter" is tried before "butter".
    entries.sort(key=lambda e: len(re.sub(r"[^a-z ]", "", e[0])), reverse=True)
    pattern = "|".join(f"(?P<k{i}>{kw})" for i, (kw, _) in enumerate(entries))
    regex = re.compile(rf"(?<![a-z])(?:{pattern})(?:s|es)?(?![a-z])", re.IGNORECASE)
    return regex, [cat for _, cat in entries]


_KEYWORD_RE, _KEYWORD_CATEGORY = _compile_keywords()
_INFANT_RE = re.compile(
    r"(?<![a-z])(?:" + "|".join(CATEGORIES["infant_formula_baby_food"]) + r")(?![a-z])", re.IGNORECASE
)


def product_name(description):
    """The leading product-name part of a description."""
    if not description:
        return ""
    first_line = description.split("\n", 1)[0]
    m = NAME_END_RE.search(first_line)
    name = first_line[: m.start()] if m and m.start() > 0 else first_line
    # Stop at the first sentence break, drop parenthetical notes, and cut
    # "X with Y" / "X in Y" / "X on Y" down to X ("Juice with Vitamin C").
    name = re.split(r"[.;:](?:\s|$)", name, maxsplit=1)[0]
    name = re.sub(r"\([^)]*\)?", " ", name)
    return re.split(r"\s(?:with|w/|in|on|over|topped)\s", name, maxsplit=1, flags=re.IGNORECASE)[0]


def _matches(text):
    for m in _KEYWORD_RE.finditer(text):
        idx = int(m.lastgroup[1:])
        yield m, _KEYWORD_CATEGORY[idx]


def product_category(description):
    """Best-guess food category for a product description, or None."""
    if not description:
        return None
    name = product_name(description)
    if _INFANT_RE.search(name):  # "EleCare ... Nutrition Powder" is formula, not a supplement
        return "infant_formula_baby_food"
    matches = list(_matches(name))
    if matches:
        return matches[-1][1]  # head noun is last
    # Nothing in the name: fall back to the first keyword anywhere (before
    # any ingredient list, which tends to come later).
    before_ingredients = re.split(r"ingredients?\s*:", description, maxsplit=1, flags=re.IGNORECASE)[0]
    for text in (before_ingredients, description):
        for _, category in _matches(text):
            return category
    return None


# --- UPCs ----------------------------------------------------------------

# "UPC 7-01248-00100-1", "UPC: 8 58950 00508 6", "UPC#: 0 12345 67890 5 and 0 12345 67891 2"
_UPC_LABEL_RE = re.compile(r"\bupc(?:\s*(?:code|number|no\.?|#|s|/\s*plu))*\s*[:#.\-]?\s*", re.IGNORECASE)
_DIGIT_RUN_RE = re.compile(r"\d(?:[\d\s\-]*\d)?")
# A bare 12/13-digit number is only trusted if its check digit is valid.
_NOT_UPC_LABEL_RE = re.compile(r"\b(?:lot|code|item|sku|batch|plu|ndc|order|invoice|po)\b[^a-z]*$", re.IGNORECASE)
_BARE_RE = re.compile(r"(?<![\d\-])(\d{12,13})(?![\d\-])")


def _valid_check_digit(code):
    digits = [int(d) for d in code]
    body, check = digits[:-1], digits[-1]
    # weights 3,1,3,1... from the right of the body
    total = sum(d * (3 if i % 2 == 0 else 1) for i, d in enumerate(reversed(body)))
    return (10 - total % 10) % 10 == check


def find_upcs(description):
    """Return the sorted UPC/EAN codes (digits only) in a description."""
    if not description:
        return []
    found = set()
    for label in _UPC_LABEL_RE.finditer(description):
        # Read a list of codes after the label: "UPC 123..., 456... & 789..."
        pos = label.end()
        while True:
            m = _DIGIT_RUN_RE.match(description, pos)
            if not m:
                break
            digits = re.sub(r"\D", "", m[0])
            # A run can swallow a trailing size ("... 1 24 oz"); take the
            # longest 8-14 digit prefix of dash/space groups.
            if 8 <= len(digits) <= 14:
                found.add(digits)
            elif len(digits) > 14:
                groups = re.split(r"[\s\-]+", m[0])
                acc = ""
                for g in groups:
                    if len(acc + g) > 14:
                        break
                    acc += g
                if 8 <= len(acc) <= 14:
                    found.add(acc)
            sep = re.match(r"\s*(?:,|;|/|&|\band\b|\bor\b)\s*(?:upc\s*[:#]?\s*)?", description[m.end():], re.IGNORECASE)
            if not sep:
                break
            pos = m.end() + sep.end()
    for m in _BARE_RE.finditer(description):
        preceding = description[max(0, m.start() - 15):m.start()]
        if _valid_check_digit(m[1]) and not _NOT_UPC_LABEL_RE.search(preceding):
            found.add(m[1])
    return sorted(found)

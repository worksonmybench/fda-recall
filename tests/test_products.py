import unittest

from fda_recall.products import find_upcs, product_category


class ProductCategoryTests(unittest.TestCase):
    def assertCategory(self, description, category):
        self.assertEqual(product_category(description), category, description)

    def test_head_noun_wins(self):
        self.assertCategory("Chocolate Chip Cookie Dough Ice Cream", "frozen_dessert")
        self.assertCategory("SE Grocers **BAKERY** 18 CT Peanut Butter Cookies", "bakery")
        self.assertCategory("Fresh Creative Cuisine White Label, Turkey, Sausage, Egg, & Fontina Bialy, Net Wt. 5.5 Oz.", "bakery")
        self.assertCategory("Chicken Salad Sandwich", "prepared_foods")
        self.assertCategory("Pepperidge Farm Goldfish Baked Snack Crackers, 30 Packs.", "snacks")

    def test_ingredients_and_packaging_are_ignored(self):
        self.assertCategory("Tomato Salsa Fresca. Ingredients: Tomatoes, Yellow Onion, Milk", "sauces_condiments")
        self.assertCategory("Hot Smoked Pink Salmon is Low salt, vacuum packaged.", "seafood")
        self.assertCategory("365 Organic 100% Apple Juice from concentrate with Vitamin C and Calcium", "beverages")
        self.assertCategory("Refrigerated, Ready to Eat Herring Fillets in Oil Lightly Salted", "seafood")
        self.assertCategory("Olive Bread (Kalamata olives), Bosket Bread brand", "bakery")

    def test_size_words_and_codes_are_not_categories(self):
        self.assertCategory("Private Selections Organic Baby Spinach,", "produce")
        self.assertCategory("Wawa baby carrots", "produce")
        self.assertCategory("-Reser's Baja Cafe Margarita Salsa, Formula SA.40 packaged", "sauces_condiments")

    def test_infant_formula(self):
        self.assertCategory("HiPP German Stage 2 Combiotic Follow-on Infant Milk Formula", "infant_formula_baby_food")
        self.assertCategory("Abbott EleCare Jr Amino Acid-Based Nutrition Powder Unflavored", "infant_formula_baby_food")
        self.assertCategory("Plum Organics Pumpkin & Banana Organic Baby Food,", "infant_formula_baby_food")

    def test_unknown(self):
        self.assertIsNone(product_category(None))
        self.assertIsNone(product_category("CardioAdvance"))


class FindUpcsTests(unittest.TestCase):
    def test_labelled_codes(self):
        self.assertEqual(find_upcs("Shaved Ham & Cheese, UPC 7-01248-00100-1, MFG Code 101"), ["701248001001"])
        self.assertEqual(find_upcs("Cookies UPC: 8 58950 00508 6 Ingredients"), ["858950005086"])
        self.assertEqual(
            find_upcs("3 oz, UPC 74690-028590; and 8 oz., UPC 74690-231556."), ["74690028590", "74690231556"]
        )
        self.assertEqual(find_upcs("UPC/PLU 25179600000"), ["25179600000"])

    def test_bare_codes_need_a_valid_check_digit(self):
        self.assertEqual(find_upcs("Gourmet Junior Burger Roll 12-pack (033474501308)"), ["033474501308"])
        self.assertEqual(find_upcs("Burger Roll (033474501309)"), [])  # bad check digit
        self.assertEqual(find_upcs("Lot 123456789012 exp 2020"), [])  # a lot number

    def test_none(self):
        self.assertEqual(find_upcs("UPC: N/A"), [])
        self.assertEqual(find_upcs(None), [])


if __name__ == "__main__":
    unittest.main()

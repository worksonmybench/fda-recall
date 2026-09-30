import unittest

from fda_recall.reasons import primary_category, tag_reason


class TagReasonTests(unittest.TestCase):
    def assertTags(self, text, expected):
        self.assertEqual(tag_reason(text), sorted(expected))

    def test_pathogens(self):
        self.assertTags("Product may be contaminated with Listeria monocytogenes.", [("pathogen", "listeria")])
        self.assertTags("Conveyor belt tested positive for L. mono.", [("pathogen", "listeria")])
        self.assertTags("Potential contamination with E. coli O157:H7", [("pathogen", "e_coli")])
        self.assertTags("Potential contamination with B. cepacia.", [("pathogen", "burkholderia")])

    def test_allergens(self):
        self.assertTags("Undeclared milk and soy.", [("undeclared_allergen", "milk"), ("undeclared_allergen", "soy")])
        self.assertTags("Jams made with butter which is not declared on the label.", [("undeclared_allergen", "milk")])
        self.assertTags("Peanut butter cups contain undeclared egg.", [("undeclared_allergen", "egg"), ("undeclared_allergen", "peanut")])
        self.assertTags("Bubble tea powders contain undeclared allergens.", [("undeclared_allergen", "unspecified")])
        self.assertTags("Possible Peanut Protein contamination.", [("undeclared_allergen", "peanut")])

    def test_foreign_material(self):
        self.assertTags("Potential for metal in product", [("foreign_material", "metal")])
        self.assertTags("Frozen pizza crust may contain foreign material (glass).", [("foreign_material", "glass")])
        self.assertTags("Pieces of a pen (writing utensil); foreign material.", [("foreign_material", "other")])

    def test_product_names_and_packaging_are_not_tagged(self):
        self.assertTags('"Wood-Ear" mushroom tested positive for Salmonella.', [("pathogen", "salmonella")])
        self.assertTags("Cherry tomatoes in a plastic clamshell, potential Salmonella.", [("pathogen", "salmonella")])
        self.assertTags(
            'Hot Smoked Salmon is not labeled "KEEP FROZEN" and may be contaminated with Clostridium botulinum.',
            [("labeling", "missing_label_info"), ("pathogen", "c_botulinum")],
        )
        self.assertTags("Cold smoked steelhead recalled due to Listeria monocytogenes.", [("pathogen", "listeria")])
        self.assertTags("Spring water in glass bottles recalled because arsenic was detected.", [("chemical", "heavy_metal")])
        self.assertTags("Soy Protein Isolate which may be contaminated with Salmonella.", [("pathogen", "salmonella")])
        self.assertTags("Pasteurized liquid whole eggs tested positive for Salmonella.", [("pathogen", "salmonella")])
        self.assertTags("Dole is withdrawing all private label salads.", [])
        self.assertTags("Early Bird Foods granola contains undeclared milk.", [("undeclared_allergen", "milk")])

    def test_other_categories(self):
        self.assertTags("Products not manufactured under GMP's", [("sanitation", "gmp")])
        self.assertTags("Product was improperly pasteurized.", [("processing", "pasteurization")])
        self.assertTags("Canned shrimp may be under-processed", [("processing", "under_processing")])
        self.assertTags("Elevated histamine levels.", [("chemical", "histamine")])
        self.assertTags("Undeclared Yellow #5", [("labeling", "undeclared_color")])
        self.assertTags(
            "Products were not held at an appropriate temperature due to a mechanical malfunction.",
            [("temperature_abuse", "temperature_abuse")],
        )
        self.assertTags("Product contains the unapproved ingredient, picamilon.", [("unapproved_drug", "unapproved_ingredient")])
        self.assertTags("Potential microbial contamination", [("pathogen", "unspecified")])

    def test_labeling_wording_in_allergen_recalls_is_not_double_counted(self):
        self.assertTags("Product mislabeled; undeclared egg.", [("undeclared_allergen", "egg")])

    def test_primary_category(self):
        self.assertEqual(primary_category(tag_reason("Undeclared milk; Listeria monocytogenes found.")), "pathogen")
        self.assertEqual(primary_category([]), "other")

    def test_empty(self):
        self.assertEqual(tag_reason(None), [])
        self.assertEqual(tag_reason("Sharp product: reach"), [])


if __name__ == "__main__":
    unittest.main()

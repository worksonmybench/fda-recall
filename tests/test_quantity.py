import unittest

from fda_recall.quantity import event_units, parse_quantity, size_bucket


class ParseQuantityTests(unittest.TestCase):
    def assertParses(self, text, units, unit_type, is_total=False):
        parsed = parse_quantity(text)
        self.assertIsNotNone(parsed, text)
        self.assertAlmostEqual(parsed[0], units, places=1, msg=text)
        self.assertEqual(parsed[1:], (unit_type, is_total), text)

    def test_simple_units(self):
        self.assertParses("9,392 packages", 9392, "each")
        self.assertParses("3411 cases", 3411 * 12, "case")
        self.assertParses("52 lbs.", 52, "weight")
        self.assertParses("4000 pounds", 4000, "weight")
        self.assertParses("3000 kg", 3000 * 2.2046, "weight")
        self.assertParses("8092 OZ", 8092 / 16, "weight")
        self.assertParses("Approx 19.5 gallons", 19.5 * 8.34, "volume")
        self.assertParses("approximately 1.2 million lbs", 1_200_000, "weight")
        self.assertParses("10693", 10693, "each")

    def test_totals(self):
        self.assertParses("OH/CA Total Distributed Combined: 578,243 cases", 578_243 * 12, "case", True)
        self.assertParses("12,898 lbs (total of all products)", 12_898, "weight", True)
        self.assertParses("(Total Quantity: 607)", 607, "each", True)

    def test_multiple_amounts_are_added(self):
        self.assertParses("528,250 lbs.(US) Canada 21,700 lbs (OUS)", 549_950, "weight")
        self.assertParses("1-lb: 500 bags, 2-lb: 350 bags, 10-lb: 60 bags", 910, "each")

    def test_pack_sizes_are_not_amounts(self):
        self.assertParses("500 12-oz bottles", 500, "each")
        self.assertParses("93cs/12/23oz package", 93 * 12, "case")
        self.assertParses("1,221 cases (6/2 lb. bags per case)", 1221 * 6, "case")
        self.assertParses("5,556/2 lb mesh bags + 44/40lb boxes", 5600, "each")
        self.assertParses("12 x 14 oz. plastic jars: 300 cases", 300 * 12, "case")
        self.assertParses("1,000 Bottles (90,000 capsules)", 1000, "each")
        self.assertParses("20,000 lbs of product", 20_000, "weight")

    def test_stated_units_per_container(self):
        self.assertParses("424 boxes (54 units each)", 424 * 54, "each")
        self.assertParses("126 cases, 144 units per case", 126 * 144, "case")
        self.assertParses("1462 cases (12/case)", 1462 * 12, "case")
        self.assertParses("147 cases of 12 units", 147 * 12, "case")
        self.assertParses("558 cases (120 bars in each case)", 558 * 120, "case")
        self.assertParses("689 Cases (each case has 24 cans (4oz each))", 689 * 24, "case")
        self.assertParses("13,457 cases (1 case = 42 twice baked potatoes at 5 oz each)", 13457 * 42, "case")
        self.assertParses("2449 Cases x 6 bags of 7.6 oz each", 2449 * 6, "case")
        self.assertParses("2,267 cases (6-50oz units/case)", 2267 * 6, "case")
        self.assertParses("4 pallets at 1344 canisters per pallet", 4 * 1344, "case")

    def test_weight_per_container(self):
        self.assertParses("2 cases (5 pounds each)", 10, "case")
        self.assertParses("2,603 cases (20 lbs/case)", 2603 * 20, "case")
        # a small "oz each" is the size of each unit, so the default 12 per case applies
        self.assertParses("56 cases, 1792 pouches, 1.2 oz each", 56 * 12, "case")

    def test_stated_unit_total_for_cases(self):
        self.assertParses("179 cases (1,432 bottles)", 1432, "each")
        self.assertParses("653 cases (5,224 retail units)", 5224, "each")

    def test_multiplied_counts(self):
        self.assertParses("2,166 x 16 oz", 2166, "each")
        self.assertParses("41,436 x 6 x 5 lb", 41436 * 6, "each")
        self.assertParses("86,817 20 x 16 oz", 86817 * 20, "each")

    def test_things_that_are_not_pack_counts(self):
        self.assertParses("20,520 each", 20520, "each")
        self.assertParses("8232 bottles of 40 count", 8232, "each")  # 40 pills per bottle
        self.assertParses("477 containers each weighing 44.092 lbs", 477, "each")
        self.assertParses("10 pallets - 6x 4 pks per case,", 10 * 600, "case")  # per case, not per pallet
        self.assertParses("24,100 Pounds 9964 x 25 lb. boxes)", 24100, "weight")

    def test_identifiers_are_not_amounts(self):
        self.assertParses("Lot# 100420218 = 23,223", 23_223, "each")
        self.assertParses("UPC 012345678905: 300 cases", 3600, "case")

    def test_unparseable(self):
        for text in [None, "", "Unknown", "will be provided"]:
            self.assertIsNone(parse_quantity(text))


class SizeTests(unittest.TestCase):
    def test_buckets(self):
        self.assertIsNone(size_bucket(None))
        self.assertEqual(size_bucket(0), "XS")
        self.assertEqual(size_bucket(99), "XS")
        self.assertEqual(size_bucket(100), "S")
        self.assertEqual(size_bucket(9_999), "M")
        self.assertEqual(size_bucket(50_000), "L")
        self.assertEqual(size_bucket(999_999), "XL")
        self.assertEqual(size_bucket(206_749_248), "XXL")

    def test_event_units(self):
        def parsed(*texts):
            return [(t, parse_quantity(t)) for t in texts]

        # separate per-product amounts are added
        self.assertEqual(event_units(parsed("11 cases", "8 cases")), 19 * 12)
        # the same total copied onto every product counts once
        self.assertEqual(event_units(parsed(*["400 cases (total)"] * 6)), 400 * 12)
        # a stated total wins over a smaller sum of per-product amounts
        self.assertEqual(event_units(parsed("100 units", "5,000 units total for all products")), 5000)
        self.assertIsNone(event_units(parsed("Unknown", None)))


if __name__ == "__main__":
    unittest.main()

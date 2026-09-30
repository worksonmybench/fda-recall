import unittest

from fda_recall.distribution import parse_distribution


class ParseDistributionTests(unittest.TestCase):
    def assertParses(self, text, states, nationwide=False, foreign=False, online=False):
        self.assertEqual(parse_distribution(text), (sorted(states), nationwide, foreign, online), text)

    def test_code_lists(self):
        self.assertParses("IL, MI, KY, IN, WI", ["IL", "MI", "KY", "IN", "WI"])
        self.assertParses("ME VT NH MA RI CT NY PA", ["ME", "VT", "NH", "MA", "RI", "CT", "NY", "PA"])
        self.assertParses("Distributed in ID, OR and WA.", ["ID", "OR", "WA"])
        self.assertParses("NY", ["NY"])
        self.assertParses("TX, Ok, KS", ["TX", "OK", "KS"])

    def test_full_names(self):
        self.assertParses("New Jersey, New York, Rhode Island, and Maryland", ["NJ", "NY", "RI", "MD"])
        self.assertParses("West Virginia and Virginia", ["WV", "VA"])
        self.assertParses("Kansas and Arkansas", ["KS", "AR"])
        self.assertParses("Washington, D.C. and Maryland", ["DC", "MD"])
        self.assertParses("Iowa Illinois Indiana Missouri Wisconsin", ["IA", "IL", "IN", "MO", "WI"])

    def test_word_like_codes_are_not_misread(self):
        self.assertParses("sold in CA, or NV", ["CA", "NV"])
        self.assertParses("DISTRIBUTED IN CA AND NV", ["CA", "NV"])
        self.assertParses("DISTRIBUTED TO: IN, OH, MI", ["IN", "OH", "MI"])

    def test_nationwide(self):
        self.assertParses("Nationwide", [], nationwide=True)
        self.assertParses("Product was distributed nationwide.", [], nationwide=True)
        self.assertParses("Nationwide. AZ, CA, CO", ["AZ", "CA", "CO"], nationwide=True)
        self.assertParses("All US States: AL, AZ, CA", ["AL", "AZ", "CA"])
        self.assertParses("Product is distributed worldwide.", [], nationwide=True, foreign=True)

    def test_online_sales_count_as_nationwide(self):
        self.assertParses("Product was only sold on the internet.", [], nationwide=True, online=True)
        self.assertParses("Direct online sales to customers.", [], nationwide=True, online=True)
        self.assertParses("Texas and internet sales", ["TX"], nationwide=True, online=True)
        self.assertParses("distributed in WA and sold on company website https://www.example.com.", ["WA"], nationwide=True, online=True)
        self.assertParses("Distributed nationwide and via amazon.com", [], nationwide=True, online=True)
        self.assertParses("Distributed in Oregon and sold through mail orders.", ["OR"], nationwide=True, online=True)
        # Amazon's physical / local-delivery businesses are local retail
        self.assertParses("Distributed through Amazon Fresh in the Bellevue, Washington area.", ["WA"])
        self.assertParses("Whole Foods distribution to CA and CO DC's. 6 Amazon stores in CA.", ["CA", "CO"])

    def test_foreign(self):
        self.assertParses("distributed in AZ, CA and in Canada.", ["AZ", "CA"], foreign=True)
        self.assertParses("Texas and Mexico", ["TX"], foreign=True)
        self.assertParses("New Mexico", ["NM"])
        self.assertParses("Domestic: AL, AR, FL. Foreign: Not applicable.", ["AL", "AR", "FL"])
        self.assertParses("U.S. distribution to the following; CA, NY. No foreign distribution.", ["CA", "NY"])
        self.assertParses("PR and USVI", ["PR"])

    def test_empty(self):
        self.assertParses(None, [])
        self.assertParses("Domestic distribution only.", [])


if __name__ == "__main__":
    unittest.main()

import unittest

from fda_recall.detection import detection_sources, illness_reported


class IllnessTests(unittest.TestCase):
    def test_reported_illness(self):
        for text in [
            "CDC epidemiologists have linked an outbreak of Listeria monocytogenes illness to caramel apples.",
            "Product associated with scombroid illness.",
            "Firm received consumer complaint of an allergic reaction after consumption.",
            "Product is linked to an outbreak of E. coli O157, which could cause serious illness.",
        ]:
            self.assertTrue(illness_reported(text), text)

    def test_boilerplate_and_negations_are_not_illness(self):
        for text in [
            "Product may be contaminated with Salmonella, an organism which can cause serious and sometimes fatal infections.",
            "Consumers with a milk allergy run the risk of serious or life-threatening allergic reaction if they consume these products.",
            "No illnesses, injury or complaints reported due that the product is positive for Salmonella.",
            "The firm has not received any reports of illness to date.",
            "Two samples collected from tuna with reported high levels of scombrotoxin.",
            None,
        ]:
            self.assertFalse(illness_reported(text), text)


class DetectionSourceTests(unittest.TestCase):
    def assertSources(self, text, sources):
        self.assertEqual(detection_sources(text), sorted(sources), text)

    def test_sources(self):
        self.assertSources("FDA sampling found Listeria monocytogenes in the product.", ["regulator_testing"])
        self.assertSources("Firm was notified by supplier that the flour was recalled due to E. coli.", ["supplier_notification"])
        self.assertSources("The firm's routine finished product testing found Salmonella.", ["firm_testing"])
        self.assertSources("Consumer complaints of black plastic found in product.", ["consumer_complaint"])
        self.assertSources(
            "During an inspection by the Ohio Department of Agriculture, metal fragments were found.", ["regulator_inspection"]
        )
        self.assertSources(
            "CDC epidemiologists have linked an outbreak of Listeria monocytogenes illness to caramel apples.",
            ["illness_investigation"],
        )

    def test_agency_names_are_not_inspections(self):
        self.assertSources(
            "Canadian Food Inspection Agency tested blueberries and found Cyclospora.", ["regulator_testing"]
        )

    def test_denied_complaints_do_not_count(self):
        self.assertSources("Product tested positive for Salmonella. No complaints have been received.", [])

    def test_unknown(self):
        self.assertSources("Undeclared milk.", [])
        self.assertSources(None, [])


if __name__ == "__main__":
    unittest.main()

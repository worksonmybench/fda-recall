// Display names for the category keys used in the data.
export const LABELS = {
  // recall reasons
  pathogen: "Pathogen", undeclared_allergen: "Undeclared allergen", foreign_material: "Foreign material",
  processing: "Processing / spoilage", labeling: "Other labeling", chemical: "Chemical contaminant",
  sanitation: "Sanitation / GMP", temperature_abuse: "Temperature abuse", unapproved_drug: "Unapproved drug",
  supplier_recall: "Supplier recall", regulatory_order: "Court order", other: "Other / unclear",
  // product categories
  produce: "Produce", bakery: "Bakery", prepared_foods: "Prepared foods", dairy: "Dairy",
  sauces_condiments: "Sauces & condiments", dietary_supplements: "Dietary supplements",
  grains_pasta_cereal: "Grains, pasta & cereal", spices_seasonings: "Spices & seasonings",
  nuts_seeds: "Nuts & seeds", seafood: "Seafood", frozen_dessert: "Ice cream & frozen desserts",
  candy_chocolate: "Candy & chocolate", snacks: "Snacks", beverages: "Beverages", meat_poultry: "Meat & poultry",
  infant_formula_baby_food: "Infant formula & baby food", eggs: "Eggs", unknown: "Unknown",
  // how the problem was found
  supplier_notification: "Supplier notified the firm", regulator_testing: "Regulator testing",
  regulator_inspection: "Regulator inspection", firm_testing: "Firm's own testing", customer_testing: "Customer's testing",
  consumer_complaint: "Consumer complaint", illness_investigation: "Illness investigation",
  label_or_record_review: "Label or record review",
};
export const label = (key) => LABELS[key] ?? key;

export const titleCase = (key) => (key ?? "").replace(/_/g, " ").replace(/^./, (c) => c.toUpperCase());

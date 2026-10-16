"""Map each return line to one of the firm's 9 review areas.

Rules are checked in order; the first match wins. They match on the line
key's prefix (form, or form + line), never on a specific document, so the
same mapping works for any client's return.
"""

AREAS = [
    # id (from firm.budget_hours)        display name
    ("intake_and_engagement",            "Intake and engagement"),
    ("wages_and_stock_compensation",     "Wages and stock compensation"),
    ("investments_and_digital_assets",   "Investments and digital assets"),
    ("business",                         "Business"),
    ("rentals_and_sale",                 "Rentals and sale"),
    ("pass_throughs_and_basis",          "Pass-throughs and basis"),
    ("deductions_and_credits",           "Deductions and credits"),
    ("california",                       "California"),
    ("partner_review",                   "Tax computation and payments"),
]

# (key prefix, area). Longer, more specific prefixes come first.
RULES = [
    # Wages and stock compensation
    ("F1040.1",  "wages_and_stock_compensation"),
    ("F8959",    "wages_and_stock_compensation"),
    ("F6251.2i", "wages_and_stock_compensation"),   # ISO exercise
    ("Sch3.11",  "wages_and_stock_compensation"),   # excess social security
    # Business
    ("SchC",     "business"),
    ("SchSE",    "business"),
    ("F4562-C",  "business"),
    ("F8995",    "business"),
    ("Sch1.3",   "business"),
    ("Sch1.15",  "business"),
    ("Sch1.16",  "business"),
    ("Sch1.17",  "business"),
    # Pass-throughs and basis (before rentals: SchE.28+ are K-1 lines)
    ("SchE.28",  "pass_throughs_and_basis"),
    ("SchE.32",  "pass_throughs_and_basis"),
    ("F7203",    "pass_throughs_and_basis"),
    # Rentals and sale
    ("SchE",     "rentals_and_sale"),
    ("F4562-E",  "rentals_and_sale"),
    ("F4797",    "rentals_and_sale"),
    ("F8582",    "rentals_and_sale"),
    ("Sch1.5",   "rentals_and_sale"),
    # Investments and digital assets (incl. IRA and foreign accounts)
    ("SchB",     "investments_and_digital_assets"),
    ("SchD",     "investments_and_digital_assets"),
    ("F8949",    "investments_and_digital_assets"),
    ("F8960",    "investments_and_digital_assets"),
    ("F8938",    "investments_and_digital_assets"),
    ("F8606",    "investments_and_digital_assets"),
    ("Sch3.1",   "investments_and_digital_assets"),  # foreign tax credit
    ("F1040.2",  "investments_and_digital_assets"),
    ("F1040.3",  "investments_and_digital_assets"),
    ("F1040.4",  "investments_and_digital_assets"),
    ("F1040.7",  "investments_and_digital_assets"),
    # Deductions and credits
    ("SchA",     "deductions_and_credits"),
    ("F8283",    "deductions_and_credits"),
    ("F8812",    "deductions_and_credits"),
    ("F8863",    "deductions_and_credits"),
    ("F2441",    "deductions_and_credits"),
    ("F8867",    "deductions_and_credits"),
    ("F8889",    "deductions_and_credits"),
    ("Sch1.13",  "deductions_and_credits"),
    ("F1040.12", "deductions_and_credits"),
    ("F1040.13", "deductions_and_credits"),
    ("F1040.14", "deductions_and_credits"),
    ("F1040.19", "deductions_and_credits"),
]


def area_for(key: str, jurisdiction: str) -> str:
    """Return the area id for a line key.

    Note on prefixes: 'F1040.1' must not swallow 'F1040.11' (AGI) or
    'F1040.12'. So a prefix ending in a digit only matches when the next
    character is not also a digit.
    """
    if jurisdiction == "california":
        return "california"
    for prefix, area in RULES:
        if key.startswith(prefix):
            rest = key[len(prefix):]
            if prefix[-1].isdigit() and rest[:1].isdigit():
                continue
            return area
    # Totals, tax, payments, penalties: reviewed as the overall computation.
    return "partner_review"

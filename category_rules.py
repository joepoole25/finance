"""
category_rules.py — Transaction Categorization Rules
Derived from 2025/26 transaction history.

HOW MATCHING WORKS:
─────────────────────────────────────────────────────────────────────────────
  Rules run top to bottom. FIRST MATCH WINS. Order is intentional — do not
  rearrange without understanding the dependencies noted in comments.

  Each keyword is tested as a case-insensitive substring of Description.
  One keyword matching is sufficient to trigger the rule.

  amount_sign: "positive" = money in | "negative" = money out
  Use this to split the same merchant into Income vs Expenses (e.g. BAE SYSTEMS).

WHAT WILL CORRECTLY STAY UNASSIGNED (review these monthly):
─────────────────────────────────────────────────────────────────────────────
  - Personal payments from / to family (CHAR MARTIN, MARTIN C E, POOLE SE,
    BENJAMIN JOHN POOL) — context-dependent, can't keyword reliably
  - UBER trips — personal vs work is indistinguishable from description alone
  - Amazon / eBay purchases — category depends on what was bought
  - PAYPAL *ALIPAY — category depends on purchase
  - One-off restaurant / bar names not yet in the rules below
  - Any new merchant not yet seen

HOW TO ADD A NEW RULE:
─────────────────────────────────────────────────────────────────────────────
  After each run, open master_ledger.csv, filter Category == "unassigned",
  review the Description values, and paste a new block here. Run:
      python category_rules.py
  to validate before next run.
"""

# ─────────────────────────────────────────────────────────────────────────────
# AMBIGUOUS MERCHANTS
# Description substrings (case-insensitive) that must NEVER be auto-assigned
# from historical patterns (see historical_categorizer.py), because the same
# merchant genuinely spans multiple categories depending on context. Mirrors
# the "WHAT WILL CORRECTLY STAY UNASSIGNED" list in the module docstring above.
# ─────────────────────────────────────────────────────────────────────────────

AMBIGUOUS_MERCHANT_KEYWORDS: list[str] = [
    "CHAR MARTIN", "MARTIN C E", "POOLE SE", "BENJAMIN JOHN POOL",
    "UBER", "AMAZON", "EBAY", "PAYPAL *ALIPAY",
]


CATEGORY_RULES: list[dict] = [

    # ══════════════════════════════════════════════════════════════════════════
    # TRANSFERS
    # Must be FIRST — these patterns overlap with other categories
    # (e.g. LYDS MC contains Lloyds; PAYMENT RECEIVED is also on AMEX)
    # ══════════════════════════════════════════════════════════════════════════

    # AMEX card payment sent from Lloyds
    {
        "keywords": ["AMERICAN EXP 3773", "AMEX PAYMENT"],
        "category": "Transfers",
    },
    # Lloyds card payment from AMEX or other account
    {
        "keywords": ["LYDS MC 5404/5402", "LLOYDS ULTRA", "LLoyds Payment"],
        "category": "Transfers",
    },
    # AMEX inbound payment acknowledgement line
    {
        "keywords": ["PAYMENT RECEIVED - THANK YOU", "PAYMENT RECEIVED - THAN"],
        "category": "Transfers",
    },
    # Generic DD / bank transfer labels
    {
        "keywords": ["DIRECT DEBIT PAYMENT -"],
        "category": "Transfers",
    },
    # "Joseph Poole - JosephPoole" dash variant = Transfers (NOT savings)
    # MUST sit above the broad "JOSEPH POOLE" → Saving rule below
    {
        "keywords": ["JOSEPH POOLE - JOSEPHPOOLE", "Joseph Poole - JosephPoole",
                     "Joseph Poole - JosephPoole"],
        "category": "Transfers",
    },
    # Wife-to-account transfers
    {
        "keywords": ["MARTIN C E love you", "MARTIN C E - love you"],
        "category": "Transfers",
    },

    # ══════════════════════════════════════════════════════════════════════════
    # SAVING
    # Various formatting of the same standing order / internal transfer
    # ══════════════════════════════════════════════════════════════════════════

    {
        "keywords": ["JOSEPH POOLE JOSEPHPOOLE", "Joseph Poole JosephPoole",
                     "JOSEPH POOLE CR", "JOSEPH POOLE - JOSEPHPOOLE SO",
                     "JOSEPH POOLE"],
        "category": "Saving",
    },

    # ══════════════════════════════════════════════════════════════════════════
    # INCOME
    # amount_sign filters prevent refunds / reimbursements from miscategorising
    # ══════════════════════════════════════════════════════════════════════════

    # BAE Systems salary and expense reimbursements (positive = money in)
    {
        "keywords": ["BAE SYSTEMS"],
        "category": "Income",
        "amount_sign": "positive",
    },
    # eBay sales proceeds
    {
        "keywords": ["EBAY COMMERCE UK", "EBAY Commerce UK"],
        "category": "Income",
        "amount_sign": "positive",
    },
    {
        "keywords": ["PRINCH VIBY"],
        "category": "Income",
        "amount_sign": "positive",
    },

    # ══════════════════════════════════════════════════════════════════════════
    # MORTGAGE
    # Shared account standing order — match full compound string
    # (BILLS and FOOD variants of POOLE&MARTIN handled below)
    # ══════════════════════════════════════════════════════════════════════════

    {
        "keywords": ["POOLE&MARTIN*CAA MORTGAGE", "POOLE&MARTIN*CAA - MORTGAGE",
                     "POOLE&MARTIN - MORTGAGE"],
        "category": "Mortgage",
    },

    # ══════════════════════════════════════════════════════════════════════════
    # BILLS
    # ══════════════════════════════════════════════════════════════════════════

    {
        "keywords": ["POOLE&MARTIN*CAA BILLS", "POOLE&MARTIN*CAA - BILLS",
                     "POOLE&MARTIN - BILLS"],
        "category": "Bills",
    },
    # O2 mobile — match both "O2 DD" and plain "O2" variants
    {
        "keywords": ["O2 DD", "O2 "],
        "category": "Bills",
    },
    # AMEX interest charge (appears in AMEX export)
    {
        "keywords": ["INTEREST CHARGE"],
        "category": "Bills",
    },

    # ══════════════════════════════════════════════════════════════════════════
    # HOUSE
    # Includes Nationwide credit card DD (card used primarily for home purchases)
    # ══════════════════════════════════════════════════════════════════════════

    {
        "keywords": ["NW MASTERCARD DD", "NW MASTERCARD FIRST PAYMENT DD",
                     "NW MASTERCARD", "NW PLAT M/C 552213"],
        "category": "House",
    },
    {
        "keywords": ["TOOLSTATION"],
        "category": "House",
    },
    {
        "keywords": ["SCREWFIX"],
        "category": "House",
    },
    {
        "keywords": ["ROOFWISE"],
        "category": "House",
    },

    # ══════════════════════════════════════════════════════════════════════════
    # PERSONAL CARE
    # ══════════════════════════════════════════════════════════════════════════

    # Peloton via shared account — MUST come before general POOLE&MARTIN catch
    {
        "keywords": ["POOLE&MARTIN*CAA PELOT", "POOLE&MARTIN*CAA - PELOT"],
        "category": "Personal Care",
    },
    # Contact lens subscription
    {
        "keywords": ["VISION CLS"],
        "category": "Personal Care",
    },
    # Gym memberships
    {
        "keywords": ["VIRGIN ACTIVE"],
        "category": "Personal Care",
    },
    # Barbers
    {
        "keywords": ["THE PARK BARBERS", "PARK BARBERS"],
        "category": "Personal Care",
    },
    # Pharmacy — Boots appears as Holidays in SA context but Personal Care is primary
    {
        "keywords": ["BOOTS THE CHEMIST"],
        "category": "Personal Care",
    },
    # Supplements (Bulk Supplements / Bulk Powders)
    {
        "keywords": ["BULK COLCHESTER", "BULK "],
        "category": "Personal Care",
    },
    # Personal training
    {
        "keywords": ["DYNAMO FEES", "DYNAMO"],
        "category": "Personal Care",
    },

    # ══════════════════════════════════════════════════════════════════════════
    # HOLIDAYS
    # Yoco = South African payment terminal (strong signal)
    # UberDirectSA / UberAT = SA-specific Uber variants
    # Named SA venues listed individually
    # ══════════════════════════════════════════════════════════════════════════

    # Yoco POS — all South Africa holiday transactions use this terminal
    {
        "keywords": ["YOCO", "Yoco"],
        "category": "Holidays",
    },
    # South Africa Uber variants
    {
        "keywords": ["UBERDIRECTSA", "UberDirectSA", "UBERAT_EATS", "UberAT_EATS"],
        "category": "Holidays",
    },
    # SA payment gateway
    {
        "keywords": ["PAYSTACK"],
        "category": "Holidays",
    },
    # Named South African venues (Franschhoek / Stellenbosch / Cape Town area)
    {
        "keywords": ["TINTSWALO", "FRANSCHOEK PHARMACY", "BOSCHENDAL", "BARTINNEY",
                     "DELAIRE GRAFF", "SPIER WINE", "SPIER HOTEL",
                     "BABEL PAARL", "TMNP BOULDERS", "LA PETITE COLOMBE",
                     "MOREA HOUSE", "ABT FACILITIES", "TOTAL AIRPORT INDUSTRI",
                     "MERTIA", "TERBODORE"],
        "category": "Holidays",
    },
    # Car hire — appears in SA holiday context
    {
        "keywords": ["AVIS RENT A CAR", "AVIS "],
        "category": "Holidays",
    },

    # ══════════════════════════════════════════════════════════════════════════
    # BICYCLE
    # NOTE: B&Q appears exclusively for bike parts in historical data — if you
    # buy DIY supplies from B&Q, manually correct those transactions
    # ══════════════════════════════════════════════════════════════════════════

    {
        "keywords": ["TREDZ"],
        "category": "Bicycle",
    },
    {
        "keywords": ["BALFESBIKES", "BALFES BIKES", "Balfes Bikes"],
        "category": "Bicycle",
    },
    {
        "keywords": ["SJSCYCLES", "SJS CYCLES"],
        "category": "Bicycle",
    },
    {
        "keywords": ["BIKE CLINIQUE", "SP BIKE CLINIQUE"],
        "category": "Bicycle",
    },
    {
        "keywords": ["SP BIKEPARTS", "BIKEPARTS"],
        "category": "Bicycle",
    },
    {
        "keywords": ["DECATHLON"],
        "category": "Bicycle",
    },
    # B&Q Merton has an in-store bike section (see "MERTON (INSIDE SAINSBUR")
    {
        "keywords": ["B&Q", "BANDQ"],
        "category": "Bicycle",
    },
    # Bike section inside Sainsbury's Merton
    {
        "keywords": ["MERTON (INSIDE SAINSBUR"],
        "category": "Bicycle",
    },

    # ══════════════════════════════════════════════════════════════════════════
    # CAR
    # TESCO PETROL must sit ABOVE the general TESCO → Groceries rule
    # MOTO LANCASTER SOUTH MW (motorway fuel) must sit ABOVE generic MOTO → Food
    # ══════════════════════════════════════════════════════════════════════════

    {
        "keywords": ["TESCO PETROL"],
        "category": "Car",
    },
    {
        "keywords": ["M6 TOLL"],
        "category": "Car",
    },
    # "MW" suffix on Moto = motorway fuel pump (vs "CO" / plain = food court)
    {
        "keywords": ["MOTO LANCASTER SOUTH MW"],
        "category": "Car",
    },

    # ══════════════════════════════════════════════════════════════════════════
    # TRANSPORT
    # UBER is intentionally omitted — personal vs work is indistinguishable
    # from description alone. Review monthly and categorise manually.
    # SWR routes are under Expenses (work travel — see below)
    # ══════════════════════════════════════════════════════════════════════════

    {
        "keywords": ["TFL TRAVEL CHARGE", "TFL.GOV"],
        "category": "Transport",
    },
    # Bolt rides (UK)
    {
        "keywords": ["BOLT SERVICES UK"],
        "category": "Transport",
    },
    # Lime e-bikes / scooters
    {
        "keywords": ["LIME*RIDE", "LIME*PASS"],
        "category": "Transport",
    },

    # ══════════════════════════════════════════════════════════════════════════
    # GROCERIES
    # Specific POOLE&MARTIN food sharing rule FIRST, then supermarkets
    # TESCO STORE after TESCO PETROL (Car rule above)
    # ══════════════════════════════════════════════════════════════════════════

    {
        "keywords": ["POOLE&MARTIN*CAA FOOD", "POOLE&MARTIN*CAA - FOOD",
                     "POOLE&MARTIN - FOOD"],
        "category": "Groceries",
    },
    {
        "keywords": ["SAINSBURY"],
        "category": "Groceries",
    },
    {
        "keywords": ["MORRISONS"],
        "category": "Groceries",
    },
    {
        "keywords": ["WAITROSE"],
        "category": "Groceries",
    },
    {
        "keywords": ["LIDL"],
        "category": "Groceries",
    },
    # Tesco stores (not petrol — that rule fires first above)
    {
        "keywords": ["TESCO STORE", "TESCO EXTRA", "TESCO SUPERSTORE"],
        "category": "Groceries",
    },
    {
        "keywords": ["BUYWHOLEFOODSONLINE"],
        "category": "Groceries",
    },
    # Colicci is a Richmond Park café but appears as Groceries in data
    {
        "keywords": ["LS COLICCI RICHMOND"],
        "category": "Groceries",
    },
    # M&S specific locations — Wimbledon = weekly shop, Colliers Wood = local food run
    # If you shop at other M&S locations, add them here
    {
        "keywords": ["M&S WIMBLEDON", "M&S COLLIERS WOOD", "MARKS AND SPENCER"],
        "category": "Groceries",
    },

    # ══════════════════════════════════════════════════════════════════════════
    # COFFEE
    # ══════════════════════════════════════════════════════════════════════════

    {
        "keywords": ["SP GROUND COFFEE C", "GROUND COFFEE C"],
        "category": "Coffee",
    },
    {
        "keywords": ["DROPSHOT COFFEE", "ZETTLE *DROPSHOT"],
        "category": "Coffee",
    },
    # DOJO*COFFEE AT THE STAND
    {
        "keywords": ["DOJO*COFFEE AT THE STAN"],
        "category": "Coffee",
    },
    # Artisan Coffee Putney — appears as Coffee (primary) and Food & drink
    {
        "keywords": ["DOJO*ARTISAN PUTNEY", "ARTISAN PUTNEY"],
        "category": "Coffee",
    },
    {
        "keywords": ["FORTY ACRE COFFEE"],
        "category": "Coffee",
    },
    {
        "keywords": ["NAKED COFFEE"],
        "category": "Coffee",
    },
    {
        "keywords": ["THE EXCHANGE CAFE"],
        "category": "Coffee",
    },
    {
        "keywords": ["TAN HOUSE FARM SHOP", "TAN HOUSE FARM"],
        "category": "Coffee",
    },

    # ══════════════════════════════════════════════════════════════════════════
    # FOOD & DRINK
    # Named cafes / restaurants / food delivery
    # Costa, Pret, Nandos etc. are not listed here because they appear as
    # "Expenses" on work trips — too ambiguous to auto-assign
    # ══════════════════════════════════════════════════════════════════════════

    # BAE Systems site canteen (appears consistently as Food & drink)
    {
        "keywords": ["CAFE 110"],
        "category": "Food & drink",
    },
    {
        "keywords": ["DELIVEROO"],
        "category": "Food & drink",
    },
    {
        "keywords": ["DUKE'S HEAD PUTNEY", "DUKES HEAD PUTNEY"],
        "category": "Food & drink",
    },
    {
        "keywords": ["PEASLAKE VILLAGE"],
        "category": "Food & drink",
    },
    {
        "keywords": ["PORTLAND LONDON"],
        "category": "Food & drink",
    },
    {
        "keywords": ["IDE HILL COMMUNITY"],
        "category": "Food & drink",
    },
    {
        "keywords": ["LS GANYMEDE"],
        "category": "Food & drink",
    },
    {
        "keywords": ["SHIFT4*THE LITTLE TAPER", "THE LITTLE TAPER"],
        "category": "Food & drink",
    },
    {
        "keywords": ["TST-RUTH'S"],
        "category": "Food & drink",
    },
    # Village pub / food stop
    {
        "keywords": ["THE CROSSINGS INN"],
        "category": "Food & drink",
    },
    {
        "keywords": ["ZETTLE_*DOUGH DISCIPLE", "DOUGH DISCIPLE"],
        "category": "Food & drink",
    },
    # Kauai juice / coffee chain (predominantly Food & drink in data)
    {
        "keywords": ["KAUAI", "Kauai"],
        "category": "Food & drink",
    },
    # Motorway services food (fuel variant fires first via Car rule above)
    {
        "keywords": ["MOTO LANCASTER SOUTH"],
        "category": "Food & drink",
    },
    # Post Office local store used for food purchases
    {
        "keywords": ["POST OFFICE TADWORTH"],
        "category": "Food & drink",
    },
    # DOJO*KOKORO - Japanese food chain
    {
        "keywords": ["DOJO*KOKORO", "KOKORO"],
        "category": "Food & drink",
    },

    # ══════════════════════════════════════════════════════════════════════════
    # DRINKS
    # Pubs and bars — specific venue names
    # ══════════════════════════════════════════════════════════════════════════

    {
        "keywords": ["DOJO*THE ANTELOPE", "THE ANTELOPE SURBITON"],
        "category": "Drinks",
    },
    {
        "keywords": ["WHITE HORSE LONDON", "White Horse LONDON"],
        "category": "Drinks",
    },
    {
        "keywords": ["TOOTING TAVERN", "Tooting Tavern"],
        "category": "Drinks",
    },
    {
        "keywords": ["DOG AND FOX"],
        "category": "Drinks",
    },
    {
        "keywords": ["THE RAILWAY", "The Railway"],
        "category": "Drinks",
    },
    {
        "keywords": ["THE ROSE AND CROWN", "ROSE AND CROWN"],
        "category": "Drinks",
    },
    {
        "keywords": ["LEFT HANDED GIANT BREW", "LEFT HANDED GIANT"],
        "category": "Drinks",
    },
    {
        "keywords": ["ZETTLE *TAYER", "TAYER LIMITED"],
        "category": "Drinks",
    },
    {
        "keywords": ["THOMAS CUBIT - TTC", "THOMAS CUBIT"],
        "category": "Drinks",
    },
    {
        "keywords": ["TREMBLING MADNESS"],
        "category": "Drinks",
    },
    # Heathrow airside bar
    {
        "keywords": ["3CPAYMENT*SSPUKHEATHROW"],
        "category": "Drinks",
    },
    # US venue (Celtics game)
    {
        "keywords": ["TD GARDEN F&B"],
        "category": "Drinks",
    },
    {
        "keywords": ["DOJO*THREE COMPASSES", "LS THREE COMPASSES", "THREE COMPASSES"],
        "category": "Drinks",
    },

    # ══════════════════════════════════════════════════════════════════════════
    # ENTERTAINMENT
    # Ongoing subscriptions and media (not event tickets — those are Experiences)
    # ══════════════════════════════════════════════════════════════════════════

    {
        "keywords": ["SPOTIFY"],
        "category": "Entertainment",
    },
    {
        "keywords": ["APPLE.COM/BILL", "APPLE.COM"],
        "category": "Entertainment",
    },
    {
        "keywords": ["FINANCIAL TIMES"],
        "category": "Entertainment",
    },

    # ══════════════════════════════════════════════════════════════════════════
    # EXPERIENCES
    # One-off event tickets and experiential purchases
    # ══════════════════════════════════════════════════════════════════════════

    {
        "keywords": ["DICE.FM", "DICE "],
        "category": "Experiences",
    },
    {
        "keywords": ["TICKETMASTER", "TM *TICKETMASTER"],
        "category": "Experiences",
    },

    # ══════════════════════════════════════════════════════════════════════════
    # CAREER EDUCATION
    # ══════════════════════════════════════════════════════════════════════════

    {
        "keywords": ["CLAUDE.AI SUBSCRIPTION", "CLAUDE.AI"],
        "category": "Career Educa",
    },
    # Institution of Mechanical Engineers membership
    {
        "keywords": ["IMECHE"],
        "category": "Career Educa",
    },

    # ══════════════════════════════════════════════════════════════════════════
    # GIVING
    # ══════════════════════════════════════════════════════════════════════════

    {
        "keywords": ["MOONPIG"],
        "category": "Giving",
    },

    # ══════════════════════════════════════════════════════════════════════════
    # SHOPPING
    # ══════════════════════════════════════════════════════════════════════════

    {
        "keywords": ["SPORTSDIRECT"],
        "category": "Shopping",
    },
    {
        "keywords": ["ABERCROMBIE"],
        "category": "Shopping",
    },
    {
        "keywords": ["NAYLORS"],
        "category": "Shopping",
    },
    {
        "keywords": ["SP HIPSWAN", "HIPSWAN"],
        "category": "Shopping",
    },
    # Post Office counter purchases (not the Tadworth food store, which fires first above)
    {
        "keywords": ["POST OFFICE COUNTER"],
        "category": "Shopping",
    },

    # ══════════════════════════════════════════════════════════════════════════
    # EXPENSES
    # Work-related spending — BAE Systems canteens, site access, work travel
    # BAE SYSTEMS (negative amount) catches expenses not caught by specific rules
    # ══════════════════════════════════════════════════════════════════════════

    # Site canteens
    {
        "keywords": ["ESS CATERING", "ESS MOD ABBEYWOOD", "ESS MOD"],
        "category": "Expenses",
    },
    # Compass / facility services
    {
        "keywords": ["COMPASS SERVICES U.K.", "COMPASS SERVICES"],
        "category": "Expenses",
    },
    # MoD Abbeywood site (Bristol)
    {
        "keywords": ["ABBEY WOOD MAIN", "ABBEY WOOD"],
        "category": "Expenses",
    },
    # BAE site cost centres
    {
        "keywords": ["5141 - BAE", "5142 - BAE", "BAE WPS", "BAE SYSTEMS MARITIME"],
        "category": "Expenses",
    },
    {
        "keywords": ["BRSDE PMS"],
        "category": "Expenses",
    },
    # BAE corporate travel
    {
        "keywords": ["GBT TRAVEL SERVICES"],
        "category": "Expenses",
    },
    # Work rail travel (SWR to/from BAE sites)
    # Personal SWR travel would need manual correction — but the Bicester route
    # is consistently work-related
    {
        "keywords": ["SWR MOBILE APP", "SWR - SILVERRAIL"],
        "category": "Expenses",
    },
    # BAE Systems spend (negative = expense; positive = Income, handled above)
    {
        "keywords": ["BAE SYSTEMS"],
        "category": "Expenses",
        "amount_sign": "negative",
    },

]


# ─────────────────────────────────────────────────────────────────────────────
# VALIDATION  (run: python category_rules.py)
# ─────────────────────────────────────────────────────────────────────────────

VALID_CATEGORIES = {
    "Bicycle", "Big Life", "Bills", "Car", "Career Educa", "Cash", "Coffee",
    "Drinks", "Entertainment", "Expenses", "Experiences", "Food & drink",
    "General", "Giving", "Groceries", "Holidays", "House", "Income",
    "Investment", "Mortgage", "Personal Care", "Saving", "Shopping",
    "Transfers", "Transport",
}


def validate_rules() -> None:
    valid_match_types  = {"contains", "startswith", "exact"}
    valid_amount_signs = {"positive", "negative"}
    errors = []

    for i, rule in enumerate(CATEGORY_RULES):
        cat   = rule.get("category", "?")
        label = f"Rule[{i}] ({cat})"

        if not rule.get("keywords"):
            errors.append(f"{label}: 'keywords' is empty or missing.")
        if not rule.get("category"):
            errors.append(f"{label}: 'category' is missing.")
        if rule.get("category") and rule["category"] not in VALID_CATEGORIES:
            errors.append(
                f"{label}: '{rule['category']}' is not in the valid category list. "
                f"Valid options: {sorted(VALID_CATEGORIES)}"
            )
        if "match_type" in rule and rule["match_type"] not in valid_match_types:
            errors.append(f"{label}: invalid match_type '{rule['match_type']}'.")
        if "amount_sign" in rule and rule["amount_sign"] not in valid_amount_signs:
            errors.append(f"{label}: invalid amount_sign '{rule['amount_sign']}'.")

    if errors:
        print(f"\n✗ {len(errors)} error(s) found:")
        for e in errors:
            print(f"  {e}")
    else:
        print(f"\n✓ {len(CATEGORY_RULES)} rules validated — no errors.")
        print(f"  Categories in use: "
              f"{sorted({r['category'] for r in CATEGORY_RULES})}")
        uncovered = VALID_CATEGORIES - {r["category"] for r in CATEGORY_RULES}
        if uncovered:
            print(f"  Categories with no rules yet: {sorted(uncovered)}")
            print(f"  (Big Life, Cash, General, Investment — normal, these need manual assignment)")


if __name__ == "__main__":
    validate_rules()

"""
historical_categorizer.py — Rolling-History Categorization Fallback

Runs AFTER the static keyword rules in category_rules.py. Any transaction
still left "unassigned" is checked against a merchant → category lookup
built from the master ledger's own history, so the categorizer learns from
past decisions instead of relying solely on hand-written keyword rules.

ROLLING WINDOW
─────────────────────────────────────────────────────────────────────────────
  Only already-categorized ledger rows from the trailing HISTORY_ROLLING_MONTHS
  (relative to today, not to the ledger's newest row) feed the lookup. Each
  run the window slides forward automatically — old merchant categorizations
  age out on their own, so a merchant that changes category over time (or a
  one-off past mistake) doesn't stick around forever.

MATCHING
─────────────────────────────────────────────────────────────────────────────
  Descriptions are normalized (uppercased, reference numbers stripped) and
  paired with the transaction's direction (money in / out), since the same
  merchant name can mean Income in one direction and an Expense in the other
  (see BAE SYSTEMS in category_rules.py).

  A (normalized description, direction) pair only produces a proposed
  category if it appeared at least MIN_OCCURRENCES times in the window AND
  at least MIN_AGREEMENT of those occurrences agree on the same category.
  This keeps genuinely ambiguous merchants (see AMBIGUOUS_MERCHANT_KEYWORDS
  in category_rules.py) from being auto-assigned on a fluke.
"""

from __future__ import annotations

import re
import logging
from collections import Counter, defaultdict
from datetime import datetime

import pandas as pd

from category_rules import AMBIGUOUS_MERCHANT_KEYWORDS, VALID_CATEGORIES

log = logging.getLogger(__name__)


# ─────────────────────────────────────────────────────────────────────────────
# CONFIG
# ─────────────────────────────────────────────────────────────────────────────

HISTORY_ROLLING_MONTHS = 12   # trailing window of ledger history to learn from
MIN_OCCURRENCES         = 2   # a merchant signature must recur at least this many times...
MIN_AGREEMENT           = 0.7 # ...and agree on one category at least this often


# ─────────────────────────────────────────────────────────────────────────────
# NORMALIZATION
# ─────────────────────────────────────────────────────────────────────────────

_REF_NUMBER_RE   = re.compile(r"\b\d{3,}\b")
_NON_ALNUM_RE    = re.compile(r"[^A-Z0-9&' ]")
_WHITESPACE_RE   = re.compile(r"\s+")


def normalize_description(desc: str) -> str:
    """
    Collapse a raw Description into a stable merchant signature by stripping
    reference numbers (card auth codes, transaction IDs) and punctuation that
    vary run to run but don't identify the merchant.
    """
    s = str(desc).upper()
    s = _REF_NUMBER_RE.sub(" ", s)
    s = _NON_ALNUM_RE.sub(" ", s)
    s = _WHITESPACE_RE.sub(" ", s).strip()
    return s


def _direction(amount: float) -> str:
    return "positive" if amount > 0 else "negative"


def _is_ambiguous(normalized_desc: str) -> bool:
    return any(kw.upper() in normalized_desc for kw in AMBIGUOUS_MERCHANT_KEYWORDS)


# ─────────────────────────────────────────────────────────────────────────────
# LOOKUP CONSTRUCTION
# ─────────────────────────────────────────────────────────────────────────────

def build_history_lookup(
    hist_df: pd.DataFrame,
    rolling_months: int = HISTORY_ROLLING_MONTHS,
    as_of: datetime | None = None,
) -> dict[tuple[str, str], str]:
    """
    Build a {(normalized_description, direction): category} lookup from the
    trailing `rolling_months` of already-categorized rows in `hist_df`.

    `hist_df` should be the CURRENT state of the ledger — i.e. pulled fresh
    from wherever categories actually get corrected (see budget_ingest.py's
    download_ledger_from_sheets()), not a local cache that may have drifted
    from manual corrections made elsewhere.

    Returns an empty dict (never raises) if `hist_df` is empty/None or has no
    usable history — the categorizer simply falls back to keyword rules only
    in that case.
    """
    if hist_df is None or hist_df.empty or not {"Date", "Description", "Amount", "Category"}.issubset(hist_df.columns):
        log.info("History lookup skipped — no usable ledger history provided.")
        return {}

    hist = hist_df.copy()
    hist["_date"] = pd.to_datetime(hist["Date"], format="%d/%m/%Y", errors="coerce")
    cutoff = (as_of or datetime.today()) - pd.DateOffset(months=rolling_months)
    hist = hist[hist["_date"] >= cutoff]
    hist = hist[hist["Category"].notna() & (hist["Category"] != "") & (hist["Category"] != "unassigned")]

    groups: dict[tuple[str, str], Counter] = defaultdict(Counter)
    for _, row in hist.iterrows():
        category = row["Category"]
        if category not in VALID_CATEGORIES:
            continue

        normalized = normalize_description(row["Description"])
        if not normalized or _is_ambiguous(normalized):
            continue

        try:
            amount = float(row["Amount"])
        except (TypeError, ValueError):
            continue

        groups[(normalized, _direction(amount))][category] += 1

    lookup: dict[tuple[str, str], str] = {}
    for key, counts in groups.items():
        total = sum(counts.values())
        category, top_count = counts.most_common(1)[0]
        if total >= MIN_OCCURRENCES and (top_count / total) >= MIN_AGREEMENT:
            lookup[key] = category

    log.info(
        f"History lookup built from trailing {rolling_months} month(s): "
        f"{len(lookup)} merchant signature(s) eligible for auto-categorization."
    )
    return lookup


# ─────────────────────────────────────────────────────────────────────────────
# APPLICATION
# ─────────────────────────────────────────────────────────────────────────────

def apply_history_categories(
    df: pd.DataFrame,
    lookup: dict[tuple[str, str], str],
) -> pd.DataFrame:
    """
    For rows still Category == "unassigned" after keyword rules, propose a
    category from `lookup` when the merchant signature + direction matches.
    Rows outside the lookup (new merchants, ambiguous merchants, insufficient
    history) are left "unassigned" for manual review, unchanged.
    """
    result = df.copy()
    matched = 0

    if not lookup:
        return result

    for idx, row in result.iterrows():
        if row["Category"] != "unassigned":
            continue

        normalized = normalize_description(row["Description"])
        if not normalized or _is_ambiguous(normalized):
            continue

        try:
            amount = float(row["Amount"])
        except (TypeError, ValueError):
            continue

        key = (normalized, _direction(amount))
        category = lookup.get(key)
        if category:
            result.at[idx, "Category"] = category
            matched += 1

    if matched:
        log.info(f"History-based categorization: {matched} additional transaction(s) matched from ledger history.")
    else:
        log.info("History-based categorization: 0 additional transactions matched.")

    return result

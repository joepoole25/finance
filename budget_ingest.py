#!/usr/bin/env python3
"""
budget_ingest.py — Financial Ingestion, Normalization & Categorization
Phases 1–3: Detect → Normalize → Categorize → Append → Archive

Output schema : Account | Date | Description | Amount | Category
Amount sign   : negative = money OUT (expense/debit)
                positive = money IN  (income/refund/credit)
Date format   : DD/MM/YYYY

Usage:
    python /Users/BenPoole/Documents/budget/budget_ingest.py

Add alias to ~/.zshrc:
    alias run-budget='python /Users/BenPoole/Documents/budget/budget_ingest.py'
"""

import os
import sys
import glob
import shutil
import logging
from datetime import datetime
from pathlib import Path

import pandas as pd

# ─────────────────────────────────────────────────────────────────────────────
# LOGGING
# ─────────────────────────────────────────────────────────────────────────────

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
    handlers=[logging.StreamHandler(sys.stdout)],
)
log = logging.getLogger(__name__)


# ─────────────────────────────────────────────────────────────────────────────
# PATHS
# ─────────────────────────────────────────────────────────────────────────────

DOWNLOADS_DIR  = Path("/Users/BenPoole/Downloads")
STATEMENTS_DIR = Path("/Users/BenPoole/Documents/Joe/Statements")
MASTER_LEDGER  = STATEMENTS_DIR / "master_ledger.csv"

OUTPUT_COLUMNS = ["Account", "Date", "Description", "Amount", "Category"]

# Banks whose source filename is generic and would collide on monthly re-runs.
# These are renamed with a YYYYMMDD suffix when archived.
GENERIC_FILENAME_BANKS = {"AMEX", "Barclays"}


# ─────────────────────────────────────────────────────────────────────────────
# BANK CONFIGURATIONS
# ─────────────────────────────────────────────────────────────────────────────
#
# amount_encoding options:
#   "single_signed"      — one column; sign indicates direction
#   "split_debit_credit" — two columns (one blank per row); unsigned values
#
# positive_is_debit (single_signed only):
#   True  → positive value in source = expense (debit)  → output becomes negative
#   False → positive value in source = income (credit)  → output stays positive
#
# dayfirst:
#   True  → date strings parsed as DD/MM/YY[YY]  (UK)
#   False → date strings parsed as MM/DD/YY[YY]  (US)
#   AMEX: assumed True (UK account) — VERIFY on first run (see note below)
# ─────────────────────────────────────────────────────────────────────────────

BANK_CONFIGS: dict = {

    "AMEX": {
        "enabled":            True,
        "filename_pattern":   "activity.csv",       # exact name — generic, be aware
        "account_label":      "AMEX",
        "column_map": {
            "date":           "Date",
            "description":    "Description",
            "amount":         "Amount",
        },
        # VERIFY ON FIRST RUN:
        #   7/5/26 with dayfirst=True  → 7 May 2026  (UK format, assumed)
        #   7/5/26 with dayfirst=False → 5 July 2026 (US format)
        #   Check your first output batch against known transaction dates.
        #   Toggle this to False if dates are wrong.
        "dayfirst":           True,
        "amount_encoding":    "single_signed",
        "positive_is_debit":  True,   # AMEX charges appear as positive → flip to negative
        "encoding":           "utf-8-sig",   # handles BOM if present in export
        "skiprows":           0,
        "strip_currency":     True,
    },

    "Lloyds": {
        "enabled":            True,
        "filename_pattern":   "9091_*.csv",
        "account_label":      "Lloyds",
        "column_map": {
            "date":           "Transaction Date",
            "description":    "Transaction Description",
            "amount":         "Transaction Amount",
        },
        "dayfirst":           True,   # 5/3/26 = 5 March 2026, confirmed from sample
        "amount_encoding":    "single_signed",
        "positive_is_debit":  True,   # purchases appear as positive → flip to negative
        "encoding":           "utf-8",
        "skiprows":           0,
        "strip_currency":     True,
    },

    "Barclays": {
        # ── ENABLED ──────────────────────────────────────────────────────────
        # Source schema (confirmed from sample):
        #   Number | Date | Account | Amount | Subcategory | Memo
        #
        # WARNING — filename 'data.csv' is extremely generic. ANY file called
        # data.csv in Downloads will be picked up as Barclays. Strongly
        # recommend renaming the export to 'barclays_data.csv' and updating
        # filename_pattern below. Until then, archive_source_files() renames
        # with a datestamp to avoid re-run overwrite.
        #
        # Sign convention differs from AMEX/Lloyds:
        #   Sample: -9 = money out (Funds Transfer to CHAR MARTIN)
        #   Therefore source already matches output convention → no flip.
        #
        # Description source: Memo column (free text like "CHAR MARTIN OWED FT").
        # Subcategory ("Funds Transfer" etc.) is the bank's own classification
        # and is intentionally ignored — it would add noise to keyword matching
        # against existing rules. Revisit if needed.
        # ─────────────────────────────────────────────────────────────────────
        "enabled":            True,
        "filename_pattern":   "data.csv",
        "account_label":      "Barclays",
        "column_map": {
            "date":           "Date",
            "description":    "Memo",
            "amount":         "Amount",
        },
        "dayfirst":           True,                 # 29/05/2026 = 29 May 2026
        "amount_encoding":    "single_signed",
        "positive_is_debit":  False,                # -9 = out → already matches output convention
        "encoding":           "utf-8-sig",          # Barclays often exports with BOM
        "skiprows":           0,
        "strip_currency":     True,
    },

}


# ─────────────────────────────────────────────────────────────────────────────
# PHASE 1 — FILE DETECTION
# ─────────────────────────────────────────────────────────────────────────────

def detect_bank_files() -> dict[str, Path]:
    """
    Scan ~/Downloads for files matching each enabled bank's filename_pattern.
    Selects the most recently modified file when multiple matches exist.

    Returns {bank_key: Path} for every bank with a matching file.
    Exits cleanly if nothing is found.
    """
    found: dict[str, Path] = {}

    for bank_key, config in BANK_CONFIGS.items():
        if not config.get("enabled", True):
            log.info(f"[{bank_key}] Skipped — disabled in BANK_CONFIGS.")
            continue

        pattern = str(DOWNLOADS_DIR / config["filename_pattern"])
        matches = sorted(
            [Path(p) for p in glob.glob(pattern)],
            key=lambda p: p.stat().st_mtime,
            reverse=True,
        )

        if not matches:
            log.info(f"[{bank_key}] No files found matching: {config['filename_pattern']}")
            continue

        selected = matches[0]

        if len(matches) > 1:
            skipped = [m.name for m in matches[1:]]
            log.warning(
                f"[{bank_key}] {len(matches)} files matched. "
                f"Using newest: '{selected.name}'. "
                f"Ignored: {skipped}"
            )
        else:
            log.info(f"[{bank_key}] Detected: {selected.name}")

        found[bank_key] = selected

    if not found:
        log.warning("No bank files found in Downloads. Nothing to process.")
        sys.exit(0)

    return found


# ─────────────────────────────────────────────────────────────────────────────
# PHASE 2 — INGESTION & NORMALIZATION (helpers)
# ─────────────────────────────────────────────────────────────────────────────

def _read_raw_csv(bank_key: str, file_path: Path) -> pd.DataFrame:
    """Read raw CSV preserving all columns as strings for explicit type conversion."""
    config = BANK_CONFIGS[bank_key]
    try:
        df = pd.read_csv(
            file_path,
            encoding=config.get("encoding", "utf-8"),
            skiprows=config.get("skiprows", 0),
            dtype=str,
            skip_blank_lines=True,
        )
        df.columns = df.columns.str.strip()
        log.info(f"[{bank_key}] Read {len(df)} raw rows. Columns: {list(df.columns)}")
        return df
    except UnicodeDecodeError:
        log.error(
            f"[{bank_key}] Encoding error on '{file_path.name}'. "
            f"Current: '{config.get('encoding')}'. Try 'latin-1' or 'utf-8-sig'."
        )
        raise
    except Exception as e:
        log.error(f"[{bank_key}] Failed to read '{file_path.name}': {e}")
        raise


def _parse_dates(series: pd.Series, dayfirst: bool, bank_key: str) -> pd.Series:
    """
    Parse date strings (padded or unpadded, 2 or 4 digit year) to formatted strings.
    Two-digit years: 00–68 → 2000–2068, 69–99 → 1969–1999 (Python/pandas standard).
    Output format: DD/MM/YYYY.
    """
    try:
        parsed = pd.to_datetime(series.str.strip(), dayfirst=dayfirst)
        return parsed.dt.strftime("%d/%m/%Y")
    except Exception as e:
        log.error(f"[{bank_key}] Date parsing failed: {e}")
        raise


def _clean_amount_string(series: pd.Series, config: dict) -> pd.Series:
    """Strip currency symbols and thousands separators, return clean numeric strings."""
    s = series.astype(str).str.strip()
    if config.get("strip_currency", True):
        s = s.str.replace(r"[£$€]", "", regex=True)
    sep = config.get("thousands_sep", ",")
    if sep:
        s = s.str.replace(sep, "", regex=False)
    s = s.str.replace(r"\s+", "", regex=True)
    s = s.replace({"": "NaN", "-": "NaN", "–": "NaN", "N/A": "NaN"})
    return s


def _normalize_amount(raw_df: pd.DataFrame, config: dict, bank_key: str) -> pd.Series:
    """
    Produce a single signed Amount Series aligned to output convention:
        negative = expense (money out)
        positive = income  (money in)
    """
    encoding = config["amount_encoding"]

    if encoding == "single_signed":
        col = config["column_map"].get("amount")
        if not col or col not in raw_df.columns:
            raise KeyError(
                f"[{bank_key}] Amount column '{col}' not found. "
                f"Available: {list(raw_df.columns)}"
            )
        amounts = pd.to_numeric(_clean_amount_string(raw_df[col], config), errors="coerce")

        if config.get("positive_is_debit", True):
            # Source: positive = expense → flip to negative
            return -amounts
        else:
            # Source: positive = income → already correct
            return amounts

    elif encoding == "split_debit_credit":
        debit_col  = config.get("debit_col")
        credit_col = config.get("credit_col")
        for col, label in [(debit_col, "debit_col"), (credit_col, "credit_col")]:
            if not col or col not in raw_df.columns:
                raise KeyError(
                    f"[{bank_key}] {label} '{col}' not found. "
                    f"Available: {list(raw_df.columns)}"
                )

        debits  = pd.to_numeric(_clean_amount_string(raw_df[debit_col],  config), errors="coerce").fillna(0.0)
        credits = pd.to_numeric(_clean_amount_string(raw_df[credit_col], config), errors="coerce").fillna(0.0)

        if not config.get("debit_values_positive",  True): debits  = debits.abs()
        if not config.get("credit_values_positive", True): credits = credits.abs()

        # Debits are expenses (negative), credits are income (positive)
        return credits - debits

    else:
        raise ValueError(
            f"[{bank_key}] Unknown amount_encoding '{encoding}'. "
            f"Valid: 'single_signed', 'split_debit_credit'."
        )


# ─────────────────────────────────────────────────────────────────────────────
# PHASE 2 — MAIN NORMALIZATION
# ─────────────────────────────────────────────────────────────────────────────

def normalize_bank_dataframe(bank_key: str, raw_df: pd.DataFrame) -> pd.DataFrame:
    """
    Map a raw bank CSV to the standard output schema.
    Raises KeyError with a clear message if any expected column is absent.
    """
    config    = BANK_CONFIGS[bank_key]
    col_map   = config["column_map"]
    available = list(raw_df.columns)
    out = pd.DataFrame()

    # Date — must be first; scalar columns (Account, Category) only broadcast
    # to existing rows, so rows must exist before those assignments
    date_col = col_map.get("date")
    if not date_col or date_col not in available:
        raise KeyError(f"[{bank_key}] Date column '{date_col}' not in CSV. Available: {available}")
    out["Date"] = _parse_dates(raw_df[date_col], config.get("dayfirst", True), bank_key)

    # Account — assigned after rows exist so scalar broadcasts correctly
    out["Account"] = config["account_label"]

    # Description — strip whitespace, tabs, and surrounding quote artefacts
    # (Barclays Memo field embeds tabs and quote chars in the sample data)
    desc_col = col_map.get("description")
    if not desc_col or desc_col not in available:
        raise KeyError(f"[{bank_key}] Description column '{desc_col}' not in CSV. Available: {available}")
    out["Description"] = (
        raw_df[desc_col]
        .astype(str)
        .str.replace(r"[\t\r\n]+", " ", regex=True)   # collapse embedded tabs/newlines
        .str.replace(r"\s+", " ", regex=True)         # collapse runs of whitespace
        .str.strip()
        .str.strip('"')                               # strip stray surrounding quotes
        .str.strip()
    )

    # Amount
    out["Amount"] = _normalize_amount(raw_df, config, bank_key)

    # Category placeholder — Phase 3 overwrites this
    out["Category"] = "unassigned"

    # Drop rows with null Date or Amount (blank trailing rows, sub-total rows)
    pre = len(out)
    out = out.dropna(subset=["Amount"]).query("Date.notna() and Date != ''").reset_index(drop=True)
    dropped = pre - len(out)
    if dropped:
        log.warning(f"[{bank_key}] Dropped {dropped} row(s) with null Date or Amount.")

    log.info(f"[{bank_key}] Normalized: {len(out)} transactions.")
    return out[OUTPUT_COLUMNS]


# ─────────────────────────────────────────────────────────────────────────────
# PHASE 3 — CATEGORIZATION
# ─────────────────────────────────────────────────────────────────────────────
# Rules live in category_rules.py (same directory as this script).
# Each rule is matched in order — first match wins.
# Unmatched transactions keep Category = "unassigned" as a review signal.
# ─────────────────────────────────────────────────────────────────────────────

def _load_category_rules() -> list[dict]:
    """
    Import CATEGORY_RULES from category_rules.py.
    Fails loudly if the file is missing or malformed — silent failure here
    would produce an entire run of 'unassigned' with no warning.
    """
    script_dir = Path(__file__).parent
    rules_path = script_dir / "category_rules.py"
    if not rules_path.exists():
        raise FileNotFoundError(
            f"category_rules.py not found at {rules_path}. "
            f"Create it from the provided template before running."
        )
    import importlib.util
    spec   = importlib.util.spec_from_file_location("category_rules", rules_path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    rules  = getattr(module, "CATEGORY_RULES", None)
    if rules is None:
        raise AttributeError("category_rules.py must define a CATEGORY_RULES list.")
    log.info(f"Loaded {len(rules)} category rules from {rules_path.name}.")
    return rules


def apply_categories(df: pd.DataFrame, rules: list[dict]) -> pd.DataFrame:
    """
    Apply keyword rules to the Description column.
    Matching is case-insensitive substring by default.
    First match wins — rule order matters.

    Rule keys:
        keywords    list[str]  Substrings to test against Description
        category    str        Value to assign on match
        match_type  str        "contains" (default) | "startswith" | "exact"
        amount_sign str        Optional: "negative" (expenses) | "positive" (income)
                               Restricts rule to matching transaction direction.
    """
    result = df.copy()
    descriptions = result["Description"].str.lower()
    amounts      = result["Amount"]

    for idx, row in result.iterrows():
        desc = descriptions[idx]
        amt  = amounts[idx]

        for rule in rules:
            # Optional amount direction filter
            sign_filter = rule.get("amount_sign")
            if sign_filter == "negative" and amt >= 0:
                continue
            if sign_filter == "positive" and amt <= 0:
                continue

            match_type = rule.get("match_type", "contains")
            matched    = False

            for kw in rule["keywords"]:
                kw_lower = kw.lower()
                if   match_type == "contains"   and kw_lower in desc:      matched = True
                elif match_type == "startswith" and desc.startswith(kw_lower): matched = True
                elif match_type == "exact"      and desc == kw_lower:      matched = True
                if matched:
                    break

            if matched:
                result.at[idx, "Category"] = rule["category"]
                break
        # If no rule matched, Category remains "unassigned"

    matched_count   = (result["Category"] != "unassigned").sum()
    unmatched_count = (result["Category"] == "unassigned").sum()
    log.info(
        f"Categorization: {matched_count} matched, "
        f"{unmatched_count} unassigned "
        f"({unmatched_count/len(result)*100:.1f}% — review these)."
    )
    return result


# ─────────────────────────────────────────────────────────────────────────────
# PHASE 4 — APPEND TO MASTER LEDGER & ARCHIVE SOURCE FILES
# ─────────────────────────────────────────────────────────────────────────────

def append_to_ledger(df: pd.DataFrame) -> None:
    """
    Append normalized transactions to the master CSV ledger.
    Creates the file with a header if it doesn't exist yet.
    Never overwrites — always appends.
    """
    STATEMENTS_DIR.mkdir(parents=True, exist_ok=True)

    write_header = not MASTER_LEDGER.exists() or MASTER_LEDGER.stat().st_size == 0

    df.to_csv(
        MASTER_LEDGER,
        mode="a",
        header=write_header,
        index=False,
    )

    action = "Created" if write_header else "Appended"
    log.info(f"{action} {len(df)} rows → {MASTER_LEDGER}")


def archive_source_files(bank_files: dict[str, Path]) -> None:
    """
    Move raw bank CSV files out of Downloads into the Statements directory.
    Banks with generic filenames (AMEX 'activity.csv', Barclays 'data.csv')
    are renamed with a datestamp to prevent overwrite on next month's run.
    Lloyds files already contain a date in their filename.
    """
    STATEMENTS_DIR.mkdir(parents=True, exist_ok=True)
    today = datetime.today().strftime("%Y%m%d")

    for bank_key, src_path in bank_files.items():
        if bank_key in GENERIC_FILENAME_BANKS:
            # Rename to <bank>_<original_stem>_<date>.<ext>
            stem = src_path.stem
            ext  = src_path.suffix
            dest_name = f"{bank_key.lower()}_{stem}_{today}{ext}"
        else:
            dest_name = src_path.name  # e.g. Lloyds: 9091_DDMMYYYY.csv already unique

        dest_path = STATEMENTS_DIR / dest_name

        if dest_path.exists():
            log.warning(
                f"[{bank_key}] Archive file already exists: {dest_name}. "
                f"Skipping move to avoid overwrite — remove the existing file manually."
            )
            continue

        shutil.move(str(src_path), str(dest_path))
        log.info(f"[{bank_key}] Archived: {src_path.name} → {dest_path}")


# ─────────────────────────────────────────────────────────────────────────────
# ORCHESTRATION
# ─────────────────────────────────────────────────────────────────────────────

def run() -> None:
    log.info("=" * 60)
    log.info("Budget Ingest — Phases 1–4")
    log.info("=" * 60)

    # Phase 1 — detect
    bank_files = detect_bank_files()

    # Phase 2 — normalize
    normalized_frames: list[pd.DataFrame] = []
    failed: list[str] = []

    for bank_key, file_path in bank_files.items():
        try:
            raw_df  = _read_raw_csv(bank_key, file_path)
            norm_df = normalize_bank_dataframe(bank_key, raw_df)
            normalized_frames.append(norm_df)
        except Exception as e:
            log.error(f"[{bank_key}] Normalization failed — skipping: {e}")
            failed.append(bank_key)

    if not normalized_frames:
        log.error("No data normalized. Exiting without writing output.")
        sys.exit(1)

    combined = (
        pd.concat(normalized_frames, ignore_index=True)
          .sort_values("Date")
          .reset_index(drop=True)
    )

    if failed:
        log.warning(f"Banks skipped due to errors: {failed}")

    # Phase 3 — categorize
    rules     = _load_category_rules()
    combined  = apply_categories(combined, rules)

    # Preview
    log.info(f"\n{'─'*60}")
    log.info(f"Preview — first 10 rows:")
    log.info(f"{'─'*60}")
    print(combined.head(10).to_string(index=False))
    log.info(f"\nTransactions by account:\n{combined['Account'].value_counts().to_string()}")
    log.info(f"Date range: {combined['Date'].min()} → {combined['Date'].max()}")
    log.info(f"{'─'*60}")

    # Phase 4 — append + archive
    append_to_ledger(combined)
    archive_source_files({k: v for k, v in bank_files.items() if k not in failed})

    log.info("Done.")


# ─────────────────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    run()

"""Shared loading and cleaning helpers, used by both notebooks."""

from pathlib import Path

import numpy as np
import pandas as pd

ROOT_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = ROOT_DIR / "data"


def load_listings(path: Path = DATA_DIR / "listings.csv") -> pd.DataFrame:
    """Load the raw listings table (106 columns, ~85k London listings)."""
    return pd.read_csv(path, low_memory=False)


def parse_money(series: pd.Series) -> pd.Series:
    """Convert a '$1,234.00'-style string column to float."""
    return pd.to_numeric(
        series.astype(str).str.replace(r"[$,]", "", regex=True), errors="coerce"
    )


def parse_tf_bool(series: pd.Series) -> pd.Series:
    """Convert a 't'/'f' string column to a nullable boolean."""
    return series.map({"t": True, "f": False}).astype("boolean")


def clean_price(df: pd.DataFrame, price_col: str = "price", cap: float = 1000.0) -> pd.DataFrame:
    """Parse `price_col`, drop non-positive/missing/outlier rows, add log_price.

    Rows with price <= 0, missing, or above `cap` (£/night) are dropped —
    a price column that wide right-skews badly, so OLS on raw price would be
    dominated by a handful of luxury listings.
    """
    out = df.copy()
    out["price_num"] = parse_money(out[price_col])
    out = out.loc[out["price_num"].notna() & (out["price_num"] > 0) & (out["price_num"] <= cap)].copy()
    out["log_price"] = np.log(out["price_num"])
    return out

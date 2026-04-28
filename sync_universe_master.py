from __future__ import annotations

import argparse
from pathlib import Path

import numpy as np
import pandas as pd


BASE_DIR = Path(__file__).resolve().parent
UNIVERSE_PATH = BASE_DIR / "universe.csv"
ASSUMPTIONS_PATH = BASE_DIR / "assumptions.csv"
EPS_CACHE_PATH = BASE_DIR / "eps_cache.csv"


DEFAULT_ASSUMPTION = {
    "is_loss_making": 0,
    "eps_growth_3y_pct": 10.0,
    "target_pe_bear": 8.0,
    "target_pe_base": 12.0,
    "target_pe_bull": 16.0,
    "manual_forward_eps": np.nan,
    "max_position_pct": 3.0,
    "sector_group": "기타",
}


def _read_universe(path: Path) -> pd.DataFrame:
    universe = pd.read_csv(path, dtype={"ticker": str})
    if "ticker" not in universe.columns:
        raise ValueError("universe.csv must contain ticker column")
    universe = universe.copy()
    universe["ticker"] = universe["ticker"].astype(str).str.zfill(6)
    return universe


def _read_assumptions(path: Path) -> pd.DataFrame:
    if not path.exists():
        return pd.DataFrame({"ticker": []})
    assumptions = pd.read_csv(path, dtype={"ticker": str})
    if "ticker" not in assumptions.columns:
        assumptions["ticker"] = ""
    assumptions["ticker"] = assumptions["ticker"].astype(str).str.zfill(6)
    return assumptions


def sync_assumptions_with_universe(universe: pd.DataFrame, assumptions: pd.DataFrame) -> pd.DataFrame:
    assumptions = assumptions.copy()
    base = pd.DataFrame({"ticker": universe["ticker"].astype(str).str.zfill(6)})
    merged = base.merge(assumptions, on="ticker", how="left")

    for key, value in DEFAULT_ASSUMPTION.items():
        if key not in merged.columns:
            merged[key] = value
        merged[key] = merged[key].where(~merged[key].isna(), value)

    return merged


def maybe_enrich_sector_from_eps_cache(assumptions: pd.DataFrame) -> pd.DataFrame:
    if not EPS_CACHE_PATH.exists():
        return assumptions

    try:
        cache = pd.read_csv(EPS_CACHE_PATH, dtype={"ticker": str})
    except Exception:
        return assumptions

    if cache.empty or "ticker" not in cache.columns or "naver_sector" not in cache.columns:
        return assumptions

    cache["ticker"] = cache["ticker"].astype(str).str.zfill(6)
    sector_map = cache.dropna(subset=["ticker"]).set_index("ticker")["naver_sector"].astype(str).to_dict()

    out = assumptions.copy()
    if "sector_group" not in out.columns:
        out["sector_group"] = out["ticker"].map(sector_map).fillna(DEFAULT_ASSUMPTION["sector_group"])
        return out

    current = out["sector_group"].astype(str).str.strip()
    fill_mask = (current == "") | (current == DEFAULT_ASSUMPTION["sector_group"])
    out.loc[fill_mask, "sector_group"] = out.loc[fill_mask, "ticker"].map(sector_map).fillna(out.loc[fill_mask, "sector_group"])
    return out


def sync_universe_master() -> pd.DataFrame:
    if not UNIVERSE_PATH.exists():
        raise FileNotFoundError(f"Missing universe.csv: {UNIVERSE_PATH}")

    universe = _read_universe(UNIVERSE_PATH)
    assumptions = _read_assumptions(ASSUMPTIONS_PATH)
    merged = sync_assumptions_with_universe(universe, assumptions)
    merged = maybe_enrich_sector_from_eps_cache(merged)
    merged.to_csv(ASSUMPTIONS_PATH, index=False, encoding="utf-8-sig")
    print(f"[OK] Saved: {ASSUMPTIONS_PATH} ({len(merged)} rows)")
    return merged


def main() -> int:
    parser = argparse.ArgumentParser(description="Sync universe.csv and assumptions.csv")
    _ = parser.parse_args()
    sync_universe_master()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
"""Manage portfolio positions from scored signals."""
from __future__ import annotations

from datetime import datetime
from pathlib import Path
import os
import argparse

import numpy as np
import pandas as pd

import build_daily_report as report


BASE_DIR = Path(__file__).resolve().parents[2]
OUTPUT_DIR = BASE_DIR / "output"


def _latest_file(pattern: str) -> Path | None:
    candidates = [path for path in OUTPUT_DIR.glob(pattern) if path.is_file()]
    if not candidates:
        return None
    return max(candidates, key=lambda path: path.stat().st_mtime)


def _read_csv(path: Path) -> pd.DataFrame:
    return pd.read_csv(path, keep_default_na=True)


def _safe_write_csv(df: pd.DataFrame, path: Path) -> Path:
    tmp = path.with_name(f"{path.stem}.tmp{path.suffix}")
    df.to_csv(tmp, index=False, encoding="utf-8-sig")
    os.replace(tmp, path)
    return path


def _load_scored(path: str | None = None) -> pd.DataFrame:
    if path:
        p = Path(path)
    else:
        p = _latest_file("scored_report_*.csv")
        if p is None:
            raise FileNotFoundError("No scored_report found in output directory")
    return _read_csv(p)


def _build_positions(scored: pd.DataFrame) -> pd.DataFrame:
    # Ensure expected numeric columns
    if "suggested_weight_pct" in scored.columns:
        scored["suggested_weight_pct"] = scored["suggested_weight_pct"].fillna(0).astype(float)
    else:
        scored["suggested_weight_pct"] = 0.0

    if "total_score" in scored.columns:
        scored["total_score"] = scored["total_score"].fillna(0).astype(float)
    else:
        scored["total_score"] = 0.0

    # Filter out excluded actions
    if "combined_action" in scored.columns:
        keep = scored[scored["combined_action"].isin(["추천_매수진입", "진입_관심", "관심종목"])]
    else:
        keep = scored.copy()
    if keep.empty:
        # fallback: top 10 by score
        keep = scored.sort_values(by=["total_score"], ascending=False).head(10).copy()

    # Normalize suggested weights so they sum to at most 100%
    weights = keep["suggested_weight_pct"].astype(float).clip(lower=0)
    total = weights.sum()
    if total <= 0:
        # assign equal small allocations up to cap 3% each
        cap = 3.0
        n = len(keep)
        if n == 0:
            return pd.DataFrame(columns=["date","suggested_rank","ticker","name","market","combined_action","suggested_weight_pct","position_pct"])
        w = min(cap, 100.0 / n)
        pos_pct = [w] * n
    else:
        scale = min(1.0, 100.0 / total)
        pos_pct = (weights * scale).round(4).tolist()

    keep = keep.reset_index(drop=True).copy()
    keep.insert(0, "position_rank", range(1, len(keep) + 1))
    keep["position_pct"] = pos_pct[: len(keep)]

    out_cols = [
        "date",
        "position_rank",
        "suggested_rank",
        "name",
        "ticker",
        "market",
        "combined_action",
        "suggested_weight_pct",
        "position_pct",
        "total_score",
    ]
    available = [c for c in out_cols if c in keep.columns]
    return keep[available]


def main() -> int:
    parser = argparse.ArgumentParser(description="Manage positions from scored report")
    parser.add_argument("--input", type=str, default="", help="Optional scored report path")
    parser.add_argument("--output", type=str, default="", help="Optional positions output path")
    args = parser.parse_args()

    scored = _load_scored(args.input or None)
    positions = _build_positions(scored)

    today = datetime.now().strftime("%Y-%m-%d")
    out_path = Path(args.output) if args.output else OUTPUT_DIR / f"positions_{today}.csv"
    out_path.parent.mkdir(parents=True, exist_ok=True)

    out_path = _safe_write_csv(positions, out_path)
    print(f"[Manage] Saved: {out_path} ({len(positions)} rows)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
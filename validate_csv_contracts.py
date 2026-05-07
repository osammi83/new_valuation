from __future__ import annotations

import argparse
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

import pandas as pd


BASE_DIR = Path(__file__).resolve().parent
DEFAULT_REGISTRY_PATH = BASE_DIR / "schema_registry.csv"


@dataclass(frozen=True)
class RegistryEntry:
    dataset: str
    file_glob: str
    required_columns: list[str]
    key_columns: list[str]
    enum_rules: dict[str, list[str]]
    enabled: bool
    notes: str


def _split_list(value: str | float | int | None) -> list[str]:
    text = "" if value is None else str(value).strip()
    if not text:
        return []
    return [part.strip() for part in text.split("|") if part.strip()]


def _parse_enum_rules(value: str | float | int | None) -> dict[str, list[str]]:
    text = "" if value is None else str(value).strip()
    if not text:
        return {}

    rules: dict[str, list[str]] = {}
    for rule in text.split(";"):
        rule = rule.strip()
        if not rule or "=" not in rule:
            continue
        column, allowed = rule.split("=", 1)
        rules[column.strip()] = [item.strip() for item in allowed.split("|") if item.strip()]
    return rules


def _parse_enabled(value: str | float | int | None) -> bool:
    text = "" if value is None else str(value).strip().lower()
    return text in {"1", "true", "t", "y", "yes", "on"}


def load_registry(registry_path: Path) -> list[RegistryEntry]:
    registry = pd.read_csv(registry_path, dtype=str, keep_default_na=False)
    entries: list[RegistryEntry] = []
    for row in registry.to_dict(orient="records"):
        entries.append(
            RegistryEntry(
                dataset=str(row.get("dataset", "")).strip(),
                file_glob=str(row.get("file_glob", "")).strip(),
                required_columns=_split_list(row.get("required_columns")),
                key_columns=_split_list(row.get("key_columns")),
                enum_rules=_parse_enum_rules(row.get("enum_rules")),
                enabled=_parse_enabled(row.get("enabled")),
                notes=str(row.get("notes", "")).strip(),
            )
        )
    return entries


def _read_csv(path: Path) -> pd.DataFrame:
    return pd.read_csv(path, dtype=str, keep_default_na=False)


def _find_files(root: Path, pattern: str) -> list[Path]:
    files: list[Path] = []
    for token in pattern.split("|"):
        token = token.strip()
        if not token:
            continue
        files.extend(p for p in root.glob(token) if p.is_file())
    unique_files = sorted({path.resolve(): path for path in files}.values(), key=lambda path: path.stat().st_mtime)
    return unique_files


def _find_latest_file(root: Path, pattern: str) -> Path | None:
    files = _find_files(root, pattern)
    if not files:
        return None
    return max(files, key=lambda path: path.stat().st_mtime)


def _check_required_columns(df: pd.DataFrame, required_columns: Iterable[str]) -> list[str]:
    return [column for column in required_columns if column not in df.columns]


def _check_keys(df: pd.DataFrame, key_columns: list[str]) -> list[str]:
    issues: list[str] = []
    existing = [column for column in key_columns if column in df.columns]
    if not existing:
        return issues

    key_frame = df[existing].fillna("").astype(str)
    empty_mask = key_frame.apply(lambda s: s.str.strip() == "").any(axis=1)
    if empty_mask.any():
        issues.append(f"empty key rows={int(empty_mask.sum())}")

    duplicate_mask = key_frame.duplicated(keep=False)
    if duplicate_mask.any():
        issues.append(f"duplicate key rows={int(duplicate_mask.sum())}")

    return issues


def _check_enums(df: pd.DataFrame, enum_rules: dict[str, list[str]]) -> list[str]:
    issues: list[str] = []
    for column, allowed in enum_rules.items():
        if column not in df.columns:
            continue
        series = df[column].fillna("").astype(str).str.strip()
        invalid_values = sorted({value for value in series.unique() if value and value not in allowed})
        if invalid_values:
            issues.append(f"{column}: {', '.join(invalid_values)}")
    return issues


def validate_registry_entry(root: Path, entry: RegistryEntry) -> list[str]:
    if not entry.enabled:
        return []

    issues: list[str] = []
    latest_file = _find_latest_file(root, entry.file_glob)
    if latest_file is None:
        return [f"{entry.dataset}: no files matched {entry.file_glob}"]

    try:
        df = _read_csv(latest_file)
    except Exception as exc:
        return [f"{latest_file}: unreadable ({exc})"]

    missing_columns = _check_required_columns(df, entry.required_columns)
    if missing_columns:
        issues.append(f"{latest_file}: missing columns {', '.join(missing_columns)}")

    for issue in _check_keys(df, entry.key_columns):
        issues.append(f"{latest_file}: {issue}")

    for issue in _check_enums(df, entry.enum_rules):
        issues.append(f"{latest_file}: {issue}")

    return issues


def main() -> int:
    parser = argparse.ArgumentParser(description="Validate CSV contracts from schema_registry.csv")
    parser.add_argument("--registry", default=str(DEFAULT_REGISTRY_PATH), help="Path to schema_registry.csv")
    parser.add_argument("--root", default=str(BASE_DIR), help="Workspace root for relative file globs")
    args = parser.parse_args()

    registry_path = Path(args.registry)
    root = Path(args.root)

    if not registry_path.exists():
        print(f"[Contract] registry not found: {registry_path}")
        return 1

    entries = load_registry(registry_path)
    all_issues: list[str] = []
    checked_files = 0

    for entry in entries:
        if not entry.enabled:
            continue
        matched_file = _find_latest_file(root, entry.file_glob)
        checked_files += 1 if matched_file is not None else 0
        all_issues.extend(validate_registry_entry(root, entry))

    if all_issues:
        print("[Contract] validation failed")
        for issue in all_issues:
            print(f"[Contract] {issue}")
        return 1

    print(f"[Contract] validation passed for {checked_files} file(s)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
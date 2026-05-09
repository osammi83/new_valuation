from __future__ import annotations

import argparse
import json
from datetime import datetime
from pathlib import Path

import joblib
import numpy as np
import pandas as pd
from sklearn.compose import ColumnTransformer
from sklearn.ensemble import HistGradientBoostingClassifier
from sklearn.impute import SimpleImputer
from sklearn.inspection import permutation_importance
from sklearn.metrics import accuracy_score, roc_auc_score
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import OneHotEncoder


BASE_DIR = Path(__file__).resolve().parents[2]
OUTPUT_DIR = BASE_DIR / "output"
ARTIFACT_DIR = BASE_DIR / "artifacts"
MODEL_REGISTRY_PATH = BASE_DIR / "model_registry.csv"
FEATURE_IMPORTANCE_PATH = BASE_DIR / "feature_importance.csv"


NUMERIC_FEATURES = [
    "醫낃?",
    "20?쇱씠??,
    "60?쇱씠??,
    "120?쇱씠??,
    "200?쇱씠??,
    "200?쇱꽑?곷떒?щ?",
    "RSI14",
    "MACD?덉뒪?좉렇??,
    "嫄곕옒?됰퉬??0??,
    "20?쇰룎??,
    "5?쇱닔?듬쪧(%)",
    "20?쇱닔?듬쪧(%)",
    "?꾪뻾EPS(DART)",
    "而⑥꽱?쒖뒪EPS(?ㅽ겕??",
    "?먮룞?좏뻾EPS",
    "?섎룞?좏뻾EPS",
    "紐⑤뜽EPS",
    "?꾩옱PER",
    "?곸젙二쇨?_湲곗?",
    "?곸듅?щ젰(%)",
    "?곸옄?щ?",
    "理쒕?鍮꾩쨷(%)",
    "?덉쭚鍮꾩쨷諛곗닔",
    "volume_ratio_pct_rank",
]


CATEGORICAL_FEATURES = ["?쒖옣", "?뱁꽣洹몃９", "留덉폆?덉쭚", "EPS?뚯뒪", "?먮낯EPS異쒖쿂"]


def _latest_files(pattern: str) -> list[Path]:
    files = [path for path in OUTPUT_DIR.glob(pattern) if path.is_file()]
    return sorted(files, key=lambda path: path.stat().st_mtime)


def _load_latest_frame(pattern: str) -> pd.DataFrame:
    files = _latest_files(pattern)
    if not files:
        return pd.DataFrame()
    frames = [pd.read_csv(path, keep_default_na=True) for path in files]
    return pd.concat(frames, ignore_index=True)


def _load_model_registry() -> pd.DataFrame:
    if not MODEL_REGISTRY_PATH.exists():
        return pd.DataFrame()
    return pd.read_csv(MODEL_REGISTRY_PATH, keep_default_na=True)


def _deactivate_previous_models(task_type: str) -> list[str]:
    registry = _load_model_registry()
    if registry.empty or "task_type" not in registry.columns or "is_active" not in registry.columns:
        return []

    task_mask = registry["task_type"].astype(str) == task_type
    active_mask = task_mask & pd.to_numeric(registry["is_active"], errors="coerce").fillna(0).astype(int).eq(1)
    model_ids = registry.loc[active_mask, "model_id"].astype(str).tolist()
    if not model_ids:
        return []

    registry.loc[active_mask, "is_active"] = 0
    MODEL_REGISTRY_PATH.parent.mkdir(parents=True, exist_ok=True)
    registry.to_csv(MODEL_REGISTRY_PATH, index=False, encoding="utf-8-sig")
    return model_ids


def _prepare_training_frame() -> pd.DataFrame:
    report = _load_latest_frame("?곸꽭由ы룷??*.csv")
    if report.empty:
        raise FileNotFoundError(f"Missing report CSV files in {OUTPUT_DIR}")

    if "湲곗??? not in report.columns or "醫낅ぉ肄붾뱶" not in report.columns:
        raise RuntimeError("?곸꽭由ы룷??CSV must include 湲곗???and 醫낅ぉ肄붾뱶")

    report["湲곗???] = report["湲곗???].astype(str)
    report["醫낅ぉ肄붾뱶"] = report["醫낅ぉ肄붾뱶"].astype(str).str.zfill(6)

    for column in NUMERIC_FEATURES:
        if column in report.columns:
            report[column] = pd.to_numeric(report[column], errors="coerce")

    for column in CATEGORICAL_FEATURES:
        if column in report.columns:
            report[column] = report[column].astype(str).fillna("")

    if "寃고빀?≪뀡" not in report.columns:
        raise RuntimeError("?곸꽭由ы룷??CSV must include 寃고빀?≪뀡")

    report["label_alpha"] = report["寃고빀?≪뀡"].isin(["理쒖쥌留ㅼ닔?꾨낫", "吏꾩엯?湲?]).astype(int)
    report["label_entry"] = (report["寃고빀?≪뀡"] == "理쒖쥌留ㅼ닔?꾨낫").astype(int)
    return report


def _build_pipeline(numeric_features: list[str], categorical_features: list[str]) -> Pipeline:
    numeric_transformer = Pipeline(
        steps=[
            ("imputer", SimpleImputer(strategy="median")),
        ]
    )
    categorical_transformer = Pipeline(
        steps=[
            ("imputer", SimpleImputer(strategy="most_frequent")),
            ("onehot", OneHotEncoder(handle_unknown="ignore", sparse_output=False)),
        ]
    )
    preprocessor = ColumnTransformer(
        transformers=[
            ("num", numeric_transformer, numeric_features),
            ("cat", categorical_transformer, categorical_features),
        ],
        remainder="drop",
        verbose_feature_names_out=False,
    )
    model = HistGradientBoostingClassifier(max_depth=4, learning_rate=0.05, max_iter=200, random_state=42)
    return Pipeline(steps=[("preprocessor", preprocessor), ("model", model)])


def _fit_task(df: pd.DataFrame, task_type: str) -> tuple[Pipeline, dict[str, object], pd.DataFrame, pd.Series, list[str]]:
    target_column = "label_alpha" if task_type == "alpha" else "label_entry"
    numeric_features = [column for column in NUMERIC_FEATURES if column in df.columns and df[column].notna().any()]
    categorical_features = [column for column in CATEGORICAL_FEATURES if column in df.columns and df[column].nunique(dropna=True) > 0]
    feature_columns = numeric_features + categorical_features
    work = df.loc[:, ["湲곗???, "醫낅ぉ肄붾뱶", target_column] + feature_columns].copy()
    work = work.dropna(subset=[target_column])
    if work.empty:
        raise RuntimeError(f"No training rows available for task={task_type}")

    dates = sorted(work["湲곗???].dropna().astype(str).unique().tolist())
    if len(dates) >= 2:
        train_dates = set(dates[:-1])
        test_dates = set(dates[-1:])
    else:
        train_dates = set(dates)
        test_dates = set(dates)

    train_df = work.loc[work["湲곗???].isin(train_dates)].copy()
    test_df = work.loc[work["湲곗???].isin(test_dates)].copy()
    if train_df.empty or test_df.empty:
        raise RuntimeError(f"Insufficient train/test split for task={task_type}")

    X_train = train_df.loc[:, feature_columns]
    y_train = train_df[target_column].astype(int)
    X_test = test_df.loc[:, feature_columns]
    y_test = test_df[target_column].astype(int)

    pipeline = _build_pipeline(numeric_features, categorical_features)
    pipeline.fit(X_train, y_train)

    test_proba = pipeline.predict_proba(X_test)[:, 1]
    test_pred = (test_proba >= 0.5).astype(int)
    metrics = {
        "accuracy": float(accuracy_score(y_test, test_pred)),
        "roc_auc": float(roc_auc_score(y_test, test_proba)) if y_test.nunique() > 1 else float("nan"),
        "train_rows": int(len(train_df)),
        "test_rows": int(len(test_df)),
        "train_start": str(train_df["湲곗???].min()),
        "train_end": str(train_df["湲곗???].max()),
        "feature_version": "daily_features_v1",
        "positive_rate": float(y_train.mean()),
        "feature_columns": feature_columns,
        "test_positive_rate": float(y_test.mean()),
    }
    return pipeline, metrics, X_test, y_test, feature_columns


def _write_registry_row(model_id: str, task_type: str, artifact_path: Path, metrics: dict[str, object]) -> None:
    row = {
        "model_id": model_id,
        "model_family": "hist_gradient_boosting",
        "task_type": task_type,
        "train_start": metrics["train_start"],
        "train_end": metrics["train_end"],
        "feature_version": metrics["feature_version"],
        "score_primary": metrics["roc_auc"] if np.isfinite(metrics["roc_auc"]) else metrics["accuracy"],
        "is_active": 1,
        "artifact_path": str(artifact_path),
        "created_at": datetime.now().isoformat(timespec="seconds"),
        "train_rows": metrics["train_rows"],
        "test_rows": metrics["test_rows"],
        "positive_rate": metrics["positive_rate"],
        "test_positive_rate": metrics["test_positive_rate"],
    }
    fieldnames = list(row.keys())
    MODEL_REGISTRY_PATH.parent.mkdir(parents=True, exist_ok=True)
    write_header = not MODEL_REGISTRY_PATH.exists()
    with MODEL_REGISTRY_PATH.open("a", newline="", encoding="utf-8-sig") as f:
        import csv

        writer = csv.DictWriter(f, fieldnames=fieldnames)
        if write_header:
            writer.writeheader()
        writer.writerow(row)


def _write_feature_importance(model_id: str, task_type: str, pipeline: Pipeline, X_test: pd.DataFrame, y_test: pd.Series) -> None:
    result = permutation_importance(pipeline, X_test, y_test, n_repeats=10, random_state=42, scoring="accuracy")
    importances = pd.DataFrame(
        {
            "task_type": task_type,
            "model_id": model_id,
            "feature_name": list(X_test.columns),
            "importance": result.importances_mean,
        }
    ).sort_values(by="importance", ascending=False)
    importances["rank"] = range(1, len(importances) + 1)
    FEATURE_IMPORTANCE_PATH.parent.mkdir(parents=True, exist_ok=True)
    write_header = not FEATURE_IMPORTANCE_PATH.exists()
    importances.to_csv(FEATURE_IMPORTANCE_PATH, index=False, mode="a", header=write_header, encoding="utf-8-sig")


def train_task(task_type: str) -> dict[str, object]:
    df = _prepare_training_frame()
    pipeline, metrics, X_test, y_test, feature_columns = _fit_task(df, task_type)

    model_id = f"{task_type}_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
    ARTIFACT_DIR.mkdir(parents=True, exist_ok=True)
    artifact_path = ARTIFACT_DIR / f"{model_id}.joblib"
    joblib.dump(pipeline, artifact_path)

    metrics.pop("feature_columns")
    _write_feature_importance(model_id, task_type, pipeline, X_test, y_test)
    deactivated_models = _deactivate_previous_models(task_type)
    _write_registry_row(model_id, task_type, artifact_path, metrics)

    summary = {
        "model_id": model_id,
        "task_type": task_type,
        "artifact_path": str(artifact_path),
        "accuracy": metrics["accuracy"],
        "roc_auc": metrics["roc_auc"],
        "train_rows": metrics["train_rows"],
        "test_rows": metrics["test_rows"],
        "deactivated_models": len(deactivated_models),
    }
    return summary


def main() -> int:
    parser = argparse.ArgumentParser(description="Train baseline models from daily CSV outputs")
    parser.add_argument("--task", choices=["alpha", "entry", "both"], default="both")
    args = parser.parse_args()

    tasks = ["alpha", "entry"] if args.task == "both" else [args.task]
    summaries = [train_task(task) for task in tasks]

    print(f"[Model] Saved registry: {MODEL_REGISTRY_PATH}")
    print(f"[Model] Saved feature importance: {FEATURE_IMPORTANCE_PATH}")
    for summary in summaries:
        print(
            f"[Model] {summary['task_type']}: id={summary['model_id']}, accuracy={summary['accuracy']:.3f}, roc_auc={summary['roc_auc']:.3f}, train={summary['train_rows']}, test={summary['test_rows']}"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

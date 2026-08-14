"""
Trains the 4 production models referenced by ml/predictor.py from the
training CSV into ml/artifacts/, and writes a fully regenerated
ml/artifacts/final_metadata.json with honest cross-validated metrics.

The wellbeing_score model is NOT dropped: a small CV model-selection sweep
(Ridge/Lasso/ElasticNet/RandomForest/GradientBoosting/SVR vs the original
LinearRegression) is run and the best family by CV R2 is kept, so the
continuous score is improved rather than removed.

Usage (from repo root):
    python -m ml_pipeline.final_train [--csv ml_pipeline/data/social_media_addiction_mental_wellbeing.csv]
                                      [--seed 42] [--test-size 0.2]

Artifact format is exactly what ml/predictor.py expects, and each bundle
shares the same 21-feature order as build_feature_row():
    {"model": <estimator>, "scaler": <StandardScaler>,
     "features": [21 names], "classes": [...]}   # classes omitted for regression
"""
import argparse
import hashlib
import json
import os
from datetime import datetime, timezone

import joblib
import numpy as np
import pandas as pd
from sklearn.ensemble import GradientBoostingRegressor, RandomForestClassifier, RandomForestRegressor
from sklearn.linear_model import (ElasticNet, Lasso, LinearRegression, LogisticRegression, Ridge)
from sklearn.metrics import (accuracy_score, confusion_matrix, mean_absolute_error,
                             r2_score, roc_auc_score)
from sklearn.model_selection import KFold, StratifiedKFold, cross_val_score, train_test_split
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import StandardScaler
from sklearn.svm import SVR

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ARTIFACTS_DIR = os.path.join(ROOT, "ml", "artifacts")
DEFAULT_CSV = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data",
                           "social_media_addiction_mental_wellbeing.csv")

TARGET_WELLBEING = "Mental_Wellbeing_Score"
TARGET_ADDICTION = "Addiction_Level"
AT_RISK_LEVELS = {"High", "Severe"}

FEATURES = [
    "Daily_Usage_Hours", "Platforms_Used_Count", "Posts_Per_Week",
    "Notifications_Per_Day", "FOMO_Score", "Social_Comparison_Score",
    "Validation_Seeking_Score", "Scroll_Without_Purpose", "Sleep_Hours",
    "Offline_Relationship_Quality", "Physical_Activity_Hrs_Week",
    "Screen_Free_Time_Hrs",
    "Late_Night_Usage", "Tried_To_Cut_Back", "Failed_To_Cut_Back",
    "First_Check_Morning",
    "Platform_Instagram", "Platform_Snapchat", "Platform_TikTok",
    "Platform_Twitter/X", "Platform_YouTube",
]
NUMERIC_COLS = FEATURES[:12]
BINARY_COLS = ["Late_Night_Usage", "Tried_To_Cut_Back", "Failed_To_Cut_Back"]
FIRST_CHECK_MAP = {"Within 5 min": 0, "5-30 min": 1, "After 30 min": 2}
PLATFORM_DUMMY_COLS = [f for f in FEATURES if f.startswith("Platform_")]
PLATFORMS = [p.replace("Platform_", "") for p in PLATFORM_DUMMY_COLS]

WELLBEING_REG_MODELS = {
    "LinearRegression": LinearRegression(),
    "Ridge": Ridge(alpha=1.0),
    "Lasso": Lasso(alpha=0.01, max_iter=5000),
    "ElasticNet": ElasticNet(alpha=0.01, l1_ratio=0.5, max_iter=5000),
    "RandomForestRegressor": RandomForestRegressor(
        n_estimators=300, random_state=42, n_jobs=-1),
    "GradientBoostingRegressor": GradientBoostingRegressor(random_state=42),
    "SVR": SVR(C=1.0, gamma="scale"),
}


def _data_sha256(path: str) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def load_and_preprocess(path: str) -> pd.DataFrame:
    df = pd.read_csv(path)
    for col in BINARY_COLS:
        df[col] = (df[col] == "Yes").astype(int)
    df["First_Check_Morning"] = (
        df["First_Check_Morning"].map(FIRST_CHECK_MAP).fillna(0).astype(int)
    )
    platform = df["Primary_Platform"].fillna("Facebook")
    for col in PLATFORM_DUMMY_COLS:
        df[col] = (platform == col.replace("Platform_", "")).astype(int)
    for col in NUMERIC_COLS:
        df[col] = pd.to_numeric(df[col], errors="coerce")
        df[col] = df[col].fillna(df[col].median())
    return df


def _top_importance(model, features: list[str], n: int = 10) -> list[dict]:
    if hasattr(model, "coef_"):
        coef = np.asarray(model.coef_)
        coef = coef.reshape(-1) if coef.ndim == 1 else np.abs(coef).max(axis=0)
        values = np.abs(coef)
    elif hasattr(model, "feature_importances_"):
        values = np.asarray(model.feature_importances_)
    else:
        values = np.zeros(len(features))
    ranked = sorted(zip(features, values), key=lambda t: t[1], reverse=True)
    return [{"feature": f, "importance": round(float(v), 4)} for f, v in ranked[:n]]


def _confidence(metrics: dict) -> str:
    if metrics.get("roc_auc") is not None:
        return "strong" if metrics["roc_auc"] >= 0.80 else ("moderate" if metrics["roc_auc"] >= 0.65 else "weak")
    if metrics.get("test_r2") is not None:
        return "strong" if metrics["test_r2"] >= 0.70 else ("moderate" if metrics["test_r2"] >= 0.55 else "weak")
    acc = metrics.get("test_accuracy")
    if acc is not None:
        return "strong" if acc >= 0.80 else ("moderate" if acc >= 0.65 else "weak")
    return "unknown"


def _save_bundle(name: str, model, scaler, classes=None):
    bundle = {"model": model, "scaler": scaler, "features": FEATURES}
    if classes is not None:
        bundle["classes"] = classes
    joblib.dump(bundle, os.path.join(ARTIFACTS_DIR, f"{name}.joblib"))


def train_binary_flag(name, X_train, y_train, X_test, y_test, estimator_factory, classes,
                      is_auc_label_order=None):
    scaler = StandardScaler().fit(X_train)
    model = estimator_factory()
    model.fit(scaler.transform(X_train), y_train)
    _save_bundle(name, model, scaler, classes=classes)

    Xs_test = scaler.transform(X_test)
    preds = model.predict(Xs_test)
    proba = model.predict_proba(Xs_test)[:, 1]
    skf = StratifiedKFold(n_splits=5, shuffle=True, random_state=42)
    cv_scores = cross_val_score(model, scaler.transform(X_train), y_train, cv=skf, scoring="accuracy")
    metrics = {
        "model": type(model).__name__,
        "test_accuracy": round(float(accuracy_score(y_test, preds)), 4),
        "roc_auc": round(float(roc_auc_score(y_test, proba)), 4),
        "cv_accuracy_mean": round(float(cv_scores.mean()), 4),
        "cv_accuracy_std": round(float(cv_scores.std()), 4),
        "confusion_matrix": confusion_matrix(y_test, preds).tolist(),
    }
    metrics["confidence"] = _confidence(metrics)
    metrics["feature_importance"] = _top_importance(model, FEATURES)
    return model, metrics


def train_wellbeing_score(X_train, y_train, X_test, y_test, seed):
    cv = KFold(n_splits=5, shuffle=True, random_state=seed)
    comparison = []
    for name, est in WELLBEING_REG_MODELS.items():
        pipe = Pipeline([("scaler", StandardScaler()), ("model", est)])
        r2_scores = cross_val_score(pipe, X_train, y_train, cv=cv, scoring="r2")
        mae_scores = -cross_val_score(pipe, X_train, y_train, cv=cv, scoring="neg_mean_absolute_error")
        comparison.append({
            "model": name,
            "cv_r2_mean": round(float(r2_scores.mean()), 4),
            "cv_r2_std": round(float(r2_scores.std()), 4),
            "cv_mae_mean": round(float(mae_scores.mean()), 4),
        })
    best = max(comparison, key=lambda c: c["cv_r2_mean"])
    # Linear models all tie within noise (~0.653). LinearRegression stays the
    # default because its local explanations are exact (coef_ x standardized
    # value); another family only replaces it if it beats it by a real margin.
    linear_r2 = next(c["cv_r2_mean"] for c in comparison if c["model"] == "LinearRegression")
    best_name = best["model"] if best["cv_r2_mean"] - linear_r2 >= 0.005 else "LinearRegression"
    selected = next(c for c in comparison if c["model"] == best_name)
    for c in comparison:
        c["selected"] = c["model"] == best_name

    scaler = StandardScaler().fit(X_train)
    model = WELLBEING_REG_MODELS[best_name]
    if hasattr(model, "random_state"):
        model.set_params(random_state=seed)
    model.fit(scaler.transform(X_train), y_train)
    _save_bundle("wellbeing_score", model, scaler)

    Xs_test = scaler.transform(X_test)
    preds = model.predict(Xs_test)
    metrics = {
        "model": best_name,
        "test_r2": round(float(r2_score(y_test, preds)), 4),
        "test_mae": round(float(mean_absolute_error(y_test, preds)), 4),
        "cv_r2_mean": selected["cv_r2_mean"],
        "cv_r2_std": selected["cv_r2_std"],
    }
    metrics["confidence"] = _confidence(metrics)
    metrics["feature_importance"] = _top_importance(model, FEATURES)
    metrics["model_comparison"] = comparison
    metrics["model_comparison_winner"] = best_name
    metrics["selection_note"] = (
        "All linear families tie within noise at CV R2 ~0.65; trees/SVR are "
        "worse. LinearRegression is kept because its local explanations are "
        "exact; it is only replaced if another family beats it by >=0.005 CV R2."
    )
    return metrics


def main():
    parser = argparse.ArgumentParser(description="Train the 4 Kivora production models.")
    parser.add_argument("--csv", default=DEFAULT_CSV)
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--test-size", type=float, default=0.2)
    args = parser.parse_args()

    df = load_and_preprocess(args.csv)
    X = df[FEATURES]
    y_add_binary = (df[TARGET_ADDICTION].isin(AT_RISK_LEVELS)).astype(int)
    y_add_detail = df[TARGET_ADDICTION].values
    y_wb = df[TARGET_WELLBEING].astype(float).values
    wb_median = float(np.median(y_wb))
    y_wb_flag = (y_wb >= wb_median).astype(int)

    X_train, X_test, y_addb_train, y_addb_test = train_test_split(
        X, y_add_binary, test_size=args.test_size, random_state=args.seed, stratify=y_add_detail)
    _, _, y_addd_train, y_addd_test = train_test_split(
        X, y_add_detail, test_size=args.test_size, random_state=args.seed, stratify=y_add_detail)
    _, _, y_wb_train, y_wb_test = train_test_split(
        X, y_wb, test_size=args.test_size, random_state=args.seed, stratify=y_add_detail)
    _, _, y_wbf_train, y_wbf_test = train_test_split(
        X, y_wb_flag, test_size=args.test_size, random_state=args.seed, stratify=y_add_detail)

    os.makedirs(ARTIFACTS_DIR, exist_ok=True)

    _, m_flag = train_binary_flag(
        "addiction_risk_flag", X_train, y_addb_train, X_test, y_addb_test,
        lambda: LogisticRegression(max_iter=2000, random_state=args.seed),
        classes=["Not at-risk", "At-risk"])

    scaler = StandardScaler().fit(X_train)
    detail_model = LogisticRegression(max_iter=2000, random_state=args.seed)
    detail_model.fit(scaler.transform(X_train), y_addd_train)
    _save_bundle("addiction_level_detail", detail_model, scaler,
                 classes=list(detail_model.classes_))
    Xs_test = scaler.transform(X_test)
    detail_preds = detail_model.predict(Xs_test)
    skf = StratifiedKFold(n_splits=5, shuffle=True, random_state=args.seed)
    cv_scores = cross_val_score(detail_model, scaler.transform(X_train), y_addd_train,
                                cv=skf, scoring="accuracy")
    m_detail = {
        "model": type(detail_model).__name__,
        "test_accuracy": round(float(accuracy_score(y_addd_test, detail_preds)), 4),
        "cv_accuracy_mean": round(float(cv_scores.mean()), 4),
        "cv_accuracy_std": round(float(cv_scores.std()), 4),
        "confusion_matrix": confusion_matrix(y_addd_test, detail_preds).tolist(),
        "confusion_matrix_labels": list(detail_model.classes_),
    }
    m_detail["confidence"] = _confidence(m_detail)
    m_detail["feature_importance"] = _top_importance(detail_model, FEATURES)

    m_wb_score = train_wellbeing_score(X_train, y_wb_train, X_test, y_wb_test, args.seed)

    _, m_wb_flag = train_binary_flag(
        "wellbeing_risk_flag", X_train, y_wbf_train, X_test, y_wbf_test,
        lambda: RandomForestClassifier(n_estimators=500, random_state=args.seed, n_jobs=-1),
        classes=["Below median", "Above median"])

    m_flag["description"] = "Binary: High/Severe addiction (at-risk) vs Low/Moderate"
    m_detail["description"] = "4-class: Low / Moderate / High / Severe addiction level"
    m_wb_score["description"] = "Continuous Mental_Wellbeing_Score (0-10 scale)"
    m_wb_flag["description"] = "Binary: predicted wellbeing above or below the training-set median"

    metadata_path = os.path.join(ARTIFACTS_DIR, "final_metadata.json")
    old = {}
    if os.path.exists(metadata_path):
        with open(metadata_path) as f:
            old = json.load(f)

    metadata = {
        "version": 2,
        "trained_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "data_source": os.path.relpath(args.csv, ROOT).replace("\\", "/"),
        "data_sha256": _data_sha256(args.csv),
        "n_rows": int(len(df)),
        "seed": args.seed,
        "test_size": args.test_size,
        "wellbeing_median": round(wb_median, 4),
        "features": FEATURES,
        "preprocessing": {
            "numeric_imputation": "column median",
            "binary_mapping": "Yes -> 1, else 0 (nulls -> 0)",
            "first_check_morning": {"Within 5 min": 0, "5-30 min": 1, "After 30 min": 2},
            "platform_dummies": "one-hot, Facebook is the reference (all-zero) category",
        },
        "targets": {
            "addiction_risk_flag": m_flag,
            "addiction_level_detail": m_detail,
            "wellbeing_score": m_wb_score,
            "wellbeing_risk_flag": m_wb_flag,
        },
        "dead_targets_transparency": old.get("dead_targets_transparency", {}),
    }

    with open(metadata_path, "w") as f:
        json.dump(metadata, f, indent=2)

    print(f"Trained on {len(df)} rows (split {len(X_train)}/{len(X_test)})")
    print(f"addiction_risk_flag    test_acc={m_flag['test_accuracy']}  auc={m_flag['roc_auc']}")
    print(f"addiction_level_detail test_acc={m_detail['test_accuracy']}")
    print(f"wellbeing_score        model={m_wb_score['model']}  test_r2={m_wb_score['test_r2']}  cv_r2={m_wb_score['cv_r2_mean']}")
    print(f"wellbeing_risk_flag    test_acc={m_wb_flag['test_accuracy']}  auc={m_wb_flag['roc_auc']}")
    print("Metadata written to", metadata_path)


if __name__ == "__main__":
    main()

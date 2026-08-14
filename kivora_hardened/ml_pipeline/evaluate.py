"""
Re-runs the full evaluation against the SAVED artifacts in ml/artifacts/ --
not a retraining. Reproduces the exact train/test split recorded in
final_metadata.json (same seed, test_size and CSV), reloads each bundle the
same way ml/predictor.py does, recomputes every metric, and prints a
PASS/FAIL comparison against the numbers stored in the metadata.

Usage (from repo root):
    python -m ml_pipeline.evaluate [--csv <path>]

Exit code is non-zero if any stored metric drifts by more than 0.005.
"""
import argparse
import json
import os

import joblib
import numpy as np
from sklearn.metrics import (accuracy_score, confusion_matrix, mean_absolute_error,
                             r2_score, roc_auc_score)
from sklearn.model_selection import train_test_split

from ml_pipeline.final_train import (ARTIFACTS_DIR, AT_RISK_LEVELS, DEFAULT_CSV, FEATURES,
                                     TARGET_ADDICTION, TARGET_WELLBEING, load_and_preprocess)

TOL = 0.005


def load_metadata() -> dict:
    with open(os.path.join(ARTIFACTS_DIR, "final_metadata.json")) as f:
        return json.load(f)


def check(name, stored, recomputed, extra=""):
    ok = abs(stored - recomputed) <= TOL
    print(f"[{'PASS' if ok else 'FAIL'}] {name:32s} stored={stored:.4f} recomputed={recomputed:.4f} {extra}")
    return ok


def main():
    parser = argparse.ArgumentParser(description="Verify saved artifacts reproduce the recorded metrics.")
    parser.add_argument("--csv", default=DEFAULT_CSV)
    args = parser.parse_args()

    meta = load_metadata()
    seed = int(meta["seed"])
    test_size = float(meta["test_size"])

    df = load_and_preprocess(args.csv)
    X = df[FEATURES]
    y_add_binary = (df[TARGET_ADDICTION].isin(AT_RISK_LEVELS)).astype(int)
    y_add_detail = df[TARGET_ADDICTION].values
    y_wb = df[TARGET_WELLBEING].astype(float).values
    y_wb_flag = (y_wb >= float(meta["wellbeing_median"])).astype(int)

    X_train, X_test, y_addb_train, y_addb_test = train_test_split(
        X, y_add_binary, test_size=test_size, random_state=seed, stratify=y_add_detail)
    _, _, y_addd_train, y_addd_test = train_test_split(
        X, y_add_detail, test_size=test_size, random_state=seed, stratify=y_add_detail)
    _, _, y_wb_train, y_wb_test = train_test_split(
        X, y_wb, test_size=test_size, random_state=seed, stratify=y_add_detail)
    _, _, y_wbf_train, y_wbf_test = train_test_split(
        X, y_wb_flag, test_size=test_size, random_state=seed, stratify=y_add_detail)

    ok = True

    flag = joblib.load(os.path.join(ARTIFACTS_DIR, "addiction_risk_flag.joblib"))
    Xs = flag["scaler"].transform(X_test[flag["features"]])
    preds = flag["model"].predict(Xs)
    proba = flag["model"].predict_proba(Xs)[:, 1]
    ok &= check("addiction_risk_flag accuracy", meta["targets"]["addiction_risk_flag"]["test_accuracy"],
                accuracy_score(y_addb_test, preds))
    ok &= check("addiction_risk_flag auc", meta["targets"]["addiction_risk_flag"]["roc_auc"],
                roc_auc_score(y_addb_test, proba))

    detail = joblib.load(os.path.join(ARTIFACTS_DIR, "addiction_level_detail.joblib"))
    Xs = detail["scaler"].transform(X_test[detail["features"]])
    preds = detail["model"].predict(Xs)
    ok &= check("addiction_level_detail accuracy", meta["targets"]["addiction_level_detail"]["test_accuracy"],
                accuracy_score(y_addd_test, preds))

    wb = joblib.load(os.path.join(ARTIFACTS_DIR, "wellbeing_score.joblib"))
    Xs = wb["scaler"].transform(X_test[wb["features"]])
    preds = wb["model"].predict(Xs)
    ok &= check("wellbeing_score r2", meta["targets"]["wellbeing_score"]["test_r2"],
                r2_score(y_wb_test, preds))
    ok &= check("wellbeing_score mae", meta["targets"]["wellbeing_score"]["test_mae"],
                mean_absolute_error(y_wb_test, preds))

    wbf = joblib.load(os.path.join(ARTIFACTS_DIR, "wellbeing_risk_flag.joblib"))
    Xs = wbf["scaler"].transform(X_test[wbf["features"]])
    preds = wbf["model"].predict(Xs)
    proba = wbf["model"].predict_proba(Xs)[:, 1]
    ok &= check("wellbeing_risk_flag accuracy", meta["targets"]["wellbeing_risk_flag"]["test_accuracy"],
                accuracy_score(y_wbf_test, preds))
    ok &= check("wellbeing_risk_flag auc", meta["targets"]["wellbeing_risk_flag"]["roc_auc"],
                roc_auc_score(y_wbf_test, proba))

    print()
    print("ALL CHECKS PASS" if ok else "SOME CHECKS FAILED")
    raise SystemExit(0 if ok else 1)


if __name__ == "__main__":
    main()

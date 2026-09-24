import json
import os
import subprocess
import sys
from pathlib import Path

from src.validate_metrics import find_quality_failures


REPOSITORY_ROOT = Path(__file__).resolve().parents[1]


def test_training_cli_writes_expected_outputs(tmp_path: Path) -> None:
    metrics_directory = tmp_path / "metrics"
    environment = os.environ.copy()
    environment["MLFLOW_TRACKING_URI"] = (tmp_path / "mlruns").as_uri()
    environment["MPLBACKEND"] = "Agg"

    subprocess.run(
        [
            sys.executable,
            str(REPOSITORY_ROOT / "src" / "train-model-parameters.py"),
            "--training_data",
            str(REPOSITORY_ROOT / "data" / "test-data" / "diabetes-test.csv"),
            "--reg_rate",
            "0.01",
            "--metrics_output",
            str(metrics_directory),
        ],
        cwd=tmp_path,
        env=environment,
        check=True,
        capture_output=True,
        text=True,
    )

    metrics = json.loads((metrics_directory / "metrics.json").read_text())
    assert set(metrics) == {"accuracy", "auc"}
    assert all(0.0 <= value <= 1.0 for value in metrics.values())
    assert (tmp_path / "ROC-Curve.png").is_file()


def test_quality_gate_accepts_metrics_above_thresholds() -> None:
    failures = find_quality_failures(
        {"accuracy": 0.774, "auc": 0.8484},
        {"accuracy": 0.75, "auc": 0.80},
    )

    assert failures == []


def test_quality_gate_rejects_metrics_below_thresholds() -> None:
    failures = find_quality_failures(
        {"accuracy": 0.70, "auc": 0.79},
        {"accuracy": 0.75, "auc": 0.80},
    )

    assert failures == [
        "accuracy=0.7000 is below the minimum 0.7500",
        "auc=0.7900 is below the minimum 0.8000",
    ]

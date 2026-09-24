import argparse
import json
import sys
from pathlib import Path
from typing import Mapping


def find_quality_failures(
    metrics: Mapping[str, object],
    minimums: Mapping[str, float],
) -> list[str]:
    """Return an explanation for every missing, invalid, or insufficient metric."""
    failures = []

    for name, minimum in minimums.items():
        value = metrics.get(name)
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            failures.append(f"{name} is missing or is not numeric")
        elif value < minimum:
            failures.append(f"{name}={value:.4f} is below the minimum {minimum:.4f}")

    return failures


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Fail when model evaluation metrics do not meet acceptance criteria."
    )
    parser.add_argument("--metrics-file", type=Path, required=True)
    parser.add_argument("--min-accuracy", type=float, required=True)
    parser.add_argument("--min-auc", type=float, required=True)
    return parser.parse_args()


def main() -> int:
    args = parse_args()

    try:
        metrics = json.loads(args.metrics_file.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        print(f"Unable to read metrics from {args.metrics_file}: {error}", file=sys.stderr)
        return 1

    if not isinstance(metrics, dict):
        print(f"Metrics file must contain a JSON object: {args.metrics_file}", file=sys.stderr)
        return 1

    minimums = {
        "accuracy": args.min_accuracy,
        "auc": args.min_auc,
    }
    failures = find_quality_failures(metrics, minimums)

    print("Model quality criteria:")
    for name, minimum in minimums.items():
        print(f"- {name}: {metrics.get(name)!r} (minimum {minimum:.4f})")

    if failures:
        print("Model quality gate failed:", file=sys.stderr)
        for failure in failures:
            print(f"- {failure}", file=sys.stderr)
        return 1

    print("Model quality gate passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

"""
PeerDAS detection probability when sampling random columns.

Run:
    python -m src.benchmarking.benchmarks.peerdas.detection
"""

from __future__ import annotations

import random
from pathlib import Path

from src.benchmarking.peerdas.params import N
from src.benchmarking.utils.csv_logger import CSVLogger


def _results_path(name: str) -> str:
    """Centralize benchmark output location."""
    return str(Path("benchmarking") / "results" / name)


def benchmark_column_detection(
    withholding_ratio_list: list[float],
    samples: int,
    trials: int = 500,
) -> None:
    """
    Monte-Carlo estimate of detection probability under column withholding.

    A trial is counted as "detected" if at least one sampled column index falls
    inside the withheld set.
    """
    logger = CSVLogger(
        _results_path("peerdas_column_detection.csv"),
        fieldnames=[
            "phase",
            "n_columns",
            "withholding_ratio",
            "samples",
            "detection_probability",
        ],
    )

    for w in withholding_ratio_list:
        # Convert ratio into an integer number of withheld columns.
        withheld_size = int(round(w * N))
        withheld_size = min(max(withheld_size, 0), N)
        withheld = (
            set(random.sample(range(N), withheld_size)) if withheld_size else set()
        )

        failures = 0
        for _ in range(trials):
            # Clamp sample size to N to avoid invalid random.sample() calls.
            indices = random.sample(range(N), min(samples, N))
            detected = any(idx in withheld for idx in indices)
            if not detected:
                failures += 1

        # detection_probability = 1 - miss_probability
        logger.log(
            {
                "phase": "column_detection",
                "n_columns": N,
                "withholding_ratio": w,
                "samples": samples,
                "detection_probability": 1 - failures / trials,
            }
        )

    logger.close()


if __name__ == "__main__":
    benchmark_column_detection(
        withholding_ratio_list=[0.1, 0.2, 0.3, 0.4, 0.5],
        samples=16,
    )


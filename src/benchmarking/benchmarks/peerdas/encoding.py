"""
PeerDAS RS encoding benchmarks (RSrow / RSfull).

Run:
    python -m src.benchmarking.benchmarks.peerdas.encoding
"""

from __future__ import annotations

from pathlib import Path

import numpy as np

from src.benchmarking.peerdas.params import FIELD_PRIME, KD, ND
from src.benchmarking.peerdas.rs_row import (
    build_full_matrix_rowwise,
    extend_blob_coefficients,
)
from src.benchmarking.utils.csv_logger import CSVLogger
from src.benchmarking.utils.timer import timer


def _results_path(name: str) -> str:
    """Centralize benchmark output location."""
    return str(Path("benchmarking") / "results" / name)


def benchmark_peerdas_encoding(
    ell_list: list[int],
    repetitions: int = 10,
) -> None:
    """
    Benchmark two encoding stages:
    - single row extension (KD -> ND)
    - full RSfull matrix construction for given `ell`

    Parameters
    ----------
    ell_list:
        Different row counts to profile scaling behavior.
    repetitions:
        Independent repeats per configuration for stable averages.
    """
    logger = CSVLogger(
        _results_path("peerdas_encoding.csv"),
        fieldnames=[
            "phase",
            "ell",
            "nd",
            "kd",
            "avg_extend_blob_ms",
            "avg_full_matrix_ms",
        ],
    )

    # Fixed seed keeps runs reproducible across machines/sessions.
    rng = np.random.default_rng(0)

    for ell in ell_list:
        times_extend: list[float] = []
        times_matrix: list[float] = []

        for _ in range(repetitions):
            # Generate one blob worth of coefficients for RSrow extension.
            coeffs = rng.integers(0, FIELD_PRIME, size=KD, dtype=np.int64)
            with timer() as t:
                extend_blob_coefficients(coeffs)
            times_extend.append(t())

            # Generate `ell` blobs and measure end-to-end matrix build.
            rows = [
                rng.integers(0, FIELD_PRIME, size=KD, dtype=np.int64)
                for _ in range(ell)
            ]
            with timer() as t:
                build_full_matrix_rowwise(rows)
            times_matrix.append(t())

        # Persist averaged milliseconds for easier CSV post-processing.
        logger.log(
            {
                "phase": "encoding",
                "ell": ell,
                "nd": ND,
                "kd": KD,
                "avg_extend_blob_ms": (sum(times_extend) / len(times_extend)) * 1000,
                "avg_full_matrix_ms": (sum(times_matrix) / len(times_matrix)) * 1000,
            }
        )

    logger.close()


if __name__ == "__main__":
    benchmark_peerdas_encoding(ell_list=[1, 2, 4, 8, 16], repetitions=5)


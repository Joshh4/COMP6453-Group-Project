"""
PeerDAS column sampling benchmark: gather column symbols from a RSfull matrix.

Run:
    python -m src.benchmarking.benchmarks.peerdas.sampling
"""

from __future__ import annotations

import random
from pathlib import Path

import numpy as np

from src.benchmarking.peerdas.params import FIELD_PRIME, KD, N
from src.benchmarking.peerdas.rs_row import build_full_matrix_rowwise, gather_column_cells
from src.benchmarking.utils.csv_logger import CSVLogger
from src.benchmarking.utils.timer import timer


def _results_path(name: str) -> str:
    """Centralize benchmark output location."""
    return str(Path("benchmarking") / "results" / name)


def benchmark_column_sampling(
    ell: int,
    num_samples_list: list[int],
    repetitions: int = 30,
) -> None:
    """
    Measure column-symbol extraction cost from an already encoded RSfull matrix.

    This isolates client-side sampling assembly work (data slicing/layout),
    not proof verification cost.
    """
    logger = CSVLogger(
        _results_path("peerdas_column_sampling.csv"),
        fieldnames=["phase", "ell", "n_columns", "samples", "avg_gather_ms"],
    )

    # Build matrix once; this benchmark focuses on sampling, not encoding.
    rng = np.random.default_rng(1)
    rows = [
        rng.integers(0, FIELD_PRIME, size=KD, dtype=np.int64)
        for _ in range(ell)
    ]
    matrix = build_full_matrix_rowwise(rows)

    for k in num_samples_list:
        times: list[float] = []
        for _ in range(repetitions):
            # Simulate one client querying k random columns.
            indices = random.sample(range(N), k)
            with timer() as t:
                for j in indices:
                    # Each gather returns shape (ell, D), i.e. one column symbol.
                    _ = gather_column_cells(matrix, j)
            times.append(t())

        # Store average gather latency in milliseconds.
        logger.log(
            {
                "phase": "column_gather",
                "ell": ell,
                "n_columns": N,
                "samples": k,
                "avg_gather_ms": (sum(times) / len(times)) * 1000,
            }
        )

    logger.close()


if __name__ == "__main__":
    benchmark_column_sampling(ell=8, num_samples_list=[1, 2, 4, 8, 16, 32])


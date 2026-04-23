"""
Symbolic pairing counts: naive per-opening vs batched (cost model only).

Run:
    python -m src.benchmarking.benchmarks.peerdas.pairing_counts
"""

from __future__ import annotations

from src.benchmarking.utils.csv_logger import CSVLogger
from src.benchmarking.utils.paths import benchmark_csv


def naive_pairing_count(num_openings: int, num_rows: int) -> int:
    """Two pairings per (opening, row) under independent verification."""
    return 2 * num_openings * num_rows


def batched_pairing_count() -> int:
    """Batched verification: two pairings total for the batch."""
    return 2


def benchmark_pairing_counts(ell: int, l_values: list[int]) -> None:
    """Write naive vs batched pairing counts for each ``L``.

    Here, ``L`` is the number of sampled columns/openings.
    """
    logger = CSVLogger(
        benchmark_csv("peerdas_pairing_counts.csv"),
        fieldnames=["ell", "L", "naive_pairings", "batched_pairings"],
    )

    for L in l_values:
        logger.log(
            {
                "ell": ell,
                "L": L,
                "naive_pairings": naive_pairing_count(L, ell),
                "batched_pairings": batched_pairing_count(),
            }
        )

    logger.close()


if __name__ == "__main__":
    benchmark_pairing_counts(ell=8, l_values=[1, 2, 4, 8, 16, 32, 64])

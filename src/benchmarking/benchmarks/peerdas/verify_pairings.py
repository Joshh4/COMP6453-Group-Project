"""
PeerDAS verification cost: naive vs batched pairing counts (Section 4.2).

Run:
    python -m src.benchmarking.benchmarks.peerdas.verify_pairings
"""

from __future__ import annotations

from pathlib import Path

from src.benchmarking.peerdas.verify_cost import (
    batched_pairing_count,
    naive_pairing_count,
)
from src.benchmarking.utils.csv_logger import CSVLogger


def _results_path(name: str) -> str:
    """Centralize benchmark output location."""
    return str(Path("benchmarking") / "results" / name)


def benchmark_verify_pairing_counts(ell: int, l_values: list[int]) -> None:
    """
    Record symbolic pairing counts for naive and batched verification.

    This is a cost-model benchmark (counts only), not an ECC runtime benchmark.
    """
    logger = CSVLogger(
        _results_path("peerdas_verify_pairings.csv"),
        fieldnames=["ell", "L", "naive_pairings", "batched_pairings"],
    )

    for L in l_values:
        # L = number of queried cells (columns) for this scenario.
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
    benchmark_verify_pairing_counts(ell=8, l_values=[1, 2, 4, 8, 16, 32, 64])


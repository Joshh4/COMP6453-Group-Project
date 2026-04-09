"""
Merkle-DAS proof generation benchmark (legacy/basic scheme).

Run:
    python -m src.benchmarking.benchmarks.merkle_das.proof_gen
"""

from __future__ import annotations

import random
from pathlib import Path

from src.benchmarking.utils.csv_logger import CSVLogger
from src.benchmarking.utils.timer import timer
from src.commitments.merkle_tree import MerkleTree


def _results_path(name: str) -> str:
    """Centralize benchmark output location."""
    return str(Path("benchmarking") / "results" / name)


def benchmark_proof_generation(
    merkle: MerkleTree,
    chunks: list[bytes],
    num_samples_list: list[int],
    repetitions: int = 20,
) -> None:
    """
    Measure Merkle proof generation latency for random sample sets.

    This benchmark captures cost of `get_proof()` only; verification is measured
    in a separate benchmark.
    """
    logger = CSVLogger(
        _results_path("basic_das_week6.csv"),
        fieldnames=["phase", "num_chunks", "samples", "avg_proof_gen_ms"],
    )

    num_chunks = len(chunks)

    for k in num_samples_list:
        times: list[float] = []
        for _ in range(repetitions):
            # Randomly choose k leaves to request authentication paths for.
            indices = random.sample(range(num_chunks), k)
            with timer() as t:
                for idx in indices:
                    merkle.get_proof(idx)
            times.append(t())

        # Store mean proof generation time in milliseconds.
        logger.log(
            {
                "phase": "proof_generation",
                "num_chunks": num_chunks,
                "samples": k,
                "avg_proof_gen_ms": (sum(times) / len(times)) * 1000,
            }
        )

    logger.close()


if __name__ == "__main__":
    chunks = [f"chunk_{i}".encode() for i in range(1024)]
    tree = MerkleTree(chunks)
    benchmark_proof_generation(tree, chunks, num_samples_list=[1, 2, 4, 8, 16, 32])


"""
Merkle-DAS detection probability benchmark (legacy/basic scheme).

Run:
    python -m src.benchmarking.benchmarks.merkle_das.detection_probability
"""

from __future__ import annotations

import random
from pathlib import Path

from src.benchmarking.utils.csv_logger import CSVLogger
from src.commitments.merkle_tree import MerkleTree


def _results_path(name: str) -> str:
    """Centralize benchmark output location."""
    return str(Path("benchmarking") / "results" / name)


def benchmark_detection_probability(
    merkle: MerkleTree,
    chunks: list[bytes],
    withholding_ratio_list: list[float],
    samples: int,
    trials: int = 200,
) -> None:
    """
    Monte-Carlo estimate of withholding detection under random DAS sampling.

    For each withholding ratio `w`, a fixed withheld set is sampled once, then
    many random client queries are simulated to estimate detection probability.
    """
    logger = CSVLogger(
        _results_path("basic_das_week6.csv"),
        fieldnames=[
            "phase",
            "num_chunks",
            "withholding_ratio",
            "samples",
            "detection_probability",
        ],
    )

    num_chunks = len(chunks)

    for w in withholding_ratio_list:
        failures = 0
        # Model unavailable chunks chosen by adversary/network fault.
        withheld = set(random.sample(range(num_chunks), int(w * num_chunks)))

        for _ in range(trials):
            # Client samples `samples` random positions.
            indices = random.sample(range(num_chunks), samples)
            detected = any(idx in withheld for idx in indices)
            if not detected:
                failures += 1

        # detection_probability = 1 - probability(no sampled index withheld)
        logger.log(
            {
                "phase": "detection_probability",
                "num_chunks": num_chunks,
                "withholding_ratio": w,
                "samples": samples,
                "detection_probability": 1 - failures / trials,
            }
        )

    logger.close()


if __name__ == "__main__":
    chunks = [f"chunk_{i}".encode() for i in range(1024)]
    tree = MerkleTree(chunks)
    benchmark_detection_probability(
        tree,
        chunks,
        withholding_ratio_list=[0.1, 0.2, 0.3, 0.4, 0.5],
        samples=16,
    )


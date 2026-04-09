"""
Merkle-DAS verification benchmark (legacy/basic scheme).

Run:
    python -m src.benchmarking.benchmarks.merkle_das.verify
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


def benchmark_verification(
    merkle: MerkleTree,
    chunks: list[bytes],
    num_samples_list: list[int],
    repetitions: int = 20,
) -> None:
    """
    Measure Merkle proof verification latency over random sampled indices.

    Parameters
    ----------
    merkle:
        Pre-built Merkle tree used as proof source and root provider.
    chunks:
        Original leaf payloads matching `merkle`.
    num_samples_list:
        Different sample counts k to profile scaling.
    repetitions:
        Independent repeated runs per k to smooth variance.
    """
    logger = CSVLogger(
        _results_path("basic_das_week6.csv"),
        fieldnames=["phase", "num_chunks", "samples", "avg_verify_ms"],
    )

    # Root is constant for this benchmark run.
    root = merkle.get_root()
    num_chunks = len(chunks)

    for k in num_samples_list:
        times: list[float] = []
        for _ in range(repetitions):
            # Simulate a client randomly sampling k chunks and requesting proofs.
            indices = random.sample(range(num_chunks), k)
            proofs = [(i, chunks[i], merkle.get_proof(i)) for i in indices]

            with timer() as t:
                for i, chunk, proof in proofs:
                    # Assert keeps benchmark honest: invalid paths fail loudly.
                    assert MerkleTree.verify_proof(chunk, proof, root)
            times.append(t())

        # Store mean verification time in milliseconds.
        logger.log(
            {
                "phase": "verification",
                "num_chunks": num_chunks,
                "samples": k,
                "avg_verify_ms": (sum(times) / len(times)) * 1000,
            }
        )

    logger.close()


if __name__ == "__main__":
    chunks = [f"chunk_{i}".encode() for i in range(1024)]
    tree = MerkleTree(chunks)
    benchmark_verification(tree, chunks, num_samples_list=[1, 2, 4, 8, 16, 32])


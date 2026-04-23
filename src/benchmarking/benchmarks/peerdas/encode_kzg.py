"""
PeerDAS encode benchmark: RS matrix + KZG commit + column proofs.

Uses ``src.nodes.peerdas_network._encode_matrix``.

Run:
    python -m src.benchmarking.benchmarks.peerdas.encode_kzg
"""

from __future__ import annotations

from src.benchmarking.utils.csv_logger import CSVLogger
from src.benchmarking.utils.paths import benchmark_csv
from src.benchmarking.utils.random_block import generate_deterministic_block
from src.benchmarking.utils.timer import timer
from src.nodes import peerdas_network as pd


def benchmark_encode_kzg(
    configs: list[tuple[int, int]],
    repetitions: int = 5,
    block_bytes: int = 4096,
) -> None:
    """
    Time ``_encode_matrix`` after a one-call warmup per (n_blobs, n_cols).

    Warmup covers KZG SRS setup in ``_get_kzg_ctx`` so averages
    reflect steady-state encode cost for fixed geometry.
    """
    logger = CSVLogger(
        benchmark_csv("peerdas_encode_kzg.csv"),
        fieldnames=[
            "phase",
            "n_blobs",
            "n_cols",
            "block_bytes",
            "rs_available",
            "repetitions",
            "avg_encode_ms",
        ],
    )

    payload = generate_deterministic_block(block_bytes, seed=0x50444552)

    for n_blobs, n_cols in configs:
        _ = pd._encode_matrix(payload, n_blobs, n_cols)

        times: list[float] = []
        for _ in range(repetitions):
            with timer() as t:
                pd._encode_matrix(payload, n_blobs, n_cols)
            times.append(t())

        logger.log(
            {
                "phase": "encode_kzg",
                "n_blobs": n_blobs,
                "n_cols": n_cols,
                "block_bytes": block_bytes,
                "rs_available": int(bool(pd._RS_AVAILABLE)),
                "repetitions": repetitions,
                "avg_encode_ms": (sum(times) / len(times)) * 1000,
            }
        )

    logger.close()


if __name__ == "__main__":
    benchmark_encode_kzg(
        configs=[
            (2, 8),
            (4, 8),
            (4, 16),
        ],
        repetitions=3,
        block_bytes=2048,
    )

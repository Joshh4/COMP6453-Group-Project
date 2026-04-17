"""
PeerDAS KZG column verification benchmark on ``_encode_matrix`` outputs.

Uses ``peerdas_network._encode_matrix``, ``_get_kzg_ctx``, and ``KZGContext.verify_column``.

Run:
    python -m src.benchmarking.benchmarks.peerdas.verify_kzg
"""

from __future__ import annotations

import random

from src.benchmarking.utils.csv_logger import CSVLogger
from src.benchmarking.utils.paths import benchmark_csv
from src.benchmarking.utils.random_block import generate_deterministic_block
from src.benchmarking.utils.timer import timer
from src.nodes import peerdas_network as pd


def benchmark_verify_kzg(
    n_blobs: int,
    n_cols: int,
    columns_per_round: list[int],
    rounds: int = 30,
    block_bytes: int = 4096,
) -> None:
    """
    For each ``L`` in ``columns_per_round``, average time per round to verify ``L``
    random columns (one ``verify_column`` per column).
    """
    logger = CSVLogger(
        benchmark_csv("peerdas_verify_kzg.csv"),
        fieldnames=[
            "phase",
            "n_blobs",
            "n_cols",
            "columns_verified",
            "rounds",
            "block_bytes",
            "rs_available",
            "avg_ms_per_round",
            "avg_ms_per_verify",
        ],
    )

    payload = generate_deterministic_block(block_bytes, seed=0x56455249)

    matrix, commitments, col_proofs = pd._encode_matrix(
        payload, n_blobs, n_cols
    )
    kzg_ctx = pd._get_kzg_ctx(n_blobs, n_cols)

    rng = random.Random(0)

    for L in columns_per_round:
        L_eff = min(L, n_cols)
        times: list[float] = []
        for _ in range(rounds):
            cols = rng.sample(range(n_cols), L_eff)
            with timer() as t:
                for c in cols:
                    cells = [matrix[b][c] for b in range(n_blobs)]
                    kzg_ctx.verify_column(
                        commitments,
                        c,
                        cells,
                        col_proofs[c],
                    )
            times.append(t())

        total_ms = sum(times) * 1000
        denom_verify = rounds * L_eff
        logger.log(
            {
                "phase": "verify_kzg",
                "n_blobs": n_blobs,
                "n_cols": n_cols,
                "columns_verified": L_eff,
                "rounds": rounds,
                "block_bytes": block_bytes,
                "rs_available": int(bool(pd._RS_AVAILABLE)),
                "avg_ms_per_round": (total_ms / rounds),
                "avg_ms_per_verify": (total_ms / denom_verify),
            }
        )

    logger.close()


if __name__ == "__main__":
    benchmark_verify_kzg(
        n_blobs=4,
        n_cols=16,
        columns_per_round=[1, 2, 4, 8],
        rounds=12,
        block_bytes=2048,
    )

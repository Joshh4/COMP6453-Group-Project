"""
PeerDAS KZG column verification benchmark on ``_encode_matrix`` outputs.

Uses ``peerdas_network._encode_matrix``, ``_get_kzg_ctx``,
and ``KZGContext.verify_column``.

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
    For each ``L`` in ``columns_per_round``, average time per round
    to verify ``L`` random columns (one ``verify_column`` per column).
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


def benchmark_verify_kzg_geometries(
    configs: list[tuple[int, int]],
    columns_per_round: list[int],
    rounds: int = 5,
    block_bytes: int = 2048,
) -> None:
    """
    Compare verifier speed for several ``(n_blobs, n_cols)`` pairs in one CSV.

    For each geometry, encodes once, then for each ``L`` in
    ``columns_per_round`` measures ``rounds`` rounds of naive per-column
    verification (same as ``benchmark_verify_kzg``). Use ``L=1`` and compare
    ``avg_ms_per_verify`` to see how **blob count** scales (about
    ``2 * n_blobs`` pairings per column); vary ``n_cols`` at fixed ``n_blobs``
    to see domain / matrix-width effects.

    Uses one ``CSVLogger`` for the whole sweep, so the output file is not
    truncated between geometries (calling ``benchmark_verify_kzg`` in a loop
    would overwrite the default CSV on every iteration because each call
    opens the file in write mode).
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

    for n_blobs, n_cols in configs:
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
    # Default: sweep several (n_blobs, n_cols) pairs in one CSV. L values are
    # capped at n_cols; we use L <= 4 so the (2, 4) row is not duplicated for
    # L=4 vs L=8 (both would verify four columns). For a single geometry or
    # larger L (e.g. 8 on wide matrices), call benchmark_verify_kzg instead.
    benchmark_verify_kzg_geometries(
        configs=[(2, 4), (2, 8), (4, 8), (4, 16)],
        columns_per_round=[1, 2, 4],
        rounds=8,
        block_bytes=2048,
    )

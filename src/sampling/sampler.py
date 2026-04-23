"""
PeerDAS - Sampler
=================
Handles all sampling decisions for a PeerDAS light client.

How PeerDAS sampling works
--------------------------
A verifier does NOT download the entire block.  Instead it:
  1. Randomly selects a subset of column indices to sample.
  2. For each selected column, picks any DA node from that
     column's subnet (committee).
  3. Asks that node for the column data + KZG multiproof.
  4. Verifies the KZG multiproof against the blob commitments.
  5. If enough columns verify (threshold), declares available.

The threshold is not always 100% -- a verifier only needs enough
samples to be statistically convinced.  In Ethereum's spec the
sample count is chosen so the soundness error is <= 2^-lambda.

Why sample columns rather than individual cells?
------------------------------------------------
Each column has a single KZG multiproof covering all blobs at
that column position.  Sampling a whole column costs one proof
verification regardless of how many blobs there are.  Individual
cell sampling is the Danksharding end-state; PeerDAS uses columns.
"""

import asyncio
import logging
import random
from dataclasses import dataclass

from src.nodes.peerdas_network import (
    MSG_SAMPLE_RESP,
    SubnetRegistry,
    Verifier,
)

# =============================================================================
# Result types
# =============================================================================


@dataclass
class ColumnResult:
    """Result of sampling one column from one node."""

    col_index: int
    node_queried: str  # node_id of the node we asked
    responded: bool  # did we get any response at all?
    verified: bool  # did the KZG proof check out?
    error: str = ""  # human-readable reason if not verified


@dataclass
class SampleResult:
    """Aggregated result of one full sampling round."""

    block_id: str
    columns_tried: list  # list[int] -- which columns we sampled
    results: list  # list[ColumnResult]
    available: bool  # overall verdict
    verified_count: int
    failed_count: int
    no_response: int

    def summary(self) -> str:
        """One-line human-readable summary of the sampling round."""
        status = "AVAILABLE" if self.available else "UNAVAILABLE"
        total = len(self.columns_tried)
        return (
            f"Block {self.block_id}: {status} "
            f"({self.verified_count}/{total} cols OK, "
            f"{self.no_response} no response, "
            f"{self.failed_count} bad proof)"
        )


# =============================================================================
# Sampler
# =============================================================================


class Sampler:
    """
    Drives the PeerDAS sampling protocol for a single verifier.

    Parameters
    ----------
    verifier : Verifier
        The network layer object used to send/receive messages.
    registry : SubnetRegistry
        Maps column indices to DA nodes that custody them.
    kzg_ctx : object
        KZG context used to verify column proofs.  Must expose a
        verify_column(commitments, col_idx, cells, proof) method.
    n_cols : int
        Total number of columns in the blob matrix.
    sample_count : int
        How many columns to sample per block.  0 = sample all.
        In Ethereum's spec this is chosen so that the probability
        of missing an unavailable block is at most 2^-lambda.
        A safe default is ~75 of 128 for lambda=100.
    threshold : float
        Fraction of sampled columns that must verify for the block
        to be declared available.  1.0 = all must verify (strict
        light-client behaviour).  Relax to e.g. 0.75 for a more
        lenient probabilistic check.
    """

    def __init__(
        self,
        verifier: Verifier,
        registry: SubnetRegistry,
        kzg_ctx: object,
        n_cols: int,
        sample_count: int = 0,
        threshold: float = 1.0,
    ):
        self.verifier = verifier
        self.registry = registry
        self.kzg_ctx = kzg_ctx
        self.n_cols = n_cols
        self.sample_count = sample_count if sample_count > 0 else n_cols
        self.threshold = threshold
        self.logger = logging.getLogger(f"Sampler({verifier.info.node_id})")

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    async def sample(self, block_id: str) -> SampleResult:
        """
        Sample self.sample_count random columns of block_id.
        Returns a SampleResult with per-column breakdown and verdict.
        """
        cols = random.sample(
            range(self.n_cols),
            min(self.sample_count, self.n_cols),
        )
        self.logger.info(
            f"Sampling block {block_id}: {len(cols)}/{self.n_cols} columns"
        )
        return await self._run_sample(block_id, cols)

    async def sample_specific(
        self,
        block_id: str,
        col_indices: list,
    ) -> SampleResult:
        """
        Sample a specific set of columns rather than a random subset.
        Useful for reconstruction: ask for exactly the columns you
        need to fill in gaps.
        """
        return await self._run_sample(block_id, col_indices)

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    async def _run_sample(self, block_id: str, cols: list) -> SampleResult:
        """Fire all column requests concurrently and tally results."""
        tasks = [self._sample_one_column(block_id, c) for c in cols]
        results: list[ColumnResult] = await asyncio.gather(*tasks)

        verified = sum(1 for r in results if r.verified)
        failed = sum(1 for r in results if r.responded and not r.verified)
        no_resp = sum(1 for r in results if not r.responded)
        required = int(len(cols) * self.threshold)
        available = verified >= required

        sr = SampleResult(
            block_id=block_id,
            columns_tried=cols,
            results=results,
            available=available,
            verified_count=verified,
            failed_count=failed,
            no_response=no_resp,
        )
        self.logger.info(sr.summary())
        return sr

    async def _sample_one_column(
        self,
        block_id: str,
        col_idx: int,
    ) -> ColumnResult:
        """
        Ask one node for column col_idx and verify the KZG proof.

        Node selection: any node in the subnet can serve the column,
        so we pick one at random.  One attempt only -- Ethereum's
        gossip layer handles retries in the real protocol.
        """
        subnet = self.registry.nodes_for_column(col_idx)

        if not subnet:
            return ColumnResult(
                col_index=col_idx,
                node_queried="none",
                responded=False,
                verified=False,
                error=f"No nodes custody column {col_idx}",
            )

        node = random.choice(subnet)
        resp = await self.verifier.fetch_column(node, block_id, col_idx)

        if resp is None or resp.get("type") != MSG_SAMPLE_RESP:
            return ColumnResult(
                col_index=col_idx,
                node_queried=node.node_id,
                responded=False,
                verified=False,
                error="No response or unavailable",
            )

        valid = self.kzg_ctx.verify_column(
            resp["commitments"],
            resp["col_index"],
            resp["cells"],
            resp["proof"],
        )

        return ColumnResult(
            col_index=col_idx,
            node_queried=node.node_id,
            responded=True,
            verified=valid,
            error=("" if valid else "KZG multiproof verification failed"),
        )

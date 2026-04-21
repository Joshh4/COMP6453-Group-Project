"""
Tests: PeerDAS sampler
-----------------------
The sampler tests mock Verifier.fetch_column() so they run without
any real TCP connections.  This keeps the tests fast and keeps the
sampler's decision logic isolated from the network layer.

  TestSamplerAllColumnsVerify
      When every node responds with a valid column, the result must
      be available=True and verified_count == number sampled.

  TestSamplerNoNodesRespond
      When every node is silent (returns None), the result must be
      available=False with no_response == number sampled.

  TestSamplerThreshold
      When sample_count=4 and threshold=0.5, the block should be
      declared available as long as at least 2 columns verify.
      This test uses a mock that fails 2 of 4 columns.

  TestSamplerSpecificColumns
      sample_specific() must query exactly the column indices given,
      not a random subset.
"""

import asyncio
import unittest
from src.nodes.peerdas_network import (
    MSG_SAMPLE_RESP,
    NodeInfo,
    SubnetRegistry,
    Verifier,
)
from src.sampling.sampler import ColumnResult, SampleResult, Sampler


# =============================================================================
# Helpers
# =============================================================================

# Fake DA node infos -- no servers are started; these just populate
# the registry so the sampler has nodes to choose from.
_DA_INFOS = [
    NodeInfo(f"da-{j}", "127.0.0.1", 9980 + j) for j in range(4)
]

# Each DA node custodies two columns.
_CUSTODY = {
    "da-0": {0, 1},
    "da-1": {1, 2},
    "da-2": {2, 3},
    "da-3": {3, 0},
}

_N_COLS = 4


def _make_good_resp(col_idx: int) -> dict:
    """Return a realistic-looking MSG_SAMPLE_RESP for col_idx."""
    return {
        "type":        MSG_SAMPLE_RESP,
        "block_id":    "testblock001",
        "col_index":   col_idx,
        "cells":       [[1, 2, 3], [4, 5, 6]],
        "commitments": ["aabbcc", "ddeeff"],
        "proof":       "00112233",
    }


def _make_sampler(
    mock_fetch,
    sample_count: int = 0,
    threshold: float = 1.0,
) -> Sampler:
    """
    Build a Sampler with a mocked fetch_column.

    We replace fetch_column on the Verifier instance so the sampler
    calls our mock instead of opening a real TCP connection.
    """
    info     = NodeInfo("verifier", "127.0.0.1", 9979)
    verifier = Verifier(info)
    # Replace the bound method -- Python calls mock_fetch(node, ...)
    # directly without passing `self`.
    verifier.fetch_column = mock_fetch
    registry = SubnetRegistry(_DA_INFOS, _CUSTODY)
    return Sampler(
        verifier,
        registry,
        n_cols=      _N_COLS,
        sample_count=sample_count,
        threshold=   threshold,
    )


# =============================================================================
# Test: all columns respond and verify
# =============================================================================


class TestSamplerAllColumnsVerify(unittest.IsolatedAsyncioTestCase):

    async def test_available_when_all_columns_verify(self):
        """
        When every node responds with a valid column, the block
        must be declared available and all results should verify.
        """
        async def mock_fetch(node, block_id, col_idx):
            # Every request succeeds with a well-formed response.
            return _make_good_resp(col_idx)

        sampler = _make_sampler(mock_fetch, sample_count=_N_COLS)
        result  = await sampler.sample("testblock001")

        self.assertTrue(
            result.available,
            "Block must be available when all columns verify",
        )
        self.assertEqual(
            result.verified_count,
            _N_COLS,
            "All sampled columns should have been verified",
        )
        self.assertEqual(
            result.no_response,
            0,
            "There should be no missing responses",
        )
        self.assertEqual(
            result.failed_count,
            0,
            "There should be no failed KZG proofs",
        )


# =============================================================================
# Test: no nodes respond
# =============================================================================


class TestSamplerNoNodesRespond(unittest.IsolatedAsyncioTestCase):

    async def test_unavailable_when_no_nodes_respond(self):
        """
        When every node is silent (returns None), the block must be
        declared unavailable and no_response should equal the number
        of columns sampled.
        """
        async def mock_fetch(node, block_id, col_idx):
            # Simulate a node that is offline / unreachable.
            return None

        sampler = _make_sampler(mock_fetch, sample_count=_N_COLS)
        result  = await sampler.sample("testblock001")

        self.assertFalse(
            result.available,
            "Block must be unavailable when no nodes respond",
        )
        self.assertEqual(
            result.verified_count,
            0,
            "No columns should have been verified",
        )
        self.assertEqual(
            result.no_response,
            _N_COLS,
            "All sampled columns should show as no-response",
        )


# =============================================================================
# Test: threshold allows partial verification
# =============================================================================


class TestSamplerThreshold(unittest.IsolatedAsyncioTestCase):

    async def test_available_when_threshold_met_but_not_all(self):
        """
        With threshold=0.5 and 4 columns sampled, the block should
        be declared available if at least 2 columns verify.
        This test makes columns 0 and 1 fail, columns 2 and 3 pass.
        """
        async def mock_fetch(node, block_id, col_idx):
            if col_idx in (0, 1):
                # Simulate unreachable node for these columns.
                return None
            return _make_good_resp(col_idx)

        # sample_specific so we control exactly which 4 cols are hit.
        sampler = _make_sampler(
            mock_fetch, sample_count=4, threshold=0.5
        )
        result  = await sampler.sample_specific(
            "testblock001", [0, 1, 2, 3]
        )

        self.assertTrue(
            result.available,
            "Block should be available when threshold (0.5) is met "
            "(2 of 4 columns verified)",
        )
        self.assertEqual(result.verified_count, 2)
        self.assertEqual(result.no_response, 2)

    async def test_unavailable_when_threshold_not_met(self):
        """
        With threshold=0.75 and 4 columns sampled, the block should
        be unavailable if only 2 of 4 columns verify (50% < 75%).
        """
        async def mock_fetch(node, block_id, col_idx):
            if col_idx in (0, 1):
                return None
            return _make_good_resp(col_idx)

        sampler = _make_sampler(
            mock_fetch, sample_count=4, threshold=0.75
        )
        result  = await sampler.sample_specific(
            "testblock001", [0, 1, 2, 3]
        )

        self.assertFalse(
            result.available,
            "Block should be unavailable when threshold (0.75) is "
            "not met (only 2 of 4 columns verified)",
        )


# =============================================================================
# Test: sample_specific queries exactly the given columns
# =============================================================================


class TestSamplerSpecificColumns(unittest.IsolatedAsyncioTestCase):

    async def test_sample_specific_queries_given_columns(self):
        """
        sample_specific() must query exactly the column indices we
        pass in, not a random subset.  We track which columns were
        actually requested in the mock and compare.
        """
        requested_cols = []

        async def mock_fetch(node, block_id, col_idx):
            requested_cols.append(col_idx)
            return _make_good_resp(col_idx)

        sampler  = _make_sampler(mock_fetch)
        want     = [0, 2]   # specific subset, not random
        result   = await sampler.sample_specific(
            "testblock001", want
        )

        self.assertEqual(
            sorted(requested_cols),
            sorted(want),
            "sample_specific must query exactly the given columns",
        )
        self.assertEqual(
            result.columns_tried,
            want,
            "SampleResult.columns_tried should match the input list",
        )
        self.assertTrue(
            result.available,
            "Block should be available when both specific columns "
            "respond and verify",
        )


if __name__ == "__main__":
    unittest.main()
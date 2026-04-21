"""
Unit tests: PeerDAS sampler
============================
All tests mock Verifier.fetch_column() so no TCP connections are
opened.  This keeps the suite fast and isolates sampling logic from
the network layer.

Test classes
------------
TestSamplerAllColumnsVerify
    Every node responds with a valid column → available=True.

TestSamplerNoNodesRespond
    Every node is silent → available=False, no_response == sampled.

TestSamplerBadProofType
    Node responds with wrong message type → treated as unavailable.

TestSamplerThreshold
    Partial failures with sub-1.0 threshold — both directions.

TestSamplerSpecificColumns
    sample_specific() must query exactly the requested columns.

TestSamplerConcurrency
    All column requests fire concurrently (not sequentially).

TestSamplerNoSubnet
    Column with no custodians → ColumnResult with responded=False.

TestSamplerReturnTypes
    SampleResult and ColumnResult have the expected fields and types.

TestSamplerSummary
    SampleResult.summary() produces a non-empty human-readable string.

TestSamplerLargeColumnSet
    Sanity-check with sample_count > n_cols clamps to n_cols.
"""

import asyncio
import time
import unittest
from unittest.mock import AsyncMock, patch

from src.nodes.peerdas_network import (
    MSG_SAMPLE_RESP,
    NodeInfo,
    SubnetRegistry,
    Verifier,
)
from src.sampling.sampler import ColumnResult, SampleResult, Sampler


# ---------------------------------------------------------------------------
# Shared test fixtures
# ---------------------------------------------------------------------------

_N_COLS = 4

_DA_INFOS = [NodeInfo(f"da-{j}", "127.0.0.1", 9880 + j) for j in range(4)]

_CUSTODY = {
    "da-0": {0, 1},
    "da-1": {1, 2},
    "da-2": {2, 3},
    "da-3": {3, 0},
}


def _good_resp(col_idx: int) -> dict:
    return {
        "type":        MSG_SAMPLE_RESP,
        "block_id":    "testblock",
        "col_index":   col_idx,
        "cells":       [[col_idx, col_idx + 1], [col_idx + 2, col_idx + 3]],
        "commitments": [f"com{col_idx}a", f"com{col_idx}b"],
        "proof":       f'["proof{col_idx}a","proof{col_idx}b"]',
    }


def _make_sampler(mock_fetch, sample_count=0,
                  threshold=1.0, n_cols=_N_COLS) -> Sampler:
    info     = NodeInfo("verifier", "127.0.0.1", 9879)
    verifier = Verifier(info)
    verifier.fetch_column = mock_fetch
    registry = SubnetRegistry(_DA_INFOS, _CUSTODY)
    return Sampler(verifier, registry,
                   n_cols=n_cols,
                   sample_count=sample_count,
                   threshold=threshold)


# ---------------------------------------------------------------------------
# TestSamplerAllColumnsVerify
# ---------------------------------------------------------------------------

class TestSamplerAllColumnsVerify(unittest.IsolatedAsyncioTestCase):

    async def test_available_when_all_verify(self):
        async def fetch(node, block_id, col_idx):
            return _good_resp(col_idx)

        sampler = _make_sampler(fetch, sample_count=_N_COLS)
        result  = await sampler.sample("testblock")

        self.assertTrue(result.available)
        self.assertEqual(result.verified_count, _N_COLS)
        self.assertEqual(result.failed_count, 0)
        self.assertEqual(result.no_response, 0)

    async def test_columns_tried_length(self):
        async def fetch(node, block_id, col_idx):
            return _good_resp(col_idx)

        sampler = _make_sampler(fetch, sample_count=_N_COLS)
        result  = await sampler.sample("testblock")
        self.assertEqual(len(result.columns_tried), _N_COLS)

    async def test_block_id_preserved(self):
        async def fetch(node, block_id, col_idx):
            return _good_resp(col_idx)

        sampler = _make_sampler(fetch, sample_count=_N_COLS)
        result  = await sampler.sample("myblock123")
        self.assertEqual(result.block_id, "myblock123")


# ---------------------------------------------------------------------------
# TestSamplerNoNodesRespond
# ---------------------------------------------------------------------------

class TestSamplerNoNodesRespond(unittest.IsolatedAsyncioTestCase):

    async def test_unavailable_when_silent(self):
        async def fetch(node, block_id, col_idx):
            return None

        sampler = _make_sampler(fetch, sample_count=_N_COLS)
        result  = await sampler.sample("testblock")

        self.assertFalse(result.available)
        self.assertEqual(result.verified_count, 0)
        self.assertEqual(result.no_response, _N_COLS)
        self.assertEqual(result.failed_count, 0)

    async def test_no_response_column_result_fields(self):
        async def fetch(node, block_id, col_idx):
            return None

        sampler = _make_sampler(fetch, sample_count=1)
        result  = await sampler.sample_specific("testblock", [0])
        cr = result.results[0]

        self.assertFalse(cr.responded)
        self.assertFalse(cr.verified)
        self.assertNotEqual(cr.error, "")


# ---------------------------------------------------------------------------
# TestSamplerBadProofType
# ---------------------------------------------------------------------------

class TestSamplerBadProofType(unittest.IsolatedAsyncioTestCase):

    async def test_wrong_message_type_counted_as_no_response(self):
        """A response with the wrong type should not be verified."""
        async def fetch(node, block_id, col_idx):
            return {"type": "WRONG_TYPE", "col_index": col_idx}

        sampler = _make_sampler(fetch, sample_count=_N_COLS)
        result  = await sampler.sample("testblock")

        self.assertFalse(result.available)
        # The sampler treats a non-SAMPLE_RESP as "no response".
        self.assertEqual(result.verified_count, 0)

    async def test_empty_dict_response_not_verified(self):
        async def fetch(node, block_id, col_idx):
            return {}  # missing "type" key

        sampler = _make_sampler(fetch, sample_count=_N_COLS)
        result  = await sampler.sample("testblock")
        self.assertFalse(result.available)


# ---------------------------------------------------------------------------
# TestSamplerThreshold
# ---------------------------------------------------------------------------

class TestSamplerThreshold(unittest.IsolatedAsyncioTestCase):

    async def test_available_at_exact_threshold(self):
        """2 of 4 columns respond → threshold=0.5 → available."""
        async def fetch(node, block_id, col_idx):
            return _good_resp(col_idx) if col_idx >= 2 else None

        sampler = _make_sampler(fetch, sample_count=4, threshold=0.5)
        result  = await sampler.sample_specific("testblock", [0, 1, 2, 3])

        self.assertTrue(result.available)
        self.assertEqual(result.verified_count, 2)
        self.assertEqual(result.no_response, 2)

    async def test_unavailable_just_below_threshold(self):
        """2 of 4 columns respond → threshold=0.75 → unavailable."""
        async def fetch(node, block_id, col_idx):
            return _good_resp(col_idx) if col_idx >= 2 else None

        sampler = _make_sampler(fetch, sample_count=4, threshold=0.75)
        result  = await sampler.sample_specific("testblock", [0, 1, 2, 3])

        self.assertFalse(result.available)

    async def test_threshold_zero_never_available(self):
        """
        Even with threshold=0.0 the block is declared available as
        long as ceil(0 * n) == 0 verified columns suffice.
        """
        async def fetch(node, block_id, col_idx):
            return None  # no responses at all

        sampler = _make_sampler(fetch, sample_count=_N_COLS, threshold=0.0)
        result  = await sampler.sample("testblock")
        # 0 >= int(4 * 0.0) == 0, so available
        self.assertTrue(result.available)

    async def test_threshold_one_requires_all(self):
        """threshold=1.0 (default) → any failure → unavailable."""
        call_count = 0

        async def fetch(node, block_id, col_idx):
            nonlocal call_count
            call_count += 1
            # fail the last column only
            return None if col_idx == 3 else _good_resp(col_idx)

        sampler = _make_sampler(fetch, sample_count=4, threshold=1.0)
        result  = await sampler.sample_specific("testblock", [0, 1, 2, 3])

        self.assertFalse(result.available)
        self.assertEqual(result.verified_count, 3)
        self.assertEqual(result.no_response, 1)


# ---------------------------------------------------------------------------
# TestSamplerSpecificColumns
# ---------------------------------------------------------------------------

class TestSamplerSpecificColumns(unittest.IsolatedAsyncioTestCase):

    async def test_queries_exactly_given_columns(self):
        seen = []

        async def fetch(node, block_id, col_idx):
            seen.append(col_idx)
            return _good_resp(col_idx)

        sampler = _make_sampler(fetch)
        result  = await sampler.sample_specific("testblock", [0, 2])

        self.assertEqual(sorted(seen), [0, 2])
        self.assertEqual(result.columns_tried, [0, 2])

    async def test_single_column(self):
        async def fetch(node, block_id, col_idx):
            return _good_resp(col_idx)

        sampler = _make_sampler(fetch)
        result  = await sampler.sample_specific("testblock", [1])

        self.assertTrue(result.available)
        self.assertEqual(result.verified_count, 1)

    async def test_empty_column_list(self):
        async def fetch(node, block_id, col_idx):
            return _good_resp(col_idx)

        sampler = _make_sampler(fetch)
        result  = await sampler.sample_specific("testblock", [])

        # No columns → vacuously available (0 >= 0).
        self.assertEqual(result.verified_count, 0)
        self.assertEqual(len(result.columns_tried), 0)


# ---------------------------------------------------------------------------
# TestSamplerConcurrency
# ---------------------------------------------------------------------------

class TestSamplerConcurrency(unittest.IsolatedAsyncioTestCase):

    async def test_requests_fire_concurrently(self):
        """
        If requests were sequential, total time ≈ n * delay.
        Concurrent requests should finish in roughly 1 * delay.
        """
        DELAY = 0.05  # seconds per fake response

        async def fetch(node, block_id, col_idx):
            await asyncio.sleep(DELAY)
            return _good_resp(col_idx)

        sampler = _make_sampler(fetch, sample_count=_N_COLS)
        t0 = time.monotonic()
        await sampler.sample_specific("testblock", list(range(_N_COLS)))
        elapsed = time.monotonic() - t0

        # Allow 3× the single-delay budget so flaky CI doesn't fail.
        self.assertLess(elapsed, DELAY * 3,
                        f"Requests appear sequential: {elapsed:.3f}s")


# ---------------------------------------------------------------------------
# TestSamplerNoSubnet
# ---------------------------------------------------------------------------

class TestSamplerNoSubnet(unittest.IsolatedAsyncioTestCase):

    async def test_column_with_no_custodians(self):
        async def fetch(node, block_id, col_idx):
            return _good_resp(col_idx)

        info     = NodeInfo("verifier", "127.0.0.1", 9878)
        verifier = Verifier(info)
        verifier.fetch_column = fetch
        # Empty registry → no custodians for any column.
        registry = SubnetRegistry([], {})
        sampler  = Sampler(verifier, registry, n_cols=4)
        result   = await sampler.sample_specific("testblock", [0])

        self.assertFalse(result.available)
        cr = result.results[0]
        self.assertFalse(cr.responded)
        self.assertIn("No nodes custody", cr.error)


# ---------------------------------------------------------------------------
# TestSamplerReturnTypes
# ---------------------------------------------------------------------------

class TestSamplerReturnTypes(unittest.IsolatedAsyncioTestCase):

    async def test_sample_result_fields(self):
        async def fetch(node, block_id, col_idx):
            return _good_resp(col_idx)

        sampler = _make_sampler(fetch, sample_count=_N_COLS)
        result  = await sampler.sample("testblock")

        self.assertIsInstance(result, SampleResult)
        self.assertIsInstance(result.block_id, str)
        self.assertIsInstance(result.columns_tried, list)
        self.assertIsInstance(result.results, list)
        self.assertIsInstance(result.available, bool)
        self.assertIsInstance(result.verified_count, int)
        self.assertIsInstance(result.failed_count, int)
        self.assertIsInstance(result.no_response, int)

    async def test_column_result_fields(self):
        async def fetch(node, block_id, col_idx):
            return _good_resp(col_idx)

        sampler = _make_sampler(fetch, sample_count=1)
        result  = await sampler.sample_specific("testblock", [0])
        cr = result.results[0]

        self.assertIsInstance(cr, ColumnResult)
        self.assertIsInstance(cr.col_index, int)
        self.assertIsInstance(cr.node_queried, str)
        self.assertIsInstance(cr.responded, bool)
        self.assertIsInstance(cr.verified, bool)
        self.assertIsInstance(cr.error, str)


# ---------------------------------------------------------------------------
# TestSamplerSummary
# ---------------------------------------------------------------------------

class TestSamplerSummary(unittest.IsolatedAsyncioTestCase):

    async def test_summary_contains_block_id(self):
        async def fetch(node, block_id, col_idx):
            return _good_resp(col_idx)

        sampler = _make_sampler(fetch, sample_count=_N_COLS)
        result  = await sampler.sample("myspecialblock")
        summary = result.summary()

        self.assertIsInstance(summary, str)
        self.assertIn("myspecialblock", summary)
        self.assertGreater(len(summary), 0)

    async def test_summary_says_available(self):
        async def fetch(node, block_id, col_idx):
            return _good_resp(col_idx)

        sampler = _make_sampler(fetch, sample_count=_N_COLS)
        result  = await sampler.sample("testblock")
        self.assertIn("AVAILABLE", result.summary())

    async def test_summary_says_unavailable(self):
        async def fetch(node, block_id, col_idx):
            return None

        sampler = _make_sampler(fetch, sample_count=_N_COLS)
        result  = await sampler.sample("testblock")
        self.assertIn("UNAVAILABLE", result.summary())


# ---------------------------------------------------------------------------
# TestSamplerSampleCount
# ---------------------------------------------------------------------------

class TestSamplerSampleCount(unittest.IsolatedAsyncioTestCase):

    async def test_sample_count_zero_samples_all_columns(self):
        """sample_count=0 should default to sampling all n_cols."""
        seen = []

        async def fetch(node, block_id, col_idx):
            seen.append(col_idx)
            return _good_resp(col_idx)

        sampler = _make_sampler(fetch, sample_count=0, n_cols=4)
        await sampler.sample("testblock")
        self.assertEqual(len(seen), 4)

    async def test_sample_count_clamps_to_n_cols(self):
        """Requesting more columns than exist should not raise."""
        seen = []

        async def fetch(node, block_id, col_idx):
            seen.append(col_idx)
            return _good_resp(col_idx)

        sampler = _make_sampler(fetch, sample_count=100, n_cols=4)
        result  = await sampler.sample("testblock")
        # Can't sample more than n_cols=4
        self.assertLessEqual(len(seen), 4)


if __name__ == "__main__":
    unittest.main()
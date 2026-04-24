"""
Unit tests: PeerDAS networking layer
=====================================
Covers DANode, Disperser, SubnetRegistry, and wire-format helpers.

Test classes
------------
TestSubnetRegistry
    Pure data-structure tests — no TCP, no KZG, fast.

TestWireFormat
    encode_msg / decode_msg round-trips.

TestDANodeHandleColumn
    _handle_column() called directly (no TCP) so the test is
    deterministic and doesn't need a port.

TestDANodeHandleSampleReq
    _handle_sample_req() called directly for present / absent
    columns.

TestDANodeIntegration
    Full TCP round-trip using asyncio servers.  Two sub-tests:
      1. Disperser delivers col 0; DA node stores it correctly.
      2. Node discards a column outside its custody set.
      3. Node replies MSG_UNAVAILABLE for an unknown block.

TestEncodeMatrix
    _encode_matrix() / _byte_split_matrix() shape checks so the
    matrix dimensions are always (n_blobs x n_cols) and each
    cell is a non-empty list.  KZG is exercised at tiny parameters
    (n_blobs=2, n_cols=4) to keep setup time tolerable.
"""

import asyncio
import json
import unittest
from unittest.mock import AsyncMock, MagicMock, patch

from src.nodes.peerdas_network import (
    MSG_COLUMN,
    MSG_SAMPLE_REQ,
    MSG_SAMPLE_RESP,
    MSG_UNAVAILABLE,
    Column,
    DANode,
    Disperser,
    NodeInfo,
    SubnetRegistry,
    Verifier,
    _encode_matrix,
    decode_msg,
    encode_msg,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _col_payload(block_id="blk001", col_index=0, n_cols=8, n_blobs=2) -> dict:
    """A minimal well-formed MSG_COLUMN payload."""
    return {
        "type": MSG_COLUMN,
        "block_id": block_id,
        "col_index": col_index,
        "n_cols": n_cols,
        "cells": [
            list(range(col_index, col_index + 3)) for _ in range(n_blobs)
        ],
        "commitments": [f"com{b}" for b in range(n_blobs)],
        "proof": json.dumps([f"proof{b}" for b in range(n_blobs)]),
    }


def _make_da_node(node_id="da-0", port=0, custody=None) -> DANode:
    info = NodeInfo(node_id, "127.0.0.1", port)
    return DANode(info, custody_columns=custody or {0, 1})


# ---------------------------------------------------------------------------
# TestSubnetRegistry
# ---------------------------------------------------------------------------


class TestSubnetRegistry(unittest.TestCase):
    """Pure data-structure tests — no network, no KZG."""

    def setUp(self):
        self.infos = [
            NodeInfo("da-0", "127.0.0.1", 9990),
            NodeInfo("da-1", "127.0.0.1", 9991),
            NodeInfo("da-2", "127.0.0.1", 9992),
        ]
        self.custody = {
            "da-0": {0, 1},
            "da-1": {1, 2},
            "da-2": {3},
        }
        self.reg = SubnetRegistry(self.infos, self.custody)

    def test_single_custodian(self):
        col0 = self.reg.nodes_for_column(0)
        self.assertEqual(len(col0), 1)
        self.assertEqual(col0[0].node_id, "da-0")

    def test_shared_custodianship(self):
        ids = {n.node_id for n in self.reg.nodes_for_column(1)}
        self.assertEqual(ids, {"da-0", "da-1"})

    def test_unique_custodian(self):
        col3 = self.reg.nodes_for_column(3)
        self.assertEqual(len(col3), 1)
        self.assertEqual(col3[0].node_id, "da-2")

    def test_unknown_column_returns_empty(self):
        self.assertEqual(self.reg.nodes_for_column(99), [])

    def test_all_columns_lists_known_columns(self):
        cols = set(self.reg.all_columns())
        self.assertEqual(cols, {0, 1, 2, 3})

    def test_empty_custody_map(self):
        reg = SubnetRegistry(self.infos, {})
        self.assertEqual(reg.nodes_for_column(0), [])

    def test_node_not_in_infos_is_ignored(self):
        """A custody entry for an unknown node_id has no effect."""
        custody = {"ghost-node": {0}}
        reg = SubnetRegistry(self.infos, custody)
        # No NodeInfo for ghost-node was given, so column 0 has no
        # custodians from the registry's perspective.
        self.assertEqual(reg.nodes_for_column(0), [])


# ---------------------------------------------------------------------------
# TestWireFormat
# ---------------------------------------------------------------------------


class TestWireFormat(unittest.TestCase):
    def test_encode_decode_roundtrip(self):
        payload = {"block_id": "abc", "col_index": 3}
        raw = encode_msg(MSG_SAMPLE_REQ, payload)
        msg = decode_msg(raw)
        self.assertEqual(msg["type"], MSG_SAMPLE_REQ)
        self.assertEqual(msg["block_id"], "abc")
        self.assertEqual(msg["col_index"], 3)

    def test_encode_produces_newline_terminated_bytes(self):
        raw = encode_msg(MSG_UNAVAILABLE, {"block_id": "x", "col_index": 0})
        self.assertIsInstance(raw, bytes)
        self.assertTrue(raw.endswith(b"\n"))

    def test_decode_strips_whitespace(self):
        raw = b'{"type": "FOO", "v": 1}  \n'
        msg = decode_msg(raw)
        self.assertEqual(msg["type"], "FOO")
        self.assertEqual(msg["v"], 1)


# ---------------------------------------------------------------------------
# TestDANodeHandleColumn  (no TCP)
# ---------------------------------------------------------------------------


class TestDANodeHandleColumn(unittest.IsolatedAsyncioTestCase):
    async def test_stores_column_within_custody(self):
        node = _make_da_node(custody={0})
        payload = _col_payload(col_index=0)
        await node._handle_column(payload)
        self.assertIn("blk001", node.store)
        self.assertIn(0, node.store["blk001"])

    async def test_discards_column_outside_custody(self):
        node = _make_da_node(custody={0})
        payload = _col_payload(col_index=5)
        await node._handle_column(payload)
        self.assertEqual(len(node.store), 0)

    async def test_stored_column_fields(self):
        node = _make_da_node(custody={2})
        payload = _col_payload(
            block_id="myblock", col_index=2, n_cols=16, n_blobs=3
        )
        await node._handle_column(payload)
        col = node.store["myblock"][2]
        self.assertEqual(col.block_id, "myblock")
        self.assertEqual(col.col_index, 2)
        self.assertEqual(col.n_cols, 16)
        self.assertEqual(len(col.cells), 3)
        self.assertEqual(len(col.commitments), 3)

    async def test_multiple_blocks_stored_independently(self):
        node = _make_da_node(custody={0})
        await node._handle_column(_col_payload(block_id="blkA", col_index=0))
        await node._handle_column(_col_payload(block_id="blkB", col_index=0))
        self.assertIn("blkA", node.store)
        self.assertIn("blkB", node.store)

    async def test_overwrites_same_block_same_col(self):
        """Re-delivering the same (block, col) should just overwrite."""
        node = _make_da_node(custody={0})
        p1 = _col_payload(col_index=0)
        p1["commitments"] = ["original"]
        p2 = _col_payload(col_index=0)
        p2["commitments"] = ["updated"]
        await node._handle_column(p1)
        await node._handle_column(p2)
        col = node.store["blk001"][0]
        self.assertEqual(col.commitments, ["updated"])


# ---------------------------------------------------------------------------
# TestDANodeHandleSampleReq  (no TCP)
# ---------------------------------------------------------------------------


class TestDANodeHandleSampleReq(unittest.IsolatedAsyncioTestCase):
    def _plant_column(
        self, node: DANode, block_id="blk001", col_index=0
    ) -> Column:
        col = Column(
            block_id=block_id,
            col_index=col_index,
            n_cols=8,
            cells=[[1, 2], [3, 4]],
            commitments=["comA", "comB"],
            proof='["pA","pB"]',
        )
        node.store.setdefault(block_id, {})[col_index] = col
        return col

    async def test_returns_sample_resp_for_present_column(self):
        node = _make_da_node(custody={0})
        self._plant_column(node, "blk001", 0)
        req = {"block_id": "blk001", "col_index": 0}
        raw = node._handle_sample_req(req)
        msg = decode_msg(raw)
        self.assertEqual(msg["type"], MSG_SAMPLE_RESP)
        self.assertEqual(msg["col_index"], 0)
        self.assertEqual(msg["block_id"], "blk001")

    async def test_returns_unavailable_for_missing_block(self):
        node = _make_da_node()
        req = {"block_id": "ghost", "col_index": 0}
        raw = node._handle_sample_req(req)
        msg = decode_msg(raw)
        self.assertEqual(msg["type"], MSG_UNAVAILABLE)
        self.assertEqual(msg["block_id"], "ghost")

    async def test_returns_unavailable_for_missing_column(self):
        node = _make_da_node(custody={0, 1})
        # plant col 0 only
        self._plant_column(node, "blk001", 0)
        req = {"block_id": "blk001", "col_index": 1}
        raw = node._handle_sample_req(req)
        msg = decode_msg(raw)
        self.assertEqual(msg["type"], MSG_UNAVAILABLE)
        self.assertEqual(msg["col_index"], 1)

    async def test_sample_resp_contains_proof_and_cells(self):
        node = _make_da_node(custody={3})
        col = self._plant_column(node, "blk001", 3)
        req = {"block_id": "blk001", "col_index": 3}
        raw = node._handle_sample_req(req)
        msg = decode_msg(raw)
        self.assertEqual(msg["cells"], col.cells)
        self.assertEqual(msg["commitments"], col.commitments)
        self.assertEqual(msg["proof"], col.proof)

    async def test_unknown_message_type_returns_none(self):
        node = _make_da_node()
        result = await node.handle_message({"type": "BOGUS"})
        self.assertIsNone(result)


# ---------------------------------------------------------------------------
# TestDANodeIntegration  (real TCP, real KZG at tiny parameters)
# ---------------------------------------------------------------------------


class TestDANodeIntegration(unittest.IsolatedAsyncioTestCase):
    """
    These tests start real asyncio servers.  KZG is run at
    (n_blobs=2, n_cols=4) to keep setup time tolerable (~2-4 s).
    """

    N_BLOBS = 2
    N_COLS = 4
    BASE = 9300  # port base — adjust if clashes occur in CI

    async def asyncSetUp(self):
        da_info = NodeInfo("da-0", "127.0.0.1", self.BASE)
        disp_info = NodeInfo("disp", "127.0.0.1", self.BASE + 1)

        self.da = DANode(da_info, custody_columns={0, 1, 2, 3})
        custody = {"da-0": {0, 1, 2, 3}}
        registry = SubnetRegistry([da_info], custody)
        self.disp = Disperser(
            disp_info, registry, n_blobs=self.N_BLOBS, n_cols=self.N_COLS
        )

        self._tasks = [
            asyncio.create_task(self.da.start()),
            asyncio.create_task(self.disp.start()),
        ]
        await asyncio.sleep(0.3)

    async def asyncTearDown(self):
        for t in self._tasks:
            t.cancel()
        await asyncio.sleep(0.05)

    async def test_disperser_stores_all_columns_on_da_node(self):
        block_id = await self.disp.disperse(b"hello peerdas test" * 4)
        await asyncio.sleep(0.2)

        self.assertIn(block_id, self.da.store)
        for c in range(self.N_COLS):
            self.assertIn(
                c, self.da.store[block_id], f"col {c} missing from store"
            )

    async def test_stored_column_metadata(self):
        block_id = await self.disp.disperse(b"metadata check" * 4)
        await asyncio.sleep(0.2)

        col = self.da.store[block_id][0]
        self.assertEqual(col.n_cols, self.N_COLS)
        self.assertEqual(len(col.cells), self.N_BLOBS)
        self.assertEqual(len(col.commitments), self.N_BLOBS)
        # proof is a JSON list of hex strings
        proofs = json.loads(col.proof)
        self.assertEqual(len(proofs), self.N_BLOBS)

    async def test_second_disperse_creates_separate_entry(self):
        id1 = await self.disp.disperse(b"block one" * 4)
        id2 = await self.disp.disperse(b"block two" * 4)
        await asyncio.sleep(0.2)

        self.assertNotEqual(id1, id2)
        self.assertIn(id1, self.da.store)
        self.assertIn(id2, self.da.store)


# ---------------------------------------------------------------------------
# TestEncodeMatrix  (shape + basic sanity, no TCP)
# ---------------------------------------------------------------------------


class TestEncodeMatrix(unittest.TestCase):
    """
    _encode_matrix / _byte_split_matrix: verify shapes only.
    KZG is exercised at (n_blobs=2, n_cols=4) — small but real.
    """

    N_BLOBS = 2
    N_COLS = 4

    def _check_shape(self, matrix, commitments, col_proofs):
        self.assertEqual(
            len(matrix), self.N_BLOBS, "matrix must have n_blobs rows"
        )
        for row in matrix:
            self.assertEqual(
                len(row), self.N_COLS, "each row must have n_cols cells"
            )
            for cell in row:
                self.assertIsInstance(cell, list)
                self.assertGreater(len(cell), 0, "each cell must be non-empty")

        self.assertEqual(
            len(commitments), self.N_BLOBS, "one commitment per blob"
        )
        self.assertEqual(len(col_proofs), self.N_COLS, "one proof per column")

    def test_encode_matrix_shape(self):
        matrix, coms, proofs = _encode_matrix(
            b"test data for shape check" * 8,
            self.N_BLOBS,
            self.N_COLS,
        )
        self._check_shape(matrix, coms, proofs)

    def test_commitments_are_hex_strings(self):
        _, coms, _ = _encode_matrix(
            b"abc" * 20,
            self.N_BLOBS,
            self.N_COLS,
        )
        for com in coms:
            self.assertIsInstance(com, str)
            # hex string: "x_hex:y_hex"
            self.assertIn(":", com)

    def test_proofs_are_json_lists(self):
        _, _, proofs = _encode_matrix(
            b"abc" * 20,
            self.N_BLOBS,
            self.N_COLS,
        )
        for proof in proofs:
            parsed = json.loads(proof)
            self.assertIsInstance(parsed, list)
            self.assertEqual(len(parsed), self.N_BLOBS)

    def test_different_data_gives_different_commitments(self):
        _, coms_a, _ = _encode_matrix(b"aaaa" * 20, self.N_BLOBS, self.N_COLS)
        _, coms_b, _ = _encode_matrix(b"bbbb" * 20, self.N_BLOBS, self.N_COLS)
        self.assertNotEqual(coms_a, coms_b)


if __name__ == "__main__":
    unittest.main()

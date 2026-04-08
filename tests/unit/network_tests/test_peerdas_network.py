"""
Tests: PeerDAS networking layer
--------------------------------
Covers the three main behaviours of DANode and the static
SubnetRegistry mapping.

  TestDANodeStoresColumn
      After the disperser sends a block, the DA node should have
      the column stored and its fields should be correct.

  TestDANodeIgnoresNonCustodiedColumn
      A DA node must silently discard columns outside its custody
      set.  The disperser should never send the wrong columns, but
      the node defends against it anyway.

  TestDANodeServesUnavailableForMissingColumn
      If a verifier asks for a column the DA node does not have,
      the node must respond with MSG_UNAVAILABLE rather than
      crashing or hanging.

  TestSubnetRegistry
      SubnetRegistry.nodes_for_column() must return exactly the
      nodes assigned to each column and an empty list for columns
      that have no custodian.
"""

import asyncio
import unittest
from src.nodes.peerdas_network import (
    DANode,
    Disperser,
    MSG_COLUMN,
    MSG_SAMPLE_REQ,
    MSG_UNAVAILABLE,
    NodeInfo,
    SubnetRegistry,
    Verifier,
    decode_msg,
    encode_msg,
)


# =============================================================================
# Test: DA node stores a column when the disperser sends one
# =============================================================================


class TestDANodeStoresColumn(unittest.IsolatedAsyncioTestCase):

    async def test_da_node_stores_column_after_dispersal(self):
        """
        After the disperser sends a block, the DA node should have
        the column in its store with the correct metadata.
        """
        da_info   = NodeInfo("da-0", "127.0.0.1", 9200)
        disp_info = NodeInfo("disperser", "127.0.0.1", 9201)

        # DA node custodies column 0.  The disperser will produce
        # N_COLS_DEFAULT = 8 columns, so only col 0 lands here.
        da_node   = DANode(da_info, custody_columns={0})
        custody   = {"da-0": {0}}
        registry  = SubnetRegistry([da_info], custody)
        disperser = Disperser(disp_info, registry, n_blobs=2, n_cols=8)

        tasks = [
            asyncio.create_task(da_node.start()),
            asyncio.create_task(disperser.start()),
        ]
        await asyncio.sleep(0.2)

        # Disperse a block -- this delivers column 0 to da_node.
        block_data = b"test block for column storage check"
        block_id   = await disperser.disperse(block_data)

        # Give the DA node a moment to finish writing to its store.
        await asyncio.sleep(0.1)

        self.assertIn(
            block_id,
            da_node.store,
            "DA node should have an entry for the dispersed block",
        )
        self.assertIn(
            0,
            da_node.store[block_id],
            "DA node should have stored column 0",
        )

        col = da_node.store[block_id][0]
        self.assertEqual(
            col.col_index,
            0,
            "Stored column should have col_index 0",
        )
        self.assertEqual(
            col.block_id,
            block_id,
            "Stored column block_id should match the dispersed one",
        )
        self.assertEqual(
            col.n_cols,
            8,
            "Stored column should record the total column count",
        )
        # cells is a list with one entry per blob (2 blobs here).
        self.assertEqual(
            len(col.cells),
            2,
            "Stored column should have one cell per blob",
        )
        # commitments is a list with one entry per blob.
        self.assertEqual(
            len(col.commitments),
            2,
            "Stored column should have one commitment per blob",
        )

        for task in tasks:
            task.cancel()


# =============================================================================
# Test: DA node ignores columns outside its custody set
# =============================================================================


class TestDANodeIgnoresNonCustodiedColumn(
    unittest.IsolatedAsyncioTestCase
):

    async def test_column_outside_custody_is_discarded(self):
        """
        A DA node must not store columns outside its custody set.
        We send a MSG_COLUMN for col_index=5 directly to a node
        that only custodies col_index=0.
        """
        # The node only custodies column 0.
        da_info = NodeInfo("da-0", "127.0.0.1", 9210)
        da_node = DANode(da_info, custody_columns={0})

        # We need a second node to send the rogue column message.
        sender_info = NodeInfo("sender", "127.0.0.1", 9211)
        sender      = Verifier(sender_info)  # reuse send() helper

        tasks = [
            asyncio.create_task(da_node.start()),
            asyncio.create_task(sender.start()),
        ]
        await asyncio.sleep(0.2)

        # Send a column the DA node doesn't custody (col_index=5).
        rogue_payload = {
            "block_id":    "aabbccdd1122",
            "col_index":   5,
            "n_cols":      8,
            "cells":       [[1, 2, 3], [4, 5, 6]],
            "commitments": ["deadbeef", "cafebabe"],
            "proof":       "00112233",
        }
        await sender.send(
            da_info,
            MSG_COLUMN,
            rogue_payload,
            wait_for_reply=False,
        )
        await asyncio.sleep(0.1)

        # The node should have nothing in its store.
        self.assertEqual(
            len(da_node.store),
            0,
            "DA node must not store a column outside its custody set",
        )

        for task in tasks:
            task.cancel()


# =============================================================================
# Test: DA node returns MSG_UNAVAILABLE for a missing column
# =============================================================================


class TestDANodeServesUnavailable(unittest.IsolatedAsyncioTestCase):

    async def test_unavailable_response_for_missing_column(self):
        """
        If a verifier asks for a column the DA node does not have,
        the node must respond with MSG_UNAVAILABLE.
        """
        da_info       = NodeInfo("da-0", "127.0.0.1", 9220)
        verifier_info = NodeInfo("verifier", "127.0.0.1", 9221)

        da_node  = DANode(da_info, custody_columns={0, 1})
        verifier = Verifier(verifier_info)

        tasks = [
            asyncio.create_task(da_node.start()),
            asyncio.create_task(verifier.start()),
        ]
        await asyncio.sleep(0.2)

        # Ask for a block that was never dispersed.
        resp = await verifier.send(
            da_info,
            MSG_SAMPLE_REQ,
            {"block_id": "nonexistent", "col_index": 0},
        )

        self.assertIsNotNone(
            resp,
            "DA node must send a response even for unknown blocks",
        )
        self.assertEqual(
            resp.get("type"),
            MSG_UNAVAILABLE,
            "Response type must be MSG_UNAVAILABLE",
        )
        self.assertEqual(
            resp.get("block_id"),
            "nonexistent",
            "Response must echo back the requested block_id",
        )

        for task in tasks:
            task.cancel()


# =============================================================================
# Test: SubnetRegistry maps columns to the correct nodes
# =============================================================================


class TestSubnetRegistry(unittest.IsolatedAsyncioTestCase):
    """No network required -- SubnetRegistry is a pure data structure."""

    async def test_nodes_for_column_returns_correct_nodes(self):
        """
        nodes_for_column(col_idx) should return exactly the nodes
        that listed col_idx in their custody set.
        """
        infos = [
            NodeInfo("da-0", "127.0.0.1", 9990),
            NodeInfo("da-1", "127.0.0.1", 9991),
            NodeInfo("da-2", "127.0.0.1", 9992),
        ]
        custody = {
            "da-0": {0, 1},
            "da-1": {1, 2},
            "da-2": {3},
        }
        registry = SubnetRegistry(infos, custody)

        # Column 0 is only custodied by da-0.
        col0 = registry.nodes_for_column(0)
        self.assertEqual(len(col0), 1)
        self.assertEqual(col0[0].node_id, "da-0")

        # Column 1 is custodied by both da-0 and da-1.
        col1_ids = {n.node_id for n in registry.nodes_for_column(1)}
        self.assertEqual(col1_ids, {"da-0", "da-1"})

        # Column 3 is only custodied by da-2.
        col3 = registry.nodes_for_column(3)
        self.assertEqual(len(col3), 1)
        self.assertEqual(col3[0].node_id, "da-2")

        # Column 99 has no custodian -- should return empty list.
        self.assertEqual(
            registry.nodes_for_column(99),
            [],
            "Unknown column must return an empty list",
        )


if __name__ == "__main__":
    unittest.main()
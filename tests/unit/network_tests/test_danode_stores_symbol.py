"""
Test: DA node stores a symbol when the disperser sends one
----------------------------------------------------------
The disperser sends a SYMBOL message to a DA node.
This test checks that the DA node correctly stores the symbol
so it can serve it later when a light node asks for it.
"""

import asyncio
import unittest
import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from src.nodes.network import DANode, Disperser, NodeInfo


class TestDANodeStoresSymbol(unittest.IsolatedAsyncioTestCase):

    async def test_da_node_stores_symbol_after_dispersal(self):
        """
        After the disperser sends a block, the DA node should have
        the symbol stored in its store dict.
        """
        da_info        = NodeInfo("da-0", "127.0.0.1", 9100)
        disperser_info = NodeInfo("disperser", "127.0.0.1", 9101)

        da_node   = DANode(da_info)
        disperser = Disperser(disperser_info, [da_info])

        # Start both nodes in the background
        tasks = [
            asyncio.create_task(da_node.start()),
            asyncio.create_task(disperser.start()),
        ]
        await asyncio.sleep(0.2)

        # Disperse a block -- this sends the symbol to the DA node
        block_data = b"test block data for storage test"
        block_id   = await disperser.disperse(block_data)

        # Give the DA node a moment to finish storing
        await asyncio.sleep(0.1)

        # The DA node should now have the symbol in its store
        self.assertIn(block_id, da_node.store,
                      "DA node should have stored the symbol after dispersal")

        stored = da_node.store[block_id]
        self.assertEqual(stored.index, 0,
                         "The stored symbol should have index 0 (only one node)")
        self.assertEqual(stored.n_total, 1,
                         "n_total should be 1 since there is only one DA node")
        self.assertEqual(stored.block_id, block_id,
                         "Stored symbol block_id should match the dispersed block_id")

        for task in tasks:
            task.cancel()


if __name__ == "__main__":
    unittest.main()
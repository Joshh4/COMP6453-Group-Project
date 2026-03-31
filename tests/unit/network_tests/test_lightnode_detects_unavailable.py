"""
Test: Light node correctly reports unavailable when a DA node has no symbol
---------------------------------------------------------------------------
If a light node asks a DA node for a symbol that was never sent to it,
the DA node should reply with UNAVAILABLE, and the light node's sample()
should return False.

This simulates an attacker withholding data -- the light node should
detect that the block is not fully available.
"""

import asyncio
import unittest
import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from src.nodes.network import DANode, Verifier, NodeInfo


class TestLightNodeDetectsUnavailable(unittest.IsolatedAsyncioTestCase):

    async def test_light_node_returns_false_when_symbol_missing(self):
        """
        If a DA node never received its symbol (e.g. the disperser withheld it),
        the light node's sample() should return False.
        """
        da_info    = NodeInfo("da-0", "127.0.0.1", 9300)
        light_info = NodeInfo("light-0", "127.0.0.1", 9301)

        da_node    = DANode(da_info)
        light_node = Verifier(light_info, [da_info])

        tasks = [
            asyncio.create_task(da_node.start()),
            asyncio.create_task(light_node.start()),
        ]
        await asyncio.sleep(0.2)

        # The DA node's store is empty -- no block was ever dispersed to it.
        # Asking for a block that doesn't exist should return False.
        result = await light_node.sample("nonexistent_block_id")

        self.assertFalse(result,
                         "sample() should return False when the DA node has no symbol")

        for task in tasks:
            task.cancel()

    async def test_da_node_store_is_empty_before_dispersal(self):
        """
        A freshly started DA node should have nothing in its store.
        """
        da_info = NodeInfo("da-0", "127.0.0.1", 9302)
        da_node = DANode(da_info)

        task = asyncio.create_task(da_node.start())
        await asyncio.sleep(0.1)

        self.assertEqual(len(da_node.store), 0,
                         "DA node store should be empty before any dispersal")

        task.cancel()


if __name__ == "__main__":
    unittest.main()
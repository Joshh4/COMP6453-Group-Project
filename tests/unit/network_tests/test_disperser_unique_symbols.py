"""
Test: Disperser sends each DA node a unique symbol with the correct index
-------------------------------------------------------------------------
When the disperser splits a block across n DA nodes, each node should
receive exactly one symbol, and every symbol should have a different index.
No two nodes should receive the same piece of the block.
"""

import asyncio
import unittest
import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from src.nodes.network import DANode, Disperser, NodeInfo


class TestDisperserSendsUniqueSymbols(unittest.IsolatedAsyncioTestCase):

    async def test_each_da_node_gets_a_unique_index(self):
        """
        With 4 DA nodes, each should end up with a different symbol index
        (0, 1, 2, 3) and all should reference the same block.
        """
        N = 4
        base_port = 9400

        da_infos      = [NodeInfo(f"da-{j}", "127.0.0.1", base_port + j) for j in range(N)]
        disperser_info = NodeInfo("disperser", "127.0.0.1", base_port + N)

        da_nodes  = [DANode(info) for info in da_infos]
        disperser = Disperser(disperser_info, da_infos)

        tasks = [asyncio.create_task(node.start()) for node in da_nodes]
        tasks.append(asyncio.create_task(disperser.start()))
        await asyncio.sleep(0.2)

        block_data = b"block for unique symbol index test" * 4
        block_id   = await disperser.disperse(block_data)
        await asyncio.sleep(0.1)

        # Every DA node should have received a symbol for this block
        for j, da_node in enumerate(da_nodes):
            self.assertIn(block_id, da_node.store,
                          f"DA node {j} should have a symbol for block {block_id}")

        # Collect all the indexes that were assigned
        indexes = [da_node.store[block_id].index for da_node in da_nodes]

        # Each index should be unique -- no two nodes got the same piece
        self.assertEqual(len(indexes), len(set(indexes)),
                         "Every DA node should have a unique symbol index")

        # The indexes should cover 0 through N-1
        self.assertEqual(sorted(indexes), list(range(N)),
                         "Symbol indexes should be 0, 1, 2, 3")

        # Every node should agree on the same total count
        for da_node in da_nodes:
            self.assertEqual(da_node.store[block_id].n_total, N,
                             "n_total should equal the number of DA nodes")

        for task in tasks:
            task.cancel()

    async def test_disperser_sends_same_commitment_to_all_nodes(self):
        """
        All DA nodes should receive the same commitment fingerprint,
        since it represents the whole block and is shared with everyone.
        """
        N = 3
        base_port = 9410

        da_infos       = [NodeInfo(f"da-{j}", "127.0.0.1", base_port + j) for j in range(N)]
        disperser_info = NodeInfo("disperser", "127.0.0.1", base_port + N)

        da_nodes  = [DANode(info) for info in da_infos]
        disperser = Disperser(disperser_info, da_infos)

        tasks = [asyncio.create_task(node.start()) for node in da_nodes]
        tasks.append(asyncio.create_task(disperser.start()))
        await asyncio.sleep(0.2)

        block_data = b"block for commitment consistency test"
        block_id   = await disperser.disperse(block_data)
        await asyncio.sleep(0.1)

        # Collect the commitment each node received
        commitments = [da_node.store[block_id].commitment for da_node in da_nodes]

        # They should all be the same value
        self.assertEqual(len(set(commitments)), 1,
                         "All DA nodes should have received the same commitment")

        for task in tasks:
            task.cancel()


if __name__ == "__main__":
    unittest.main()
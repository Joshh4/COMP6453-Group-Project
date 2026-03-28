"""
Test: Full end-to-end -- disperser sends block, light node confirms availability
--------------------------------------------------------------------------------
This test runs the complete protocol from start to finish:
  1. Disperser encodes a block and sends symbols to all DA nodes
  2. A light node samples all DA nodes and checks their proofs
  3. The light node should report the block as available

This is the closest thing to a real-world run of the protocol.
"""

import asyncio
import unittest
import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from src.nodes.network import DANode, Disperser, Verifier, NodeInfo


class TestEndToEnd(unittest.IsolatedAsyncioTestCase):

    async def test_block_is_available_after_dispersal(self):
        """
        After a block is dispersed across 8 DA nodes, a light node
        that samples all of them should report the block as available.
        """
        N = 8
        base_port = 9500

        da_infos       = [NodeInfo(f"da-{j}", "127.0.0.1", base_port + j) for j in range(N)]
        disperser_info = NodeInfo("disperser", "127.0.0.1", base_port + N)
        light_info     = NodeInfo("light-0",   "127.0.0.1", base_port + N + 1)

        da_nodes   = [DANode(info) for info in da_infos]
        disperser  = Disperser(disperser_info, da_infos)
        light_node = Verifier(light_info, da_infos)

        tasks = [asyncio.create_task(node.start()) for node in da_nodes]
        tasks.append(asyncio.create_task(disperser.start()))
        tasks.append(asyncio.create_task(light_node.start()))
        await asyncio.sleep(0.2)

        block_data = b"Hello CONDA! Full end-to-end test block." * 4
        block_id   = await disperser.disperse(block_data)
        await asyncio.sleep(0.1)

        result = await light_node.sample(block_id)

        self.assertTrue(result,
                        "Light node should report block as available after full dispersal")

        for task in tasks:
            task.cancel()

    async def test_multiple_light_nodes_all_agree_block_is_available(self):
        """
        Multiple independent light nodes sampling the same block should
        all come to the same conclusion -- the block is available.
        """
        N = 4
        base_port = 9520

        da_infos       = [NodeInfo(f"da-{j}", "127.0.0.1", base_port + j) for j in range(N)]
        disperser_info = NodeInfo("disperser", "127.0.0.1", base_port + N)
        light_infos    = [NodeInfo(f"light-{i}", "127.0.0.1", base_port + N + 1 + i) for i in range(3)]

        da_nodes    = [DANode(info) for info in da_infos]
        disperser   = Disperser(disperser_info, da_infos)
        light_nodes = [Verifier(info, da_infos) for info in light_infos]

        tasks = [asyncio.create_task(node.start()) for node in da_nodes]
        tasks.append(asyncio.create_task(disperser.start()))
        tasks += [asyncio.create_task(ln.start()) for ln in light_nodes]
        await asyncio.sleep(0.2)

        block_data = b"Block for multi-light-node agreement test" * 4
        block_id   = await disperser.disperse(block_data)
        await asyncio.sleep(0.1)

        # All three light nodes sample concurrently
        results = await asyncio.gather(*[ln.sample(block_id) for ln in light_nodes])

        self.assertTrue(all(results),
                        "All light nodes should agree the block is available")

        for task in tasks:
            task.cancel()


if __name__ == "__main__":
    unittest.main()
"""
Test: Light node receives a valid symbol when it samples a DA node
------------------------------------------------------------------
After the disperser has sent symbols out, a light node should be
able to ask a DA node for its symbol and get a valid response back.
This test checks the full request/response message flow between
the light node and a DA node.
"""

import asyncio
import unittest
import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from src.nodes.network import DANode, Disperser, Verifier, NodeInfo, MSG_SAMPLE_RESP


class TestLightNodeReceivesSymbol(unittest.IsolatedAsyncioTestCase):

    async def test_light_node_gets_symbol_from_da_node(self):
        """
        A light node that samples a DA node which has the symbol
        should receive a SAMPLE_RESP message with the symbol and proof.
        """
        da_info         = NodeInfo("da-0", "127.0.0.1", 9200)
        disperser_info  = NodeInfo("disperser", "127.0.0.1", 9201)
        light_info      = NodeInfo("light-0", "127.0.0.1", 9202)

        da_node    = DANode(da_info)
        disperser  = Disperser(disperser_info, [da_info])
        light_node = Verifier(light_info, [da_info])

        tasks = [
            asyncio.create_task(da_node.start()),
            asyncio.create_task(disperser.start()),
            asyncio.create_task(light_node.start()),
        ]
        await asyncio.sleep(0.2)

        # Disperse the block so the DA node has the symbol
        block_data = b"test block for light node sampling"
        block_id   = await disperser.disperse(block_data)
        await asyncio.sleep(0.1)

        # Light node directly asks the DA node for its symbol
        response = await light_node.send(
            da_info,
            "SAMPLE_REQ",
            {"block_id": block_id}
        )

        # Should get a response, not None
        self.assertIsNotNone(response,
                             "Light node should receive a response from the DA node")

        # The response should be a SAMPLE_RESP with the symbol and proof
        self.assertEqual(response["type"], MSG_SAMPLE_RESP,
                         "Response type should be SAMPLE_RESP")
        self.assertIn("data",       response, "Response should contain symbol data")
        self.assertIn("proof",      response, "Response should contain a proof")
        self.assertIn("commitment", response, "Response should contain the commitment")
        self.assertEqual(response["block_id"], block_id,
                         "Response block_id should match the requested block")

        for task in tasks:
            task.cancel()


if __name__ == "__main__":
    unittest.main()
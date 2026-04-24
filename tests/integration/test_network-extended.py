"""
Simple integration tests: PeerDAS end-to-end
=============================================
Uses a single shared event loop (setUpClass/tearDownClass) rather
than IsolatedAsyncioTestCase so servers start once and the KZG
context is generated once.  Avoids a Python 3.10 asyncio bug where
per-test event loop teardown causes a C-stack segfault via reprlib.

Run with:
    python -m pytest tests/integration/test_network-extended.py -v
"""

import asyncio
import unittest

from src.nodes.peerdas_network import (
    MSG_SAMPLE_RESP,
    MSG_UNAVAILABLE,
    DANode,
    Disperser,
    NodeInfo,
    SubnetRegistry,
    Verifier,
    _get_kzg_ctx,
)

N_BLOBS = 2
N_COLS  = 8
BASE    = 9600


class TestMultiNodeRoundTrip(unittest.TestCase):
    """
    One DA node custodying all columns, one disperser, one verifier.
    All five tests share the same servers and KZG context.
    """

    loop     = None
    da       = None
    disp     = None
    verifier = None
    kzg      = None
    registry = None
    da_info  = None
    _tasks   = []

    @classmethod
    def setUpClass(cls):
        cls.loop = asyncio.new_event_loop()
        asyncio.set_event_loop(cls.loop)
        cls.loop.run_until_complete(cls._start())

    @classmethod
    def tearDownClass(cls):
        cls.loop.run_until_complete(cls._stop())
        cls.loop.close()
        asyncio.set_event_loop(None)

    @classmethod
    async def _start(cls):
        da0_info       = NodeInfo("da-0",      "127.0.0.1", BASE)
        da1_info       = NodeInfo("da-1",      "127.0.0.1", BASE + 1)
        da2_info       = NodeInfo("da-2",      "127.0.0.1", BASE + 2)


        custody = {
            "da-0": {0, 1, 2},
            "da-1": {3, 4, 5},
            "da-2": {6, 7},
        }

        all_da_infos = [da0_info, da1_info, da2_info]
        cls.registry  = SubnetRegistry(all_da_infos, custody)

        cls.da_nodes = [
            DANode(da0_info, custody["da-0"]),
            DANode(da1_info, custody["da-1"]),
            DANode(da2_info, custody["da-2"]),
        ]
        cls.da_infos = {
            "da-0": da0_info,
            "da-1": da1_info,
            "da-2": da2_info,
        }

        disp_info     = NodeInfo("disperser", "127.0.0.1", BASE + 3)
        ver_info      = NodeInfo("verifier",  "127.0.0.1", BASE + 4)

        cls.disp      = Disperser(disp_info, cls.registry,
                                  n_blobs=N_BLOBS, n_cols=N_COLS)
        
        cls.verifier  = Verifier(ver_info)
        cls.kzg       = _get_kzg_ctx(N_BLOBS, N_COLS)

        cls._tasks = [
            asyncio.create_task(node.start()) for node in cls.da_nodes
        ] + [
            asyncio.create_task(cls.disp.start()),
            asyncio.create_task(cls.verifier.start()),
        ]
        await asyncio.sleep(0.4)

    @classmethod
    async def _stop(cls):
        for t in cls._tasks:
            t.cancel()
        await asyncio.gather(*cls._tasks, return_exceptions=True)
        await asyncio.sleep(0.1)

    # ------------------------------------------------------------------
    # Helper: run a coroutine on the shared loop from a sync test method
    # ------------------------------------------------------------------

    def run_async(self, coro):
        return self.loop.run_until_complete(coro)

    # ------------------------------------------------------------------
    # Tests
    # ------------------------------------------------------------------

    def test_columns_distributed_across_nodes(self):
        """Happy path: Each DA node only holds its assigned columns."""
        async def _run():
            block_id = await self.disp.disperse(b"multi-node test" * 4)
            await asyncio.sleep(0.2)

            custody_map = {
                "da-0": {0, 1, 2},
                "da-1": {3, 4, 5},
                "da-2": {6, 7},
            }

            for node_name, cols in custody_map.items():
                da_info = self.da_infos[node_name]
                for col_i in cols:
                    resp = await self.verifier.fetch_column(da_info, block_id, col_i)
                    self.assertIsNotNone(resp)
                    self.assertEqual(resp.get("type"), MSG_SAMPLE_RESP)
                    self.assertTrue(
                        self.kzg.verify_column(
                            resp["commitments"], col_i, resp["cells"], resp["proof"]
                        ),
                        "KZG proof for column 0 should verify",
                    )

        self.run_async(_run())

    def test_wrong_node_returns_unavailable(self):
        """Requesting a block that was never dispersed should return MSG_UNAVAILABLE."""
        async def _run():
            block_id = await self.disp.disperse(b"custody boundary test" * 4)
            await asyncio.sleep(0.2)
            
            resp = await self.verifier.fetch_column(
                self.da_infos["da-0"], block_id, 7
            )
            self.assertEqual(resp.get("type"), MSG_UNAVAILABLE)

        self.run_async(_run())

if __name__ == "__main__":
    unittest.main()
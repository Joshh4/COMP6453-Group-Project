"""
Simple integration tests: PeerDAS end-to-end
=============================================
Uses a single shared event loop (setUpClass/tearDownClass) rather
than IsolatedAsyncioTestCase so servers start once and the KZG
context is generated once.  Avoids a Python 3.10 asyncio bug where
per-test event loop teardown causes a C-stack segfault via reprlib.

Run with:
    python -m pytest tests/integration/test_network.py -v
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
N_COLS  = 4
BASE    = 9600


class TestSimpleRoundTrip(unittest.TestCase):
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
        da_info       = NodeInfo("da-0",      "127.0.0.1", BASE)
        disp_info     = NodeInfo("disperser", "127.0.0.1", BASE + 1)
        ver_info      = NodeInfo("verifier",  "127.0.0.1", BASE + 2)

        custody       = {"da-0": set(range(N_COLS))}
        cls.registry  = SubnetRegistry([da_info], custody)
        cls.da_info   = da_info

        cls.da        = DANode(da_info, set(range(N_COLS)))
        cls.disp      = Disperser(disp_info, cls.registry,
                                  n_blobs=N_BLOBS, n_cols=N_COLS)
        cls.verifier  = Verifier(ver_info)
        cls.kzg       = _get_kzg_ctx(N_BLOBS, N_COLS)

        cls._tasks = [
            asyncio.create_task(cls.da.start()),
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

    def test_01_disperse_and_verify_one_column(self):
        """Happy path: disperse a block and verify column 0."""
        async def _run():
            block_id = await self.disp.disperse(b"simple integration test" * 4)
            await asyncio.sleep(0.2)

            self.assertIn(block_id, self.da.store,
                          "DA node should have stored the block")

            resp = await self.verifier.fetch_column(self.da_info, block_id, 0)
            self.assertIsNotNone(resp)
            self.assertEqual(resp.get("type"), MSG_SAMPLE_RESP)
            self.assertTrue(
                self.kzg.verify_column(
                    resp["commitments"], 0, resp["cells"], resp["proof"]
                ),
                "KZG proof for column 0 should verify",
            )

        self.run_async(_run())

    def test_02_all_columns_verify(self):
        """All N_COLS columns should have valid KZG proofs after dispersal."""
        async def _run():
            block_id = await self.disp.disperse(b"all columns test" * 4)
            await asyncio.sleep(0.2)

            for col_idx in range(N_COLS):
                resp = await self.verifier.fetch_column(
                    self.da_info, block_id, col_idx
                )
                self.assertIsNotNone(resp, f"no response for col {col_idx}")
                self.assertEqual(resp["type"], MSG_SAMPLE_RESP)
                self.assertTrue(
                    self.kzg.verify_column(
                        resp["commitments"], col_idx,
                        resp["cells"], resp["proof"],
                    ),
                    f"KZG proof failed for col {col_idx}",
                )

        self.run_async(_run())

    def test_03_tampered_cell_fails_verification(self):
        """Flipping a byte in a cell 
        should cause verify_column to return False."""
        async def _run():
            block_id = await self.disp.disperse(b"tamper test data" * 4)
            await asyncio.sleep(0.2)

            resp = await self.verifier.fetch_column(self.da_info, block_id, 0)
            self.assertIsNotNone(resp)

            tampered       = [list(cell) for cell in resp["cells"]]
            tampered[0][0] = (tampered[0][0] + 1) % 256

            self.assertFalse(
                self.kzg.verify_column(
                    resp["commitments"], 0, tampered, resp["proof"]
                ),
                "Tampered cell should fail KZG verification",
            )

        self.run_async(_run())

    def test_04_two_blocks_are_independent(self):
        """
        Two blocks dispersed to the same network have different commitments.
        Uses n_cols=8 (k=4) so KZG commits to 4 bytes per blob, giving
        enough resolution to distinguish different inputs.
        """
        N_COLS_8 = 8
        BASE_8   = BASE + 10

        async def _run():
            da_info8   = NodeInfo("da-8",     "127.0.0.1", BASE_8)
            disp_info8 = NodeInfo("disp-8",   "127.0.0.1", BASE_8 + 1)
            ver_info8  = NodeInfo("ver-8",    "127.0.0.1", BASE_8 + 2)

            custody8   = {"da-8": set(range(N_COLS_8))}
            registry8  = SubnetRegistry([da_info8], custody8)
            da8        = DANode(da_info8, set(range(N_COLS_8)))
            disp8      = Disperser(disp_info8, registry8,
                                   n_blobs=N_BLOBS, n_cols=N_COLS_8)
            ver8       = Verifier(ver_info8)
            kzg8       = _get_kzg_ctx(N_BLOBS, N_COLS_8)

            tasks = [
                asyncio.create_task(da8.start()),
                asyncio.create_task(disp8.start()),
                asyncio.create_task(ver8.start()),
            ]
            await asyncio.sleep(0.3)

            id1 = await disp8.disperse(b"AAAA" * 20)
            id2 = await disp8.disperse(b"ZZZZ" * 20)
            await asyncio.sleep(0.2)

            self.assertNotEqual(id1, id2)

            for block_id in (id1, id2):
                resp = await ver8.fetch_column(da_info8, block_id, 0)
                self.assertIsNotNone(resp, f"no response for block {block_id}")
                self.assertTrue(
                    kzg8.verify_column(
                        resp["commitments"], 0,
                        resp["cells"], resp["proof"],
                    ),
                    f"col 0 failed for block {block_id}",
                )

            com1 = da8.store[id1][0].commitments
            com2 = da8.store[id2][0].commitments
            self.assertNotEqual(com1, com2,
                "different blocks should have different commitments")

            for t in tasks:
                t.cancel()
            await asyncio.gather(*tasks, return_exceptions=True)

        self.run_async(_run())

    def test_05_larger_column_size(self):
        """
        Verify all columns with n_cols=16 (k=8).
        Tests that the pipeline works correctly at a larger parameter size.
        Note: slower due to KZG trusted setup for new parameters.
        """
        N_COLS_16 = 16
        BASE_16   = BASE + 20

        async def _run():
            da_info16   = NodeInfo("da-16",   "127.0.0.1", BASE_16)
            disp_info16 = NodeInfo("disp-16", "127.0.0.1", BASE_16 + 1)
            ver_info16  = NodeInfo("ver-16",  "127.0.0.1", BASE_16 + 2)

            custody16  = {"da-16": set(range(N_COLS_16))}
            registry16 = SubnetRegistry([da_info16], custody16)
            da16       = DANode(da_info16, set(range(N_COLS_16)))
            disp16     = Disperser(disp_info16, registry16,
                                   n_blobs=N_BLOBS, n_cols=N_COLS_16)
            ver16      = Verifier(ver_info16)
            kzg16      = _get_kzg_ctx(N_BLOBS, N_COLS_16)

            tasks = [
                asyncio.create_task(da16.start()),
                asyncio.create_task(disp16.start()),
                asyncio.create_task(ver16.start()),
            ]
            await asyncio.sleep(0.3)

            block_id = await disp16.disperse(b"n_cols=16 test data" * 8)
            await asyncio.sleep(0.2)

            self.assertIn(block_id, da16.store,
                          "DA node should have stored the block")

            for col_idx in range(N_COLS_16):
                resp = await ver16.fetch_column(da_info16, block_id, col_idx)
                self.assertIsNotNone(resp, f"no response for col {col_idx}")
                self.assertEqual(resp["type"], MSG_SAMPLE_RESP)
                self.assertTrue(
                    kzg16.verify_column(
                        resp["commitments"], col_idx,
                        resp["cells"], resp["proof"],
                    ),
                    f"KZG proof failed for col {col_idx}",
                )

            for t in tasks:
                t.cancel()
            await asyncio.gather(*tasks, return_exceptions=True)

        self.run_async(_run())

    def test_06_missing_block_returns_unavailable(self):
        """Requesting a block that was never dispersed 
        should return MSG_UNAVAILABLE."""
        async def _run():
            resp = await self.verifier.fetch_column(
                self.da_info, "nonexistentblock123", 0
            )
            self.assertIsNotNone(resp)
            self.assertEqual(resp.get("type"), MSG_UNAVAILABLE)

        self.run_async(_run())


if __name__ == "__main__":
    unittest.main()
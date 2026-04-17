"""
kzg_context.py
==============
Adapter that bridges peerdas_network.py and sampler.py to the
KZG implementation in src/commitments/KZG.py.

kzg.py is completely untouched — all integration logic lives here.

Adjust the import path below if your Python path is set up so that
KZG.py is importable under a different name (e.g. just `from kzg
import ...` if you run from the project root with src/ on the path).
"""

import json

from py_ecc.bls12_381 import G1, Z1

from src.commitments.KZG import (
    FIELD_PRIME,
    KZGSetup,
    RootsOfUnity,
    CCfull,
)


class KZGContext:
    """
    High-level wrapper used by peerdas_network.py and sampler.py.

    Design decisions for the prototype
    -----------------------------------
    D=1 (one field element per cell):
        The GF(256) RS encoder produces one byte per cell, so we
        match that granularity.  Changing D later only affects this
        class; the rest of the network layer is unaffected.

    Rate-1/2 polynomial:
        We commit to the first k = n_cols//2 systematic bytes of each
        blob (the message).  The polynomial extended over n_cols domain
        points gives n_cols KZG-evaluated cells, providing the same
        erasure-coding guarantee as the RS step.

    Shared SRS across encode and verify:
        The trusted setup must be the same object in both roles.
        Use _get_kzg_ctx() in network.py rather than constructing a
        new KZGContext in the verifier.  A real deployment would load
        a pre-computed ceremony file instead.

    Wire format:
        G1 points are serialised as "x_hex:y_hex" strings so they
        survive JSON round-trips over the TCP wire.  A per-column
        proof bundle (one G1 per blob row) is JSON-encoded as a list.
    """

    # 7 is a generator of (Z/pZ)* for BLS12-381; any power-of-2
    # sub-domain is reachable via omega = 7^((p-1)/m) mod p.
    _FIELD_GENERATOR = 7

    def __init__(
        self,
        n_blobs: int,
        n_cols: int,
        D: int = 1,  # 1 field element per cell for the byte prototype
        srs: object = None,  # pass an existing SRS to share the trusted setup
    ):
        self.n_blobs = n_blobs
        self.n_cols = n_cols
        self.D = D
        self.k = n_cols // 2  # systematic cells per blob (rate-1/2)

        # Domain size must be a power of 2.
        m = n_cols * D
        if m & (m - 1):
            raise ValueError(f"n_cols * D = {m} must be a power of 2")

        omega = pow(self._FIELD_GENERATOR, (FIELD_PRIME - 1) // m, FIELD_PRIME)
        self.domain = RootsOfUnity(omega, m)

        if srs is None:
            srs = KZGSetup.generate(max_degree=m - 1, D=D)
        self.srs = srs

        self.ccfull = CCfull(
            self.srs,
            self.domain,
            ell=n_blobs,
            D=D,
            k=self.k,
            n=n_cols,
        )

    # ------------------------------------------------------------------
    # Called by Disperser / _rs_encode_matrix
    # ------------------------------------------------------------------

    def commit_matrix(self, rs_matrix: list):
        """
        Commit to every blob row and return hex commitments + states.

        rs_matrix : list[list[list[int]]]
            matrix[blob_idx][col_idx] = [byte_val]
            (one-element cell list, matching the GF-256 RS output)

        Returns
        -------
        commitments_hex : list[str]
            One hex-encoded G1 point per blob.
        states : list
            Opaque Polynomial objects — pass straight to open_column().
        kzg_matrix : list[list[list[int]]]
            KZG-evaluated cells for every column.  Use this as the
            matrix that gets stored and served instead of the RS cells
            so that verify_column() is always consistent.
        """
        # k systematic field elements per blob (D=1, so one int per cell).
        blobs = [[row[c][0] for c in range(self.k)] for row in rs_matrix]

        commitments_g1, states = self.ccfull.commit(blobs)
        commitments_hex = [self._g1_to_hex(c) for c in commitments_g1]

        # Re-evaluate the polynomial at every column so stored cells
        # match what verify_column() expects.
        kzg_matrix = [[] for _ in range(self.n_blobs)]
        for col_idx in range(self.n_cols):
            cells_per_blob, _ = self.ccfull.open(states, col_idx)
            for b in range(self.n_blobs):
                kzg_matrix[b].append(cells_per_blob[b])

        return commitments_hex, states, kzg_matrix

    def open_column(self, states: list, col_index: int):
        """
        Build a KZG multiproof for col_index.

        Returns
        -------
        cells     : list[list[int]]  one D-element cell per blob
        proof_hex : str              JSON list of hex G1 proofs
        """
        cells_per_blob, proofs_g1 = self.ccfull.open(states, col_index)
        proof_hex = json.dumps([self._g1_to_hex(p) for p in proofs_g1])
        return cells_per_blob, proof_hex

    # ------------------------------------------------------------------
    # Called by Verifier / Sampler
    # ------------------------------------------------------------------

    def verify_column(
        self,
        commitments_hex: list,  # list[str]       -- one per blob
        col_index: int,
        cells: list,  # list[list[int]] -- one cell per blob
        proof_hex: str,  # JSON list of hex G1 proofs
    ) -> bool:
        """
        Verify that the cells for col_index are consistent with the
        KZG commitments.  Returns True iff every row's proof passes.
        """
        commitments_g1 = [self._hex_to_g1(h) for h in commitments_hex]
        proofs_g1 = [self._hex_to_g1(h) for h in json.loads(proof_hex)]
        return self.ccfull.verify_column(
            commitments_g1, col_index, cells, proofs_g1
        )

    # ------------------------------------------------------------------
    # Serialisation helpers (G1 affine <-> hex string)
    # ------------------------------------------------------------------

    @staticmethod
    def _g1_to_hex(point) -> str:
        """Serialise a py_ecc G1 affine point to a JSON-safe string."""
        if point is None:  # py_ecc represents infinity as None
            return "inf"
        try:
            x, y = point
            return f"{x.n:064x}:{y.n:064x}"
        except (TypeError, ValueError):
            return "inf"

    @staticmethod
    def _hex_to_g1(h: str):
        """Deserialise a hex string back to a py_ecc G1 affine point."""
        if h == "inf":
            return Z1
        xh, yh = h.split(":")
        FQ_cls = type(G1[0])  # avoids a fragile direct import of FQ
        return (FQ_cls(int(xh, 16)), FQ_cls(int(yh, 16)))

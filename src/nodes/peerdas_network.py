#!/usr/bin/env python3
"""
PeerDAS - Networking Layer
==========================
Adapted from CONDA networking for PeerDAS (Ethereum EIP-7594).

What changed from the CONDA version?
--------------------------------------
  CONDA    : one unique symbol per node, Merkle proof per symbol.
  PeerDAS  : data arranged as a blob matrix (rows = blobs,
             cols = columns).  Each DA node custodies a SUBSET
             of columns (its "custody subnet").  Multiple nodes
             hold the same column -- this is the committee model
             that makes PeerDAS scale.  Proofs are KZG multiproofs
             rather than Merkle proofs.

Encoding status
---------------
  Two separate teammate modules feed into _encode_matrix():

  rs.py / block.py  [COMMITTED -- integrated below]
      Real Reed-Solomon encoding over GF(256).
      _rs_encode_matrix() uses these to produce a genuine blob
      matrix from the raw block data.

      Limitation: GF(256) operates on individual bytes, not the
      large field elements (32 bytes each) that Ethereum's BLS12-381
      curve requires.  For a demo / prototype this is fine.  When
      the full KZG module lands, the field will change but the
      matrix shape and commitment interface stay the same.

  kzg.py  [NOT YET COMMITTED -- stubs remain]
      _stub_kzg_commit()  : returns a SHA-256 hex string instead
                            of a real KZG commitment.
      _stub_kzg_multiproof(): returns a SHA-256 hex string instead
                              of a real KZG multiproof.
      Both are clearly marked with SWAP comments.

  _encode_matrix() is the single call site that ties everything
  together.  Once kzg.py is committed only that function changes --
  the rest of the network layer is unaffected.

Three roles
-----------
  Disperser : encodes the block into a blob matrix, computes KZG
              commitments (one per blob/row) and KZG multiproofs
              (one per column), then sends each column to every
              node that custodies it.

  DANode    : stores only the columns it is assigned to custody.
              Serves column data + KZG proof on request.

  Verifier  : thin network layer only -- no sampling logic here.
              Sampling decisions live in sampler.py.

Subnet / committee model
------------------------
  In Ethereum's PeerDAS spec each node custodies at least
  CUSTODY_REQUIREMENT column subnets (default >= 2 of 128).
  Here custody_columns is a set[int] given at node creation.
  SubnetRegistry maps col_index -> list[NodeInfo].

Plug-in point for kzg.py
--------------------------
  Replace _stub_kzg_commit() and _stub_kzg_multiproof() inside
  _encode_matrix() once kzg.py is committed:

      from src.commitments import kzg
      # one commitment per blob
      commitment = kzg.commit(blob_poly)
      # one multiproof per column (covers all blobs at that col)
      proof = kzg.multiproof(matrix, col_idx)
"""

import asyncio
import hashlib
import json
import logging
import random
from dataclasses import dataclass
from typing import Optional

# RS encoder (teammate's module -- committed).
# Import guard: fall back to None so the file is still importable
# in environments where the module path isn't set up yet.
try:
    from block import Block
    from rs import RS
    _RS_AVAILABLE = True
except ImportError:
    _RS_AVAILABLE = False

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(name)s] %(message)s",
)


# =============================================================================
# PeerDAS parameters  (Ethereum mainnet values as defaults)
# =============================================================================

# Total columns in the blob matrix.  128 in Ethereum mainnet.
N_COLS_DEFAULT = 8    # small value for demo; use 128 for spec

# Number of blobs (rows) per block.  Grows over time in Ethereum.
N_BLOBS_DEFAULT = 4


# =============================================================================
# Message types
# =============================================================================

# disperser -> DA node: here is your column
MSG_COLUMN = "COLUMN"

# verifier -> DA node: send me column j
MSG_SAMPLE_REQ = "SAMPLE_REQ"

# DA node -> verifier: here is column j + proof
MSG_SAMPLE_RESP = "SAMPLE_RESP"

# DA node -> verifier: I don't have that column
MSG_UNAVAILABLE = "UNAVAILABLE"


# =============================================================================
# Data classes
# =============================================================================


@dataclass
class Column:
    """
    Everything a DA node stores for one column of one block.

    block_id    : short hex ID of the original block
    col_index   : which column this is (0-based)
    n_cols      : total columns in the matrix
    cells       : cells[blob_idx] = one cell (list[int]) at this
                  column position for that blob
    commitments : one KZG commitment (hex str) per blob/row;
                  the same list appears on every node for a block
    proof       : KZG multiproof (hex str) covering all cells in
                  this column across all blobs
    """

    block_id:    str
    col_index:   int
    n_cols:      int
    cells:       list  # list[list[int]] -- one cell per blob
    commitments: list  # list[str]       -- one KZG com per blob
    proof:       str   # KZG multiproof for this column (hex)


@dataclass
class NodeInfo:
    """Network address of a node."""

    node_id: str
    host:    str
    port:    int


# =============================================================================
# Subnet registry
# =============================================================================


class SubnetRegistry:
    """
    Maps column indices to the DA nodes responsible for them.

    In Ethereum's PeerDAS spec nodes self-select which columns to
    custody and advertise this via the discovery layer.  Here we
    use a static assignment: custody_columns is given to each
    DANode at creation and the registry is built by scanning all
    nodes.

    Usage:
        registry = SubnetRegistry(da_node_infos, custody_map)
        subnet   = registry.nodes_for_column(col_idx)
    """

    def __init__(
        self,
        node_infos: list,   # list[NodeInfo]
        custody_map: dict,  # node_id -> set[int] of col indices
    ):
        # col_index -> list[NodeInfo]
        self._subnets: dict[int, list] = {}
        for info in node_infos:
            for col in custody_map.get(info.node_id, set()):
                self._subnets.setdefault(col, []).append(info)

    def nodes_for_column(self, col_idx: int) -> list:
        """Return all NodeInfo objects that custody col_idx."""
        return self._subnets.get(col_idx, [])

    def all_columns(self) -> list:
        """Return every column that has at least one custodian."""
        return list(self._subnets.keys())


# =============================================================================
# Wire format helpers
# =============================================================================


def encode_msg(msg_type: str, payload: dict) -> bytes:
    """Pack a message into a single line of JSON bytes."""
    frame = {"type": msg_type, **payload}
    return (json.dumps(frame) + "\n").encode()


def decode_msg(raw: bytes) -> dict:
    """Unpack a received line of JSON bytes into a Python dict."""
    return json.loads(raw.decode().strip())


# =============================================================================
# BaseNode -- shared networking plumbing
# =============================================================================


class BaseNode:
    """
    The networking foundation that all three node types build on.

    Starts a TCP server that listens for incoming connections and
    calls handle_message() for each message it receives.  Also
    provides send() for making outbound requests to other nodes.

    Uses asyncio so one Python process handles many connections at
    once without threads -- while waiting for a reply, other tasks
    continue to run.
    """

    def __init__(self, info: NodeInfo):
        self.info = info
        self.logger = logging.getLogger(
            f"{self.__class__.__name__}({info.node_id})"
        )
        self._server: Optional[asyncio.Server] = None

    async def start(self):
        """Bind to our host:port and start accepting connections."""
        self._server = await asyncio.start_server(
            self._handle_connection,
            self.info.host,
            self.info.port,
        )
        self.logger.info(
            f"Listening on {self.info.host}:{self.info.port}"
        )
        async with self._server:
            await self._server.serve_forever()

    async def _handle_connection(
        self,
        reader: asyncio.StreamReader,
        writer: asyncio.StreamWriter,
    ):
        """
        Called automatically for each new TCP connection.
        Reads one JSON message at a time, passes it to
        handle_message(), and writes back any reply.
        """
        try:
            while True:
                raw = await reader.readline()
                if not raw:
                    break
                msg      = decode_msg(raw)
                response = await self.handle_message(msg)
                if response is not None:
                    writer.write(response)
                    await writer.drain()
        except (asyncio.IncompleteReadError, ConnectionResetError):
            pass
        finally:
            writer.close()

    async def handle_message(self, msg: dict) -> Optional[bytes]:
        """Subclasses override this to handle incoming messages."""
        raise NotImplementedError

    async def send(
        self,
        target: NodeInfo,
        msg_type: str,
        payload: dict,
        wait_for_reply: bool = True,
    ) -> Optional[dict]:
        """
        Open a TCP connection to target, send one message, and
        optionally wait for a reply.

        Set wait_for_reply=False for fire-and-forget messages where
        no reply is expected (e.g. sending a column to a DA node).
        """
        try:
            reader, writer = await asyncio.open_connection(
                target.host, target.port
            )
            writer.write(encode_msg(msg_type, payload))
            await writer.drain()

            result = None
            if wait_for_reply:
                raw = await asyncio.wait_for(
                    reader.readline(), timeout=5.0
                )
                if raw:
                    result = decode_msg(raw)

            writer.close()
            await writer.wait_closed()
            return result

        except (ConnectionRefusedError, asyncio.TimeoutError) as e:
            self.logger.warning(
                f"Could not reach {target.node_id}: {e}"
            )
            return None


# =============================================================================
# Disperser
# =============================================================================


class Disperser(BaseNode):
    """
    The block proposer's agent.  Encodes the block into a blob
    matrix and sends each column to every DA node that custodies it.

    Steps:
      1. Encode block_data into an n_blobs x n_cols matrix of cells
         with one KZG commitment per blob and one KZG multiproof per
         column.  RS encoding is real; KZG is still stubbed.
      2. For each column, look up its subnet in the registry and
         send the column payload to every node in that subnet.
    """

    def __init__(
        self,
        info: NodeInfo,
        registry: SubnetRegistry,
        n_blobs: int = N_BLOBS_DEFAULT,
        n_cols:  int = N_COLS_DEFAULT,
    ):
        super().__init__(info)
        self.registry = registry
        self.n_blobs  = n_blobs
        self.n_cols   = n_cols

    async def handle_message(self, msg: dict) -> Optional[bytes]:
        return None  # disperser only sends; it never receives

    async def disperse(self, block_data: bytes) -> str:
        """
        Encode block_data and deliver each column to its subnet.
        Returns block_id so verifiers know what to ask for.
        """
        block_id = hashlib.sha256(block_data).hexdigest()[:12]
        self.logger.info(
            f"Dispersing block {block_id} "
            f"({self.n_blobs} blobs x {self.n_cols} cols)"
        )

        matrix, commitments, col_proofs = _encode_matrix(
            block_data, self.n_blobs, self.n_cols
        )

        # Send each column to every node in its subnet (committee).
        # Multiple nodes hold the same column -- intentional.
        # If one custodian is offline, others can still serve it.
        tasks = []
        for col_idx in range(self.n_cols):
            col_cells = [
                matrix[b][col_idx] for b in range(self.n_blobs)
            ]
            payload = {
                "block_id":    block_id,
                "col_index":   col_idx,
                "n_cols":      self.n_cols,
                "cells":       col_cells,
                "commitments": commitments,
                "proof":       col_proofs[col_idx],
            }
            subnet = self.registry.nodes_for_column(col_idx)
            if not subnet:
                self.logger.warning(
                    f"No nodes custody col {col_idx}"
                    " -- column will be lost"
                )
            for node in subnet:
                tasks.append(
                    self.send(
                        node,
                        MSG_COLUMN,
                        payload,
                        wait_for_reply=False,
                    )
                )

        await asyncio.gather(*tasks)
        self.logger.info(f"Block {block_id} dispersed")
        return block_id


# =============================================================================
# DANode
# =============================================================================


class DANode(BaseNode):
    """
    A storage node that custodies a fixed subset of columns.

    Nodes only store columns assigned to their custody set.  If the
    disperser mistakenly sends a column outside that set (shouldn't
    happen with a correct registry), it is discarded with a warning.

    store[block_id][col_index] = Column
    """

    def __init__(self, info: NodeInfo, custody_columns: set):
        super().__init__(info)
        self.custody_columns = custody_columns
        # Nested dict so a node can hold multiple blocks at once.
        self.store: dict[str, dict[int, Column]] = {}

    async def handle_message(self, msg: dict) -> Optional[bytes]:
        t = msg.get("type")

        if t == MSG_COLUMN:
            return await self._handle_column(msg)

        if t == MSG_SAMPLE_REQ:
            return self._handle_sample_req(msg)

        self.logger.warning(f"Unknown message type: {t}")
        return None

    async def _handle_column(self, msg: dict) -> None:
        """Store a column if it falls within our custody set."""
        col_idx = msg["col_index"]
        if col_idx not in self.custody_columns:
            self.logger.warning(
                f"Received col {col_idx} outside custody"
                " -- discarding"
            )
            return None

        col = Column(
            block_id=    msg["block_id"],
            col_index=   col_idx,
            n_cols=      msg["n_cols"],
            cells=       msg["cells"],
            commitments= msg["commitments"],
            proof=       msg["proof"],
        )
        self.store.setdefault(col.block_id, {})[col_idx] = col
        self.logger.info(
            f"Stored col {col_idx} for block {col.block_id}"
        )
        return None

    def _handle_sample_req(self, msg: dict) -> bytes:
        """Return the column if we have it, else MSG_UNAVAILABLE."""
        block_id = msg["block_id"]
        col_idx  = msg["col_index"]
        col      = self.store.get(block_id, {}).get(col_idx)

        if col is None:
            return encode_msg(MSG_UNAVAILABLE, {
                "block_id":  block_id,
                "col_index": col_idx,
            })

        return encode_msg(MSG_SAMPLE_RESP, {
            "block_id":    col.block_id,
            "col_index":   col.col_index,
            "cells":       col.cells,
            "commitments": col.commitments,
            "proof":       col.proof,
        })


# =============================================================================
# Verifier  (thin network layer -- sampling logic lives in sampler.py)
# =============================================================================


class Verifier(BaseNode):
    """
    Network interface for a light client (verifier).

    Only handles the TCP mechanics of sending a sample request and
    receiving the raw response.  All decisions about which columns
    to sample, which node to ask, and how to interpret results are
    in sampler.py so they can be tested independently.
    """

    async def handle_message(self, msg: dict) -> Optional[bytes]:
        return None  # verifiers never serve data

    async def fetch_column(
        self,
        target: NodeInfo,
        block_id: str,
        col_idx: int,
    ) -> Optional[dict]:
        """
        Ask `target` for column `col_idx` of block `block_id`.
        Returns the raw response dict, or None on failure.
        """
        return await self.send(
            target,
            MSG_SAMPLE_REQ,
            {"block_id": block_id, "col_index": col_idx},
        )


# =============================================================================
# Encoding  (single call site -- swap KZG stubs here when ready)
# =============================================================================


def _encode_matrix(
    data: bytes,
    n_blobs: int,
    n_cols: int,
):
    """
    Build the blob matrix, KZG commitments, and KZG multiproofs.

    RS encoding is real (uses teammate's rs.py / block.py).
    KZG commitment and multiproof are still stubbed (SHA-256 hex)
    until kzg.py is committed.

    How the RS encoder maps onto PeerDAS:
      - Split block_data into n_blobs equal blobs.
      - Each blob is treated as a message of k = n_cols/2 bytes
        (rate-1/2 code, same as PeerDAS spec).
      - RS(k, n_cols) expands each blob to n_cols symbols.
      - Each symbol (one byte in GF(256)) becomes one cell.
        In the full Ethereum implementation, a cell holds 64
        BLS12-381 field elements (32 bytes each); the GF(256)
        field is a prototype stand-in.
      - matrix[blob_idx][col_idx] = [symbol_byte] (list of 1 int
        for now; will be list of 64 ints once the field changes).

    Once kzg.py is committed, replace the two stub calls:
      # commitment per blob
      commitments[b] = kzg.commit(blob_polynomial)
      # multiproof per column (covers all blobs at that column)
      col_proofs[c]  = kzg.multiproof(matrix, c)

    Returns: (matrix, commitments, col_proofs)
      matrix      : list[list[list[int]]]
      commitments : list[str]  (hex, one per blob)
      col_proofs  : list[str]  (hex, one per column)
    """
    if _RS_AVAILABLE:
        return _rs_encode_matrix(data, n_blobs, n_cols)
    # Fallback: rs.py not importable in this environment.
    return _byte_split_matrix(data, n_blobs, n_cols)


def _rs_encode_matrix(
    data: bytes,
    n_blobs: int,
    n_cols: int,
):
    """
    Real RS encoding using teammate's RS class.

    Each blob is independently RS-encoded at rate 1/2:
      k = n_cols // 2  message bytes -> n_cols coded bytes.
    The n_cols coded bytes become the n_cols cells of that row.

    Constraint from the RS class: n < 256 (GF(256) field order).
    n_cols must therefore be <= 255.  128 (Ethereum spec) is fine.
    """
    if n_cols >= 256:
        raise ValueError(
            f"n_cols must be < 256 for GF(256) RS; got {n_cols}"
        )

    # k = half the columns (rate-1/2 matches PeerDAS spec).
    k = n_cols // 2
    rs = RS(k, n_cols)

    # Split raw data evenly across blobs, padding the last one.
    blob_size = max(1, len(data) // n_blobs)
    raw_blobs = [
        data[b * blob_size : (b + 1) * blob_size]
        for b in range(n_blobs)
    ]

    matrix      = []
    commitments = []

    for b, raw in enumerate(raw_blobs):
        # Pad or truncate blob to exactly k bytes so RS(k, n) works.
        # Real Ethereum pads at the field-element level; bytes here.
        padded = (raw + bytes(k))[:k]
        block  = Block(padded, k)
        enc    = rs.encode(block)

        # Each encoded byte is one cell at this row.
        # Wrap in a list to match the interface: cell = list[int].
        row = [[b_val] for b_val in enc.data()]
        matrix.append(row)

        # ------------------------------------------------------------------
        # SWAP for real KZG once kzg.py is committed:
        #   from src.commitments import kzg
        #   commitments.append(kzg.commit(padded))
        commitments.append(
            _stub_kzg_commit(padded)
        )
        # ------------------------------------------------------------------

    # Build one multiproof per column (stub for now).
    col_proofs = []
    for c in range(n_cols):
        col_bytes = bytes(
            matrix[b][c][0] for b in range(n_blobs)
        )
        # ------------------------------------------------------------------
        # SWAP for real KZG once kzg.py is committed:
        #   col_proofs.append(kzg.multiproof(matrix, c))
        col_proofs.append(
            _stub_kzg_multiproof(col_bytes)
        )
        # ------------------------------------------------------------------

    return matrix, commitments, col_proofs


def _byte_split_matrix(
    data: bytes,
    n_blobs: int,
    n_cols: int,
):
    """
    Fallback when rs.py is not importable.
    Simple byte-split with no real RS redundancy.
    Matches the same output shape as _rs_encode_matrix().
    """
    total = n_blobs * n_cols
    chunk = max(1, len(data) // total)
    flat  = [
        [data[i * chunk]] if i * chunk < len(data) else [0]
        for i in range(total)
    ]

    matrix = [
        [flat[b * n_cols + c] for c in range(n_cols)]
        for b in range(n_blobs)
    ]

    commitments = [
        _stub_kzg_commit(
            bytes(matrix[b][c][0] for c in range(n_cols))
        )
        for b in range(n_blobs)
    ]
    col_proofs = [
        _stub_kzg_multiproof(
            bytes(matrix[b][c][0] for b in range(n_blobs))
        )
        for c in range(n_cols)
    ]
    return matrix, commitments, col_proofs


# =============================================================================
# KZG stubs  [replace when kzg.py is committed]
# =============================================================================


def _stub_kzg_commit(blob_bytes: bytes) -> str:
    """
    Stub for kzg.commit(blob_polynomial).

    Returns SHA-256 of the blob bytes as a hex string.
    Replace with:
        from src.commitments import kzg
        return kzg.commit(blob_polynomial)
    """
    return hashlib.sha256(blob_bytes).hexdigest()


def _stub_kzg_multiproof(col_bytes: bytes) -> str:
    """
    Stub for kzg.multiproof(matrix, col_idx).

    Returns SHA-256 of the column bytes as a hex string.
    Replace with:
        from src.commitments import kzg
        return kzg.multiproof(matrix, col_idx)
    """
    return hashlib.sha256(col_bytes).hexdigest()


def _stub_kzg_verify(
    commitments: list,  # list[str] -- one per blob
    col_idx: int,
    cells: list,        # list[list[int]] -- one cell per blob
    proof: str,         # KZG multiproof (hex str)
) -> bool:
    """
    Stub for kzg.verify_multiproof().

    Always returns True so the demo runs without real KZG.
    Replace with:
        from src.commitments import kzg
        return kzg.verify_multiproof(
            commitments, col_idx, cells, proof)
    """
    return True


# =============================================================================
# Demo
# =============================================================================


async def demo():
    """
    End-to-end PeerDAS demo running in a single process.

    8 DA nodes each custody 2 columns.  The disperser RS-encodes
    the block (real encoding if rs.py is available, byte-split
    fallback otherwise).  The verifier samples 4 random columns
    and checks KZG proofs (stubbed -- always passes).
    """
    N_DA   = 8
    N_COLS = N_COLS_DEFAULT
    N_BLOB = N_BLOBS_DEFAULT
    BASE   = 9100

    da_infos = [
        NodeInfo(f"da-{j}", "127.0.0.1", BASE + j)
        for j in range(N_DA)
    ]

    # Assign two columns to each node (round-robin wrap-around).
    # In Ethereum, nodes self-advertise their custody choices.
    custody_map = {
        f"da-{j}": {j % N_COLS, (j + 1) % N_COLS}
        for j in range(N_DA)
    }

    registry = SubnetRegistry(da_infos, custody_map)

    disperser_info = NodeInfo(
        "disperser", "127.0.0.1", BASE + N_DA
    )
    verifier_info  = NodeInfo(
        "verifier", "127.0.0.1", BASE + N_DA + 1
    )

    da_nodes  = [
        DANode(info, custody_map[info.node_id])
        for info in da_infos
    ]
    disperser = Disperser(
        disperser_info, registry, N_BLOB, N_COLS
    )
    verifier  = Verifier(verifier_info)

    all_nodes = da_nodes + [disperser, verifier]
    servers   = [
        asyncio.create_task(n.start()) for n in all_nodes
    ]

    await asyncio.sleep(0.3)

    enc_label = "RS" if _RS_AVAILABLE else "byte-split (fallback)"
    print(f"Encoding mode: {enc_label}")

    block_data = b"PeerDAS block data demo." * 8
    block_id   = await disperser.disperse(block_data)

    await asyncio.sleep(0.2)

    # Sample 4 random columns.  Full sampling logic is in sampler.py;
    # this inline version keeps the demo self-contained.
    sample_cols = random.sample(range(N_COLS), 4)
    print(f"\nSampling columns: {sample_cols}")
    success = 0
    for col_idx in sample_cols:
        subnet = registry.nodes_for_column(col_idx)
        if not subnet:
            print(f"  col {col_idx}: no custodians")
            continue
        node  = random.choice(subnet)
        resp  = await verifier.fetch_column(
            node, block_id, col_idx
        )
        if resp and resp.get("type") == MSG_SAMPLE_RESP:
            valid = _stub_kzg_verify(
                resp["commitments"],
                col_idx,
                resp["cells"],
                resp["proof"],
            )
            label = "OK" if valid else "FAIL"
            print(f"  col {col_idx} ({node.node_id}): {label}")
            if valid:
                success += 1
        else:
            print(f"  col {col_idx}: unavailable")

    total = len(sample_cols)
    print(
        f"\n{success}/{total} columns verified -- "
        f"block available: {success == total}"
    )

    for s in servers:
        s.cancel()


if __name__ == "__main__":
    asyncio.run(demo())
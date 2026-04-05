#!/usr/bin/env python3
"""
CONDA DAS - Networking Layer
============================
From the paper: "Data Availability for Thousands of Nodes"
              Guo, Qu, Xiong, Zhang -- NUS (2025)

What problem does this solve?
------------------------------
When a new block is proposed on a blockchain, every participant needs to be
confident that the block's data is actually available -- i.e. the proposer
hasn't secretly withheld part of it. But downloading the whole block just to
check is too expensive, especially for phones or light clients.

CONDA's solution:
  1. The block is erasure-coded into n pieces called "symbols", one per node.
     Erasure coding means you only need k of the n symbols to reconstruct
     the full block (k < n), so even if some nodes are offline it's still
     recoverable.
  2. A cryptographic commitment is made to the whole block and shared with
     everyone.
  3. Each node gets its own unique symbol plus a proof that the symbol is
     genuine.
  4. Verifiers (light clients) ask a random subset of nodes for their symbols,
     check the proofs, and if enough pass they know the block is available.

The three roles
---------------
  Disperser : the block proposer. Encodes the block, creates the commitment,
              and sends each node its unique symbol + proof.

  DANode    : a storage node. Holds one symbol for each block it has received,
              and hands it out when asked.

  Verifier  : a light client. Asks some random nodes for their symbols, checks
              the proofs, and decides whether the block is available.

--------------
Each DA node gets exactly one unique symbol. There is no grouping or
replication at the network level -- the erasure code itself provides
redundancy. This is different from committee-based designs (like PeerDAS)
and is what makes CONDA scale to thousands of nodes efficiently.

Plug-in points for teammates
-----------------------------
  erasure_coding.py  ->  replace _stub_encode()      [NOT YET INTEGRATED]
                         Must return: (symbols, chunks)
                           symbols : list[list[int]]  one per DA node
                           chunks  : list[bytes]       one bytes object per
                                     node, used to build the Merkle tree.
                                     With a plain byte-split this is just
                                     bytes(symbol) for each symbol, but a
                                     Reed-Solomon encoding may produce
                                     different column bytes -- your teammate
                                     decides.

Commitment scheme (MerkleTree -- already integrated)
----------------------------------------------------
  _stub_encode() still returns raw byte-slices of the block (unchanged).
  Those slices are passed as chunks to MerkleTree so the commitment and
  proofs are real cryptographic Merkle proofs rather than fake SHA-256
  hashes.

  disperser side:
    symbols, chunks = _stub_encode(block_data, n)
    tree            = MerkleTree(chunks)
    commitment      = tree.get_root().hex()   # broadcast as a hex string
    proof[j]        = proof_to_json(tree.get_proof(j))

  verifier side:
    chunk = bytes(symbol.data)                # reconstruct the bytes chunk
    root  = bytes.fromhex(resp["commitment"])
    proof = proof_from_json(resp["proof"])
    valid = MerkleTree.verify_proof(chunk, proof, root)

JSON serialisation bridge
-------------------------
  Merkle proofs are List[Tuple[bytes, str]] and cannot travel over JSON
  directly.
  proof_to_json()   encodes each sibling hash as a hex string:
                    [[hex, dir], ...]
  proof_from_json() decodes back to List[Tuple[bytes, str]] for
                    verify_proof().
  The commitment (bytes) travels as a hex string via .hex() /
  bytes.fromhex().
"""

import asyncio
import hashlib
import json
import logging
import random
from dataclasses import dataclass
from typing import List, Optional, Tuple

from src.commitments.merkle_tree import MerkleTree

logging.basicConfig(level=logging.INFO, 
                    format="%(asctime)s [%(name)s] %(message)s")


# =============================================================================
# Message types
# =============================================================================

MSG_SYMBOL      = "SYMBOL"
MSG_SAMPLE_REQ  = "SAMPLE_REQ"
MSG_SAMPLE_RESP = "SAMPLE_RESP"
MSG_UNAVAILABLE = "UNAVAILABLE"
MSG_AVAILABLE   = "AVAILABLE"


# =============================================================================
# Data classes
# =============================================================================

@dataclass
class Symbol:
    """
    Everything a DA node stores for one block.

    block_id   : short SHA-256 hex ID of the original block
    index      : which piece this node was assigned (0-based)
    n_total    : total number of pieces
    data       : the symbol content as a list of ints (raw bytes of the chunk)
    commitment : Merkle root as a hex string (same value on every node)
    proof      : JSON-safe Merkle inclusion proof -- list of [hex_str, dir]
    """
    block_id:   str
    index:      int
    n_total:    int
    data:       list    # list[int] -- survives JSON round-trips
    commitment: str     # Merkle root, hex-encoded
    proof:      list    # [[hex_str, "left"|"right"], ...]


@dataclass
class NodeInfo:
    """Network address of a node."""
    node_id: str
    host:    str
    port:    int


# =============================================================================
# Wire format helpers
# =============================================================================

def encode_msg(msg_type: str, payload: dict) -> bytes:
    """Pack a message into a single line of JSON bytes ready to send."""
    frame = {"type": msg_type, **payload}
    return (json.dumps(frame) + "\n").encode()


def decode_msg(raw: bytes) -> dict:
    """Unpack a received line of JSON bytes back into a Python dict."""
    return json.loads(raw.decode().strip())


# =============================================================================
# Proof serialisation helpers
# =============================================================================

def proof_to_json(proof: List[Tuple[bytes, str]]) -> list:
    """
    Convert a MerkleTree proof to a JSON-serialisable list.

    MerkleTree.get_proof() returns List[Tuple[bytes, str]] where the first
    element of each tuple is a raw bytes sibling hash. JSON has no bytes
    type, so we hex-encode each hash.

    Returns: [[hex_str, direction], ...]
    """
    return [[sibling.hex(), direction] for sibling, direction in proof]


def proof_from_json(raw_proof: list) -> List[Tuple[bytes, str]]:
    """
    Reverse of proof_to_json().

    Returns: List[Tuple[bytes, str]] -- ready for MerkleTree.verify_proof().
    """
    return [
        (bytes.fromhex(hex_str), direction)
        for hex_str, direction in raw_proof
    ]


# =============================================================================
# BaseNode -- shared networking plumbing
# =============================================================================

class BaseNode:
    """
    The networking foundation that all three node types build on.

    Starts a TCP server that listens for incoming connections and calls
    handle_message() for each message it receives. Also provides send()
    for making outbound requests to other nodes.

    Uses asyncio so one Python process can handle many connections at once
    without threads -- while waiting for a network reply, other tasks run.
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
            self._handle_connection, self.info.host, self.info.port
        )
        self.logger.info(f"Listening on {self.info.host}:{self.info.port}")
        async with self._server:
            await self._server.serve_forever()

    async def _handle_connection(
        self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter
    ):
        """
        Called automatically each time a new TCP connection arrives.
        Reads one JSON message at a time, passes it to handle_message(),
        and writes back any reply. Cleans up when the connection closes.
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
        """
        Subclasses override this to handle incoming messages.
        Return bytes to send a reply, or None for no reply.
        """
        raise NotImplementedError

    async def send(
        self,
        target: NodeInfo,
        msg_type: str,
        payload: dict,
        wait_for_reply: bool = True,
    ) -> Optional[dict]:
        """
        Open a TCP connection to target, send one message, and optionally
        wait for a reply.

        Set wait_for_reply=False for fire-and-forget messages where no reply
        is expected (e.g. sending a symbol to a DA node).
        """
        try:
            reader, writer = await asyncio.open_connection(
                target.host, target.port
            )
            writer.write(encode_msg(msg_type, payload))
            await writer.drain()

            result = None
            if wait_for_reply:
                raw = await asyncio.wait_for(reader.readline(), timeout=5.0)
                if raw:
                    result = decode_msg(raw)

            writer.close()
            await writer.wait_closed()
            return result

        except (ConnectionRefusedError, asyncio.TimeoutError) as e:
            self.logger.warning(f"Could not reach {target.node_id}: {e}")
            return None


# =============================================================================
# Disperser
# =============================================================================

class Disperser(BaseNode):
    """
    The block proposer's agent. Encodes the block and sends each DA node
    its unique piece.

    Steps:
      1. Erasure-code the block into n symbols (currently a stub).
      2. Build a MerkleTree over the symbol chunks to get a real commitment.
      3. For each node j, get the Merkle proof for chunk j and send everything.
    """

    def __init__(self, info: NodeInfo, da_nodes: list[NodeInfo]):
        super().__init__(info)
        self.da_nodes = da_nodes

    async def handle_message(self, msg: dict) -> Optional[bytes]:
        return None  # disperser only sends; it never receives messages

    async def disperse(self, block_data: bytes) -> str:
        """
        Encode block_data and deliver each symbol to its assigned DA node.
        Returns the block_id so verifiers know what to ask for.
        """
        n        = len(self.da_nodes)
        block_id = hashlib.sha256(block_data).hexdigest()[:12]
        self.logger.info(f"Dispersing block {block_id} to {n} DA nodes")

        # Step 1: encode the block into n symbols.
        # replace with: symbols, chunks = erasure_coding.encode(block_data, n)
        # symbols[j] : list[int]  -- the piece sent to DA node j (JSON-safe)
        # chunks[j]  : bytes      -- the bytes used to build the Merkle tree
        #              (with plain byte-slicing these are identical; a real RS
        #               encoding may produce different column bytes)
        symbols, chunks = _stub_encode(block_data, n)
        # ---------------------------------------------------------------------

        # Step 2: build the Merkle tree over the chunks.
        # The root is the commitment - a cryptographic fingerprint of the whole
        # block that every node and every verifier can use to check their piece
        tree       = MerkleTree(chunks)
        commitment = tree.get_root().hex()  # travels as a hex string over JSON

        # Step 3: for each node, get its Merkle proof and send everything.
        tasks = []
        for j, node in enumerate(self.da_nodes):
            proof = proof_to_json(tree.get_proof(j))

            payload = {
                "block_id":   block_id,
                "index":      j,
                "n_total":    n,
                "data":       symbols[j],
                "commitment": commitment,
                "proof":      proof,
            }
            tasks.append(
                self.send(node, MSG_SYMBOL, payload, wait_for_reply=False)
            )

        await asyncio.gather(*tasks)
        self.logger.info(f"Block {block_id} dispersed")
        return block_id


# =============================================================================
# DANode
# =============================================================================

class DANode(BaseNode):
    """
    A storage node. Holds one unique symbol per block and serves it on
    request.

    DA nodes don't verify what they receive -- they trust the disperser.
    Verifiers are responsible for checking proofs.
    """

    def __init__(self, info: NodeInfo):
        super().__init__(info)
        self.store: dict[str, Symbol] = {}

    async def handle_message(self, msg: dict) -> Optional[bytes]:
        t = msg.get("type")

        if t == MSG_SYMBOL:
            symbol = Symbol(
                block_id=   msg["block_id"],
                index=      msg["index"],
                n_total=    msg["n_total"],
                data=       msg["data"],
                commitment= msg["commitment"],
                proof=      msg["proof"],
            )
            self.store[symbol.block_id] = symbol
            self.logger.info(
                f"Stored symbol {symbol.index}/{symbol.n_total} "
                f"for block {symbol.block_id}"
            )
            return None

        if t == MSG_SAMPLE_REQ:
            block_id = msg["block_id"]
            symbol   = self.store.get(block_id)

            if symbol is None:
                return encode_msg(MSG_UNAVAILABLE, {"block_id": block_id})

            return encode_msg(
                MSG_SAMPLE_RESP,
                {
                    "block_id":   symbol.block_id,
                    "index":      symbol.index,
                    "data":       symbol.data,
                    "commitment": symbol.commitment,
                    "proof":      symbol.proof,
                },
            )

        self.logger.warning(f"Unknown message type: {t}")
        return None


# =============================================================================
# Verifier
# =============================================================================

class Verifier(BaseNode):
    """
    A light client that checks whether a block is available by sampling.

    Picks a random subset of DA nodes, asks each for its symbol, and verifies
    the Merkle proof on each response. All sampled nodes must return a valid
    symbol for the block to be declared available.
    """

    def __init__(
        self,
        info: NodeInfo,
        da_nodes: list[NodeInfo],
        sample_count: int = 0,
    ):
        super().__init__(info)
        self.da_nodes     = da_nodes
        self.sample_count = sample_count if sample_count > 0 else len(da_nodes)

    async def handle_message(self, msg: dict) -> Optional[bytes]:
        return None  # verifiers only make requests; they never serve data

    async def sample(self, block_id: str) -> bool:
        """
        Ask a random set of DA nodes for their symbols and verify each one.
        Returns True if all sampled nodes returned a valid symbol.
        """
        targets = random.sample(self.da_nodes, self.sample_count)
        self.logger.info(
            f"Sampling block {block_id} from {[n.node_id for n in targets]}"
        )

        tasks     = [
            self.send(node, MSG_SAMPLE_REQ, {"block_id": block_id})
            for node in targets
        ]
        responses = await asyncio.gather(*tasks)

        success = 0
        for resp in responses:
            if resp is None:
                self.logger.warning("No response from a DA node")
                continue

            if resp.get("type") == MSG_SAMPLE_RESP:
                # Reconstruct the bytes chunk and Merkle root, then verify.
                chunk = bytes(resp["data"])
                root  = bytes.fromhex(resp["commitment"])
                proof = proof_from_json(resp["proof"])

                valid = MerkleTree.verify_proof(chunk, proof, root)

                if valid:
                    success += 1
                else:
                    self.logger.error(
                        f"Bad Merkle proof for symbol {resp['index']} "
                        f"of block {block_id} -- the node may be dishonest"
                    )
            # MSG_UNAVAILABLE means that node doesn't have the block - failure.

        available = (success == self.sample_count)
        status    = MSG_AVAILABLE if available else MSG_UNAVAILABLE
        self.logger.info(
            f"Block {block_id}: {status} "
            f"({success}/{self.sample_count} symbols verified)"
        )
        return available


# =============================================================================
# Stub erasure encoding  [NOT YET INTEGRATED -- awaiting teammate's module]
# =============================================================================
# Placeholder for erasure_coding.encode(). The real version will use
# Reed-Solomon so that any k of the n symbols can reconstruct the full block.
# This stub simply slices the raw bytes into n equal chunks.
#
# CONTRACT that the real implementation must honour:
#   Input  : block_data (bytes), n (int)
#   Output : (symbols, chunks)
#     symbols : list[list[int]]  -- n symbols, each a list of ints (JSON-safe)
#     chunks  : list[bytes]      -- n byte strings passed to MerkleTree.
#               With plain slicing, chunks[j] == bytes(symbols[j]).
#               A real RS encoding may differ -- that is fine as long as both
#               the disperser and verifier agree on what the chunk bytes are.

def _stub_encode(data: bytes, n: int):
    size    = max(1, len(data) // n)
    symbols = []
    chunks  = []
    for j in range(n):
        raw = data[j * size : (j + 1) * size] or b"\x00"
        symbols.append(list(raw))
        chunks.append(raw)
    return symbols, chunks


# =============================================================================
# Demo
# =============================================================================

async def demo():
    """
    End-to-end demo of the CONDA DA protocol running in a single process.

    8 DA nodes each receive a unique symbol with a real Merkle proof.
    3 verifiers independently sample all 8 nodes and confirm availability
    using MerkleTree.verify_proof().
    """
    N_DA_NODES = 8
    BASE_PORT  = 9000

    da_node_infos = [
        NodeInfo(f"da-{j}", "127.0.0.1", BASE_PORT + j)
        for j in range(N_DA_NODES)
    ]

    port           = BASE_PORT + N_DA_NODES
    disperser_info = NodeInfo("disperser", "127.0.0.1", port)
    port          += 1
    verifier_infos = [
        NodeInfo(f"verifier-{i}", "127.0.0.1", port + i) for i in range(3)
    ]

    da_nodes  = [DANode(info) for info in da_node_infos]
    disperser = Disperser(disperser_info, da_node_infos)
    verifiers = [Verifier(info, da_node_infos) for info in verifier_infos]

    all_nodes    = da_nodes + [disperser] + verifiers
    server_tasks = [asyncio.create_task(node.start()) for node in all_nodes]

    await asyncio.sleep(0.3)

    block_data = b"Hello CONDA! This is example block data for the DA demo" * 4
    block_id   = await disperser.disperse(block_data)

    await asyncio.sleep(0.2)

    results = await asyncio.gather(*[v.sample(block_id) for v in verifiers])
    print(f"\nSampling results: {results}")
    print("All available?", all(results))

    for task in server_tasks:
        task.cancel()


if __name__ == "__main__":
    asyncio.run(demo())
"""
Week 6 – Basic DAS Benchmark Runner

Runs:
1. Proof generation benchmark
2. Light client verification benchmark
3. Detection probability benchmark

Usage:
    python main.py
"""

import random
import secrets

# ====== Import your benchmark modules ======
from bench_proof_gen import benchmark_proof_generation
from bench_verify import benchmark_verification
from bench_detection_probability import benchmark_detection_probability

from utils.random_block import generate_random_block

# =========================================================
# 🔧 ADAPTER SECTION (adjust to your actual implementations)
# =========================================================

# ----- Erasure coding (already implemented by your team) -----
def encode_block(block_bytes):
    """
    Adapter for your erasure coding implementation.
    Must return List[bytes].
    """
    # TODO: replace with your actual encode function
    from erasure import encode   # example
    return encode(block_bytes)


# ----- Merkle Tree implementation -----
class MerkleTree:
    """
    Adapter wrapper for your Merkle tree implementation.
    """

    def __init__(self, chunks):
        # TODO: replace with your Merkle tree class
        from merkle import MerkleTree as MT
        self.tree = MT(chunks)

    def root(self):
        return self.tree.get_root()

    def get_proof(self, index):
        return self.tree.get_proof(index)


# ----- Light client verification -----
def verify_proof(root, chunk, index, proof):
    """
    Adapter for Merkle proof verification.
    """
    # TODO: replace with your verify function
    from merkle import verify
    return verify(root, chunk, index, proof)


# =========================================================
# 🚀 Main Benchmark Pipeline
# =========================================================

def main():
    # -------------------------
    # Reproducibility
    # -------------------------
    random.seed(42)

    # -------------------------
    # Global Parameters
    # -------------------------
    BLOCK_SIZE_BYTES = 512 * 1024        # 512 KB
    NUM_CHUNKS_EXPECTED = 1024           # after erasure coding
    SAMPLE_COUNTS = [5, 10, 20, 40]
    WITHHOLDING_RATIOS = [0.1, 0.2, 0.3]
    REPETITIONS = 20


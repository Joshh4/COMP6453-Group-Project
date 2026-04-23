def generate_deterministic_block(block_size: int, seed: int = 0) -> bytes:
    """
    Reproducible block bytes for benchmarks.

    Uses a short low-entropy cycle (not SHA256 expansion).  High-entropy
    payloads can make ``py_ecc`` pairing final exponentiation recurse until
    Python hits ``RecursionError`` with the versions used here.
    """
    atom = bytes([0x42 ^ (seed & 0xFF), 0x17, 0x5A, 0x00])
    return bytes(atom[i % len(atom)] for i in range(block_size))

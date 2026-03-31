import secrets

def generate_random_block(block_size: int) -> bytes:
    return secrets.token_bytes(block_size)

import pytest
from merkle_tree import MerkleTree


@pytest.fixture
def chunks():
    return [
        b"chunk_0",
        b"chunk_1",
        b"chunk_2",
        b"chunk_3",
        b"chunk_4",
    ]


@pytest.fixture
def chunks_2():
    return [
        b"chunk_4",
        b"chunk_3",
        b"chunk_2",
        b"chunk_1",
        b"chunk_0",
    ]

# Test that a correct proof verifies successfully
def test_valid_proof(chunks):
    tree = MerkleTree(chunks)
    sample_index = 2
    proof = tree.get_proof(sample_index)

    valid = MerkleTree.verify_proof(chunks[sample_index], proof, tree.get_root())
    assert valid is True

# Test that modifying a sibling hash causes verification to fail
def test_invalid_proof_changed_sibling_hash(chunks):
    tree = MerkleTree(chunks)
    sample_index = 2
    proof = tree.get_proof(sample_index)

    bad_proof = proof[:]
    bad_proof[0] = (b"\x00" * 32, bad_proof[0][1])

    valid = MerkleTree.verify_proof(chunks[sample_index], bad_proof, tree.get_root())
    assert valid is False

# Test that changing the direction (left/right) breaks the proof
def test_invalid_proof_changed_direction(chunks):
    tree = MerkleTree(chunks)
    sample_index = 2
    proof = tree.get_proof(sample_index)

    bad_proof = proof[:]
    bad_proof[0] = (bad_proof[0][0], "left")

    valid = MerkleTree.verify_proof(chunks[sample_index], bad_proof, tree.get_root())
    assert valid is False

# Test that using a different chunk with the same proof fails verification
def test_invalid_proof_wrong_chunk(chunks):
    tree = MerkleTree(chunks)
    sample_index = 2
    proof = tree.get_proof(sample_index)

    valid = MerkleTree.verify_proof(chunks[3], proof, tree.get_root())
    assert valid is False

# Test that verifying against a different tree root fails
def test_invalid_proof_different_root(chunks, chunks_2):
    tree1 = MerkleTree(chunks)
    tree2 = MerkleTree(chunks_2)

    sample_index = 2
    proof = tree1.get_proof(sample_index)

    valid = MerkleTree.verify_proof(chunks[sample_index], proof, tree2.get_root())
    assert valid is False

# Test that creating a tree with no chunks raises ValueError
def test_init_empty_chunks():
    with pytest.raises(ValueError):
        MerkleTree([])

# Test that creating a tree with a non-bytes chunk raises TypeError
def test_init_non_bytes_chunk():
    with pytest.raises(TypeError):
        MerkleTree([b"chunk_0", "chunk_1", b"chunk_2"])

# Test that requesting a proof with an invalid index raises IndexError
def test_get_proof_invalid_index(chunks):
    tree = MerkleTree(chunks)

    with pytest.raises(IndexError):
        tree.get_proof(10)

# Test that verify_proof raises TypeError if chunk is not bytes
def test_verify_proof_non_bytes_chunk(chunks):
    tree = MerkleTree(chunks)
    proof = tree.get_proof(0)

    with pytest.raises(TypeError):
        MerkleTree.verify_proof("not_bytes", proof, tree.get_root())

# Test that verify_proof raises TypeError if root is not bytes
def test_verify_proof_non_bytes_root(chunks):
    tree = MerkleTree(chunks)
    proof = tree.get_proof(0)

    with pytest.raises(TypeError):
        MerkleTree.verify_proof(chunks[0], proof, "not_bytes")

# Test that verify_proof raises TypeError if a proof sibling hash is not bytes
def test_verify_proof_non_bytes_sibling_hash(chunks):
    tree = MerkleTree(chunks)
    proof = tree.get_proof(0)

    bad_proof = proof[:]
    bad_proof[0] = ("not_bytes", bad_proof[0][1])

    with pytest.raises(TypeError):
        MerkleTree.verify_proof(chunks[0], bad_proof, tree.get_root())

# Test that verify_proof raises ValueError if direction is invalid
def test_verify_proof_invalid_direction(chunks):
    tree = MerkleTree(chunks)
    proof = tree.get_proof(0)

    bad_proof = proof[:]
    bad_proof[0] = (bad_proof[0][0], "up")

    with pytest.raises(ValueError):
        MerkleTree.verify_proof(chunks[0], bad_proof, tree.get_root())
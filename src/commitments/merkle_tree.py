import hashlib
from typing import List, Tuple


class MerkleTree:
    """
    This class builds a Merkle tree from a list of byte chunks and
    provides functionality to retrieve the Merkle root, generate
    proofs, and verify proofs.

    Input:
        chunks
            Type: List[bytes]
            Each chunk should be raw data
            (e.g. blockchain data without headers).

    Variables:
        self.chunks
            Type: List[bytes]
            Description:
                A copy of the original input chunks provided to the tree.

        self.leaves
            Type: List[bytes]
            Description:
                The list of hashed chunks (leaf nodes of the Merkle tree).

        self.levels
            Type: List[List[bytes]]
            Description:
                A list of levels representing the full Merkle tree.
                Each inner list contains the nodes at that level,
                starting from the leaves up to the root.
                (final level containing a single hash).

    Methods:

        __init__(chunks)
            Input:
                chunks: List[bytes]
            Description:
                Validates input, hashes all chunks into leaves, and constructs
                the full Merkle tree stored as levels.

        _sha256(data)
            Input:
                data: bytes
            Output:
                bytes
            Description:
                Computes the SHA-256 hash of the input data. (hashlib)

        _hash_leaf(chunk)
            Input:
                chunk: bytes
            Output:
                bytes
            Description:
                Hashes a single data chunk to produce a leaf node.

        _hash_pair(left, right)
            Input:
                left: bytes
                right: bytes
            Output:
                bytes
            Description:
                Hashes two child nodes together to form a parent node.

        _build_tree()
            Input:
                None
            Output:
                None
            Description:
                Constructs the Merkle tree level by level from the leaves
                up to the root. If a level has an odd number of nodes, the
                last node is duplicated.

        get_root()
            Input:
                None
            Output:
                bytes
            Description:
                Returns the Merkle root (top hash of the tree).

        get_levels()
            Input:
                None
            Output:
                List[List[bytes]]
            Description:
                Returns a copy of all levels of the tree, where each level
                is a list of hashes from leaves to root.

        get_proof(index)
            Input:
                index: int
            Output:
                List[Tuple[bytes, str]]
            Description:
                Generates a Merkle proof for the leaf at the given index.
                The proof is a list of tuples containing:
                    (sibling_hash, direction)
                where direction is "left" or "right", indicating where the
                sibling sits relative to the current node.

        verify_proof(chunk, proof, root)
            Input:
                chunk: bytes
                proof: List[Tuple[bytes, str]]
                root: bytes
            Output:
                bool
            Description:
                Verifies that a chunk belongs to a Merkle tree with the
                given root by reconstructing the hash using the proof.
                Returns True if valid, otherwise False.
    """

    def __init__(self, chunks: List[bytes]):

        # Error checks
        if len(chunks) == 0:
            raise ValueError("Cannot pass empty chunks")

        for i in range(len(chunks)):
            chunk = chunks[i]
            if not isinstance(chunk, bytes):
                raise TypeError(f"Chunk at index {i} is not bytes")

        # Copy chunks
        self.chunks = chunks[:]

        # Create leaves by hashing each chunk
        self.leaves = []
        for chunk in self.chunks:
            hashed = self._hash_leaf(chunk)
            self.leaves.append(hashed)

        # Initialise levels with the leaves
        self.levels = []
        self.levels.append(self.leaves[:])

        # Build the rest of the tree
        self._build_tree()

    @staticmethod
    def _sha256(data: bytes) -> bytes:
        return hashlib.sha256(data).digest()

    @classmethod
    def _hash_leaf(cls, chunk: bytes) -> bytes:
        return cls._sha256(chunk)

    @classmethod
    def _hash_pair(cls, left: bytes, right: bytes) -> bytes:
        return cls._sha256(left + right)

    def _build_tree(self) -> None:
        current_level = self.leaves[:]

        while len(current_level) > 1:
            # If number of nodes is odd, duplicate the last one
            if len(current_level) % 2 == 1:
                current_level = current_level + [current_level[-1]]

            next_level = []

            # Loop through current levels jumping by two and hash siblings
            for i in range(0, len(current_level), 2):
                parent = self._hash_pair(
                    current_level[i], current_level[i + 1]
                )
                next_level.append(parent)

            self.levels.append(next_level)
            current_level = next_level

    def get_root(self) -> bytes:
        return self.levels[-1][0]

    def get_levels(self) -> List[List[bytes]]:
        new_levels = []
        for level in self.levels:
            new_levels.append(list(level))
        return new_levels

    def get_proof(self, index: int) -> List[Tuple[bytes, str]]:
        # Error Check
        if index < 0 or index >= len(self.leaves):
            raise IndexError("Leaf index out of range")

        proof = []
        current_index = index

        # Loop through each level except root.
        # Only follows one vertical path,
        # not every node in each level.
        for level in self.levels[:-1]:
            level_nodes = level[:]

            # Duplicate last node if the level length is odd
            if len(level_nodes) % 2 == 1:
                level_nodes.append(level_nodes[-1])

            if current_index % 2 == 0:
                sibling_index = current_index + 1
                direction = "right"
            else:
                sibling_index = current_index - 1
                direction = "left"

            proof.append((level_nodes[sibling_index], direction))

            # Divides and rounds
            current_index //= 2

        return proof

    @classmethod
    def verify_proof(
        cls, chunk: bytes, proof: List[Tuple[bytes, str]], root: bytes
    ) -> bool:
        # Error Check
        if not isinstance(chunk, bytes):
            raise TypeError("Chunk must be bytes")
        if not isinstance(root, bytes):
            raise TypeError("Root must be bytes")

        current_hash = cls._hash_leaf(chunk)

        # Loop through proof and begin hashing by proof direction
        for sibling_hash, direction in proof:
            if not isinstance(sibling_hash, bytes):
                raise TypeError("Proof sibling hashes must be bytes")

            if direction == "right":
                current_hash = cls._hash_pair(current_hash, sibling_hash)
            elif direction == "left":
                current_hash = cls._hash_pair(sibling_hash, current_hash)
            else:
                raise ValueError("direction must be 'left' or 'right'")

        return current_hash == root

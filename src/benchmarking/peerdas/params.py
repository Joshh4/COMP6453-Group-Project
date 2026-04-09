"""
PeerDAS concrete parameters used by this benchmark package.

These values follow the "Concrete Instantiation" section of the PeerDAS write-up:
- D = 64 evaluations per cell
- K = 64 cells in a blob
- N = 128 cells in an extended blob

Important implementation note:
For *benchmarking RS/NTT throughput* we do not require the Ethereum BLS12-381
scalar field itself. Instead we choose a smaller prime p where ND divides p-1,
so an ND-point NTT exists directly in GF(p). This keeps experiments lightweight
while preserving the same algorithmic shape and asymptotic behavior.
"""

# ---- PeerDAS symbol geometry ----
# D: values per cell
# K: cells in a blob (original data, one row before extension)
# N: cells after row-wise RS extension
D = 64
K = 64
N = 128

# Aliases used in CSV output / downstream scripts for readability.
NUM_CELLS_BLOB = K
EXTENDED_CELLS = N

# Flattened lengths in field elements.
# KD: original row length, ND: extended row length.
KD = K * D
ND = N * D

# Ethereum field element byte width (documented for reference only).
ETHEREUM_FIELD_BYTES = 32

# Prime where ND | (p - 1), enabling an ND-point NTT in GF(p).
# Here ND = 8192 and 40960 = 5 * 8192.
FIELD_PRIME = 40961

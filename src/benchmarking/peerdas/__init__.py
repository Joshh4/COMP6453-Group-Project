"""PeerDAS-style RS encoding and helpers for benchmarking (Wagner–Zapico model)."""

from .params import (
    D,
    ETHEREUM_FIELD_BYTES,
    EXTENDED_CELLS,
    FIELD_PRIME,
    K,
    KD,
    N,
    ND,
    NUM_CELLS_BLOB,
)
from .rs_row import extend_blob_coefficients, reverse_bit_order_index

__all__ = [
    "D",
    "ETHEREUM_FIELD_BYTES",
    "EXTENDED_CELLS",
    "FIELD_PRIME",
    "K",
    "KD",
    "N",
    "ND",
    "NUM_CELLS_BLOB",
    "extend_blob_coefficients",
    "reverse_bit_order_index",
]

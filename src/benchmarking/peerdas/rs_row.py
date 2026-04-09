"""
RS encoding helpers for the PeerDAS row/column model.

This module focuses on Section 3 behavior in an implementation-friendly form:
1) `extend_blob_coefficients()`: one row (blob) -> extended row via NTT.
2) `build_full_matrix_rowwise()`: stack many extended rows into RSfull matrix.
3) `gather_column_cells()`: extract one sampled column symbol across all rows.

Design choice:
The code treats each blob as polynomial coefficients of degree < KD and computes
ND evaluations by zero-padding + NTT. This is equivalent in complexity to the
"interpolate then evaluate" view from the document, but simpler for benchmarking.
"""

from __future__ import annotations

import galois
import numpy as np
from galois._ntt import ntt

from .params import D, FIELD_PRIME, KD, ND, N


GF = galois.GF(FIELD_PRIME)


def reverse_bit_order_index(i: int, log_m: int) -> int:
    """
    Convert natural index into reverse-bit ordering index.

    PeerDAS uses reverse-bit order on roots of unity so contiguous chunks map
    cleanly to subgroup cosets. This helper is kept for indexing experiments and
    validation utilities.
    """
    if i < 0 or i >= (1 << log_m):
        msg = f"i must be in [0, 2^{log_m})"
        raise ValueError(msg)
    bits = format(i, f"0{log_m}b")
    return int(bits[::-1], 2)


def extend_blob_coefficients(coefficients: np.ndarray) -> np.ndarray:
    """
    RSrow extend: KD coefficients -> ND evaluations (NTT).

    Parameters
    ----------
    coefficients :
        Length KD over GF(p); interpreted as low-degree coefficients of f.
    """
    # Guard against malformed inputs so benchmark failures are explicit.
    if len(coefficients) != KD:
        msg = f"expected {KD} coefficients, got {len(coefficients)}"
        raise ValueError(msg)
    # Build f(X) coefficients of length ND by padding with zeros:
    # f(X) = c0 + c1 X + ... + c_{KD-1} X^{KD-1}
    padded = GF.Zeros(ND)
    padded[:KD] = GF(coefficients)
    # NTT gives evaluations of f over an ND-sized root-of-unity domain.
    return np.array(ntt(padded))


def gather_column_cells(matrix: np.ndarray, col_j: int) -> np.ndarray:
    """
    One PeerDAS column symbol: all row cells at column index col_j.

    matrix has shape (ell, ND); returns shape (ell, D).
    """
    # Matrix shape contract: (ell, ND), one extended row per blob.
    if matrix.ndim != 2:
        raise ValueError("matrix must be 2-D")
    _, width = matrix.shape
    if width != ND:
        msg = f"row width must be ND={ND}"
        raise ValueError(msg)
    if col_j < 0 or col_j >= N:
        raise IndexError(col_j)
    # Each "column symbol" contains one D-sized cell from every row.
    start = col_j * D
    return matrix[:, start : start + D]


def build_full_matrix_rowwise(
    blob_coeff_rows: list[np.ndarray],
) -> np.ndarray:
    """
    RSfull matrix: each row is one extended blob; shape (ell, ND).

    Symbols are columns of cells (Section 3.2); this returns flat row layout.
    """
    # ell = number of blobs / rows in RSfull.
    ell = len(blob_coeff_rows)
    out = np.empty((ell, ND), dtype=np.int64)
    for r, coeffs in enumerate(blob_coeff_rows):
        # Extend each blob independently, then place as one row.
        out[r, :] = extend_blob_coefficients(coeffs)
    return out

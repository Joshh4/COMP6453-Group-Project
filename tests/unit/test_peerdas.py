import numpy as np
import pytest
from galois._ntt import intt, ntt

from src.benchmarking.peerdas.params import D, FIELD_PRIME, KD, N, ND
from src.benchmarking.peerdas.rs_row import (
    build_full_matrix_rowwise,
    extend_blob_coefficients,
    gather_column_cells,
    reverse_bit_order_index,
)
from src.benchmarking.peerdas.verify_cost import (
    batched_pairing_count,
    naive_pairing_count,
)


def test_reverse_bit_order_identity_small():
    # Quick sanity checks for bit-reversal mapping on 3-bit indices.
    assert reverse_bit_order_index(0, 3) == 0
    assert reverse_bit_order_index(7, 3) == 7
    assert reverse_bit_order_index(1, 3) == 4


def test_ntt_roundtrip_padding():
    # NTT followed by inverse NTT should recover the original vector.
    padded = np.random.randint(0, FIELD_PRIME, size=ND, dtype=np.int64)
    back = np.array(intt(ntt(padded)))
    assert np.array_equal(back, padded)


def test_extend_blob_length():
    # RSrow extension returns ND evaluations from KD coefficients.
    coeffs = np.random.randint(0, FIELD_PRIME, size=KD, dtype=np.int64)
    out = extend_blob_coefficients(coeffs)
    assert len(out) == ND


def test_gather_column_shape():
    # One sampled column symbol has shape (ell, D).
    rng = np.random.default_rng(0)
    ell = 3
    rows = [rng.integers(0, FIELD_PRIME, size=KD, dtype=np.int64) for _ in range(ell)]
    m = build_full_matrix_rowwise(rows)
    col = gather_column_cells(m, 0)
    assert col.shape == (ell, D)


def test_gather_column_index_bounds():
    # Access past the last column must raise IndexError.
    rng = np.random.default_rng(0)
    m = build_full_matrix_rowwise(
        [rng.integers(0, FIELD_PRIME, size=KD, dtype=np.int64)]
    )
    with pytest.raises(IndexError):
        gather_column_cells(m, N)


def test_verify_cost_counts():
    # Cost model should match equations: naive=2*L*ell, batched=2.
    assert naive_pairing_count(4, 8) == 64
    assert batched_pairing_count() == 2

import pytest
import secrets

from src.commitments.KZG import (
    FIELD_PRIME,
    D_CELL_SIZE,
    K_CELLS_BLOB,
    N_CELLS_EXT,
    KZGSetup,
    RootsOfUnity,
    CCrow,
    CCfull,
    reconstruct_extended_blob,
)

# Small domain that still satisfies all the power-of-two / coset requirements.
# We use D=4, k=4 so the blob is 16 elements and the extended domain is 32.
_D = 4
_K = 4
_N = 8   # = 2 * K
_M = _N * _D  # total domain size = 32

# A primitive 32nd root of unity for BLS12-381's scalar field.
# omega_32 = omega_large ^ (FIELD_PRIME-1 // 32)  (precomputed for speed)
_OMEGA_32 = pow(
    0x7,
    (FIELD_PRIME - 1) // 32,
    FIELD_PRIME,
)

# Shared across all tests in this module, generated once to avoid
# repeating the expensive trusted setup for every test.
@pytest.fixture(scope="module")
def srs():
    # One trusted setup shared by the whole test suite
    return KZGSetup.generate(max_degree=255, D=_D)


@pytest.fixture(scope="module")
def domain():
    return RootsOfUnity(_OMEGA_32, m=_M)


@pytest.fixture(scope="module")
def ccrow(srs, domain):
    return CCrow(srs, domain, D=_D, k=_K, n=_N)


@pytest.fixture(scope="module")
def blob():
    # A fixed blob of D*k = 16 field elements
    return [i + 1 for i in range(_D * _K)]


# RootsOfUnity

class TestRootsOfUnity:
    def test_first_element_is_one(self, domain):
        # omega^0 = 1 should always be the first natural element
        assert domain._natural[0] == 1

    def test_element_count(self, domain):
        assert len(domain._rbo) == _M

    def test_fft_ifft_roundtrip(self, domain):
        # IFFT(FFT(v)) == v for arbitrary input
        original = [secrets.randbelow(FIELD_PRIME) for _ in range(_M)]
        recovered = domain.ifft(domain.fft(original))
        assert recovered == original

    def test_fft_length_mismatch_raises(self, domain):
        with pytest.raises(AssertionError):
            domain.fft([1, 2, 3])  # wrong length

    def test_coset_fft_ifft_roundtrip(self, domain):
        coeffs = [secrets.randbelow(FIELD_PRIME) for _ in range(_M)]
        beta = 7
        assert domain.coset_ifft(domain.coset_fft(coeffs, beta), beta) == coeffs

    def test_coset_vanishing_degree(self, domain):
        # Vanishing polynomial of a cell should have degree D
        r, coset_root = domain.coset_vanishing(_D, cell_index=0)
        assert r == _D
        # z(X) = X^D - coset_root, verify it vanishes at the coset points
        p = domain.p
        for i in range(_D):
            pt = domain.element(0 * _D + i)
            assert (pow(pt, _D, p) - coset_root) % p == 0

    def test_all_domain_elements_distinct(self, domain):
        # A valid group of roots of unity should have no duplicates
        elements = [domain.element(i) for i in range(_M)]
        assert len(set(elements)) == _M

    def test_element_wraps_at_m(self, domain):
        # element(m) should cycle back to element(0)
        assert domain.element(_M) == domain.element(0)


# KZGSetup / SRS

class TestKZGSetup:
    def test_srs_g1_length(self, srs):
        assert len(srs.g1_powers) == 256  # max_degree + 1

    def test_srs_g2_length(self, srs):
        assert len(srs.g2_powers) == 256

    def test_srs_equality(self):
        # Two separate setups should not be equal (different random tau)
        a = KZGSetup.generate(max_degree=7, D=_D)
        b = KZGSetup.generate(max_degree=7, D=_D)
        assert a != b

    def test_srs_repr(self, srs):
        assert "SRS" in repr(srs)


# CCrow - single blob commit / open / verify

class TestCCrow:
    def test_commit_returns_curve_point(self, ccrow, blob):
        com, state = ccrow.commit(blob)
        # A valid G1 point is a tuple of FQ elements (not None / Z1 identity)
        assert com is not None

    def test_open_returns_correct_number_of_values(self, ccrow, blob):
        _, state = ccrow.commit(blob)
        for cell_idx in range(_N):
            values, proof = ccrow.open(state, cell_idx)
            assert len(values) == _D

    def test_verify_valid_opening(self, ccrow, blob):
        com, state = ccrow.commit(blob)
        for cell_idx in range(_N):
            values, proof = ccrow.open(state, cell_idx)
            assert ccrow.verify(com, cell_idx, values, proof), (
                f"Valid proof rejected for cell {cell_idx}"
            )

    def test_verify_rejects_tampered_values(self, ccrow, blob):
        com, state = ccrow.commit(blob)
        cell_idx = 0
        values, proof = ccrow.open(state, cell_idx)

        # Flip the first value
        bad_values = list(values)
        bad_values[0] = (bad_values[0] + 1) % FIELD_PRIME

        assert not ccrow.verify(com, cell_idx, bad_values, proof), (
            "Tampered values should not verify"
        )

    def test_verify_rejects_wrong_cell_index(self, ccrow, blob):
        com, state = ccrow.commit(blob)
        values, proof = ccrow.open(state, 0)
        # Claim these values belong to cell 1 - should fail
        assert not ccrow.verify(com, 1, values, proof)

    def test_commit_wrong_blob_size_raises(self, ccrow):
        with pytest.raises(AssertionError):
            ccrow.commit([1, 2, 3])  # too short

    def test_different_blobs_produce_different_commitments(self, ccrow):
        # Two distinct blobs must not collide at the same commitment
        blob_a = [1] * (_D * _K)
        blob_b = [2] * (_D * _K)
        com_a, _ = ccrow.commit(blob_a)
        com_b, _ = ccrow.commit(blob_b)
        assert com_a != com_b

    def test_open_is_deterministic(self, ccrow, blob):
        # Opening the same cell twice should give identical results
        _, state = ccrow.commit(blob)
        values_1, proof_1 = ccrow.open(state, 0)
        values_2, proof_2 = ccrow.open(state, 0)
        assert values_1 == values_2
        assert proof_1 == proof_2

    def test_zero_blob_commits_and_verifies(self, ccrow):
        # A blob of all zeros is a valid edge case
        zero_blob = [0] * (_D * _K)
        com, state = ccrow.commit(zero_blob)
        values, proof = ccrow.open(state, 0)
        assert ccrow.verify(com, 0, values, proof)

    def test_verify_boundary_cells(self, ccrow, blob):
        # Check the first and last cell indices explicitly
        com, state = ccrow.commit(blob)
        for cell_idx in [0, _N - 1]:
            values, proof = ccrow.open(state, cell_idx)
            assert ccrow.verify(com, cell_idx, values, proof), (
                f"Boundary cell {cell_idx} failed verification"
            )

    def test_proof_does_not_verify_against_different_commitment(self, ccrow):
        # A proof from one blob should not pass under a different commitment
        blob_a = [1] * (_D * _K)
        blob_b = [2] * (_D * _K)
        com_a, state_a = ccrow.commit(blob_a)
        com_b, _       = ccrow.commit(blob_b)
        values, proof  = ccrow.open(state_a, 0)
        assert not ccrow.verify(com_b, 0, values, proof)


# reconstruct_extended_blob

class TestReconstructExtendedBlob:
    def test_full_reconstruction_from_k_cells(self, ccrow, domain, blob):
        # Given exactly k cells we should recover all n*D values
        com, state = ccrow.commit(blob)

        # Collect all extended evaluations from every cell
        all_cells = {}
        for j in range(_N):
            vals, _ = ccrow.open(state, j)
            all_cells[j] = vals

        # Use only the first k cells (drop the second half)
        partial = {j: all_cells[j] for j in range(_K)}

        recovered = reconstruct_extended_blob(
            domain, partial, D=_D, k=_K, n=_N
        )
        assert len(recovered) == _N * _D

        # Every recovered value must match the full cell values
        for j in range(_N):
            for i in range(_D):
                pos = j * _D + i
                assert recovered[pos] == all_cells[j][i], (
                    f"Mismatch at cell {j}, offset {i}"
                )

    def test_reconstruction_too_few_cells_raises(self, domain):
        with pytest.raises(AssertionError):
            reconstruct_extended_blob(
                domain, {0: [0] * _D}, D=_D, k=_K, n=_N
            )  # only 1 cell, need k=4

    def test_reconstruction_from_scattered_cells(self, ccrow, domain, blob):
        # Recovery should work even when the k cells are not contiguous
        com, state = ccrow.commit(blob)

        all_cells = {}
        for j in range(_N):
            vals, _ = ccrow.open(state, j)
            all_cells[j] = vals

        # Pick k cells scattered across the range rather than the first k
        scattered = {0: all_cells[0], 2: all_cells[2], 5: all_cells[5], 7: all_cells[7]}
        assert len(scattered) == _K

        recovered = reconstruct_extended_blob(
            domain, scattered, D=_D, k=_K, n=_N
        )

        for j in range(_N):
            for i in range(_D):
                pos = j * _D + i
                assert recovered[pos] == all_cells[j][i], (
                    f"Mismatch at cell {j}, offset {i}"
                )


# CCfull - multi-blob matrix commit / open / batch verify

class TestCCfull:
    @pytest.fixture(scope="class")
    def ccfull(self, srs, domain):
        return CCfull(srs, domain, ell=2, D=_D, k=_K, n=_N)

    @pytest.fixture(scope="class")
    def two_blobs(self):
        blob_a = [(i + 1) for i in range(_D * _K)]
        blob_b = [(i + 100) % FIELD_PRIME for i in range(_D * _K)]
        return [blob_a, blob_b]

    def test_commit_returns_one_commitment_per_blob(self, ccfull, two_blobs):
        coms, states = ccfull.commit(two_blobs)
        assert len(coms) == 2
        assert len(states) == 2

    def test_verify_column_valid(self, ccfull, two_blobs):
        coms, states = ccfull.commit(two_blobs)
        col = 0
        cells, proofs = ccfull.open(states, col)
        assert ccfull.verify_column(coms, col, cells, proofs)

    def test_verify_column_rejects_tampered_cell(self, ccfull, two_blobs):
        coms, states = ccfull.commit(two_blobs)
        col = 0
        cells, proofs = ccfull.open(states, col)

        # Corrupt the second value in the first row's cell
        bad_cells = [list(c) for c in cells]
        bad_cells[0][1] = (bad_cells[0][1] + 1) % FIELD_PRIME

        assert not ccfull.verify_column(coms, col, bad_cells, proofs)

    def test_batch_verify_valid(self, ccfull, two_blobs):
        coms, states = ccfull.commit(two_blobs)

        # Open two different columns and batch verify all proofs at once
        col_a, col_b = 0, 1
        cells_a, proofs_a = ccfull.open(states, col_a)
        cells_b, proofs_b = ccfull.open(states, col_b)

        # Flatten into the format batch_verify expects
        all_cells   = cells_a  + cells_b
        all_proofs  = proofs_a + proofs_b
        row_indices = [0, 1,    0, 1]
        col_indices = [col_a, col_a, col_b, col_b]

        assert ccfull.batch_verify(coms, col_indices, row_indices, all_cells, all_proofs)

    def test_batch_verify_rejects_tampered_cell(self, ccfull, two_blobs):
        coms, states = ccfull.commit(two_blobs)
        col = 0
        cells, proofs = ccfull.open(states, col)

        # Corrupt the first cell of the first row
        bad_cells = [list(c) for c in cells]
        bad_cells[0][0] = (bad_cells[0][0] + 1) % FIELD_PRIME

        row_indices = list(range(len(proofs)))
        col_indices = [col] * len(proofs)

        assert not ccfull.batch_verify(
            coms, col_indices, row_indices, bad_cells, proofs
        )
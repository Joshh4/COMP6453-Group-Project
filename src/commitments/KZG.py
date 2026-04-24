# KZG Polynomial Commitment Scheme
#
# HOW TO USE THIS
# ---------------
# 1. Run the trusted setup once to get a SRS (structured reference string):
#
#       srs = KZGSetup.generate(max_degree=4095)
#
# 2. Build a domain of roots of unity the same size as your extended blob:
#
#       domain = RootsOfUnity(omega, m=N_CELLS_EXT * D_CELL_SIZE)
#
# 3. To commit to a single blob (one row):
#
#       ccrow = CCrow(srs, domain)
#       commitment, state = ccrow.commit(blob_data)   # blob_data is a list
#       of D*k field elements
#
# 4. To open a cell (prove what the values are at column j):
#
#       cell_values, proof = ccrow.open(state, cell_index)
#
# 5. To verify a cell opening:
#
#       ok = ccrow.verify(commitment, cell_index, cell_values, proof)
#
# 6. For the full PeerDAS matrix (multiple blobs = multiple rows):
#
#       ccfull = CCfull(srs, domain, ell=num_blobs)
#       commitments, states = ccfull.commit([blob1, blob2, ...])
#       cells, proofs = ccfull.open(states, col_index)
#       ok = ccfull.batch_verify(commitments, col_indices,
#       row_indices, cells, proofs)
#
# 7. If some cells are missing and you want to recover them:
#
#       recovered = reconstruct_extended_blob(domain,
#       {cell_index: cell_values, ...})

import hashlib
import secrets

import py_ecc.fields.field_elements as _py_ecc_fe
import py_ecc.fields.optimized_field_elements as _py_ecc_ofe
from py_ecc.bls12_381 import G1, G2, Z1, add, multiply, neg, pairing

from src.reedsolomon.polynomial import Poly

# py_ecc's default FQ/FQP.__pow__ is recursive; BLS12-381 final exponentiation
# in pairing() needs ~4300+ stack frames and blows RecursionError on Windows.
# optimized_field_elements provides the same math with an iterative __pow__.
_py_ecc_fe.FQ.__pow__ = _py_ecc_ofe.FQ.__pow__
_py_ecc_fe.FQP.__pow__ = _py_ecc_ofe.FQP.__pow__

# Every scalar in this scheme lives in the range 0 to FIELD_PRIME-1
FIELD_PRIME = (
    0x73EDA753299D7D483339D80809A1D80553BDA402FFFE5BFEFFFFFFFF00000001
)

# PeerDAS parameters: each blob has 64 cells, each cell has 64 evaluations,
# the extended blob doubles the cells to 128
D_CELL_SIZE = 64  # evaluations per cell
K_CELLS_BLOB = 64  # cells per blob
N_CELLS_EXT = 128  # cells per extended blob (= 2 * K_CELLS_BLOB)


# Lift a scalar onto G1
def g1_mul(scalar: int):
    return multiply(G1, scalar % FIELD_PRIME)


# Lift a scalar onto G2
def g2_mul(scalar: int):
    return multiply(G2, scalar % FIELD_PRIME)


# RootsOfUnity manages the evaluation domain H = {1, omega, omega^2, ...}
# We order the elements using reverse-bit ordering (RBO) so that each
# contiguous chunk of D elements corresponds to exactly one coset — this
# makes the vanishing polynomial of any cell a cheap two-term polynomial
class RootsOfUnity:
    def __init__(self, omega: int, m: int, p: int = FIELD_PRIME):
        assert (m & (m - 1)) == 0, "m must be a power of 2"
        self.omega = omega % p
        self.m = m
        self.p = p

        # Build the natural list: _natural[i] = omega^i,
        # starting at omega^0 = 1
        self._natural = []
        cur = 1
        for _ in range(m):
            self._natural.append(cur)  # append first so index 0 = omega^0 = 1
            cur = cur * omega % p

        # Reorder into reverse-bit order so chunks align with cosets
        t = m.bit_length() - 1
        self._rbo = [self._natural[self._rbo_index(i, t)] for i in range(m)]

    @staticmethod
    def _rbo_index(i: int, t: int) -> int:
        # Reverse the t-bit binary representation of i
        return int(bin(i)[2:].zfill(t)[::-1], 2)

    def element(self, i: int) -> int:
        # Return the i-th domain point in RBO order
        return self._rbo[i % self.m]

    def coset_vanishing(self, r: int, s_hat: int) -> tuple:
        # The vanishing polynomial of cell s_hat is z(X) = X^r - coset_root
        # coset_root is the first element of that cell's coset
        coset_root = self.element(s_hat * r)
        return r, coset_root

    def lagrange_interpolate_coset(
        self, r: int, s_hat: int, values: list
    ) -> Poly:
        # Build the unique polynomial that hits each value at the r
        # coset points
        points = [self.element(s_hat * r + i) for i in range(r)]
        return Poly.lagrange_interpolate(points, values, self.p)

    # FFT over Z_p — takes polynomial coefficients, returns evaluations at all
    # domain points in RBO order. O(m log m) using Cooley-Tukey butterflies
    def fft(self, values: list) -> list:
        m = self.m
        p = self.p
        t = m.bit_length() - 1
        assert len(values) == m
        A = [int(v) % p for v in values]

        # Bit-reversal permutation on the input before the butterfly passes
        for i in range(m):
            j = self._rbo_index(i, t)
            if i < j:
                A[i], A[j] = A[j], A[i]

        # Each pass doubles the sub-problem size until the whole array is done
        length = 2
        while length <= m:
            half = length // 2
            w_step = pow(
                self.omega, m // length, p
            )  # twiddle factor for this pass
            for start in range(0, m, length):
                w = 1
                for k in range(half):
                    u = A[start + k]
                    v = A[start + k + half] * w % p
                    A[start + k] = (u + v) % p  # butterfly add
                    A[start + k + half] = (u - v) % p  # butterfly subtract
                    w = w * w_step % p
            length *= 2

        # After the DIT FFT, A is in natural evaluation order; remap to RBO
        return [A[self._rbo_index(i, t)] for i in range(m)]

    # Inverse FFT — takes RBO-ordered evaluations, returns coefficients.
    # Same butterfly structure as fft but uses omega^-1 and scales by 1/m
    def ifft(self, values: list) -> list:
        m = self.m
        p = self.p
        t = m.bit_length() - 1
        assert len(values) == m

        # Convert from RBO back to natural order before running the kernel
        natural = [0] * m
        for i in range(m):
            natural[self._rbo_index(i, t)] = int(values[i]) % p

        omega_inv = pow(self.omega, p - 2, p)  # omega^-1 mod p
        A = natural[:]

        for i in range(m):
            j = self._rbo_index(i, t)
            if i < j:
                A[i], A[j] = A[j], A[i]

        length = 2
        while length <= m:
            half = length // 2
            w_step = pow(omega_inv, m // length, p)
            for start in range(0, m, length):
                w = 1
                for k in range(half):
                    u = A[start + k]
                    v = A[start + k + half] * w % p
                    A[start + k] = (u + v) % p
                    A[start + k + half] = (u - v) % p
                    w = w * w_step % p
            length *= 2

        m_inv = pow(m, p - 2, p)  # 1/m mod p
        return [(x * m_inv) % p for x in A]

    def coset_fft(self, coeffs: list, beta: int) -> list:
        # Evaluate a polynomial over the shifted domain beta*H
        p = self.p
        assert len(coeffs) == self.m
        beta_power = 1
        shifted = []
        for c in coeffs:
            shifted.append(int(c) * beta_power % p)
            beta_power = beta_power * beta % p
        return self.fft(shifted)

    def coset_ifft(self, evals: list, beta: int) -> list:
        # Inverse of coset_fft — undo the beta^i scaling after the IFFT
        p = self.p
        beta_inv = pow(beta, p - 2, p)
        coeffs = self.ifft(evals)
        beta_inv_power = 1
        result = []
        for c in coeffs:
            result.append(c * beta_inv_power % p)
            beta_inv_power = beta_inv_power * beta_inv % p
        return result


# The SRS is the output of the trusted setup — a collection of elliptic curve
# points that encode secret powers of tau without revealing tau itself
class SRS:
    def __init__(
        self,
        g1_powers: list,
        g2_powers: list,
        g2_tauD: object,
        max_degree: int,
    ):
        self.g1_powers = g1_powers  # [1]_1, [tau]_1, [tau^2]_1, ... in G1
        self.g2_powers = g2_powers  # [1]_2, [tau]_2, [tau^2]_2, ... in G2
        self.g2_tau = g2_powers[1]  # [tau]_2 shortcut
        self.g2_tauD = g2_tauD  # [tau^D]_2 precomputed for the batch verifier
        self.max_degree = max_degree

    def __repr__(self):
        return f"SRS(max_degree={self.max_degree!r}, g2_tau={self.g2_tau!r})"

    def __eq__(self, other):
        if not isinstance(other, SRS):
            return NotImplemented
        return (
            self.g1_powers == other.g1_powers
            and self.g2_powers == other.g2_powers
            and self.max_degree == other.max_degree
        )


# KZGSetup runs the trusted setup ceremony — pick a random secret tau,
# compute its powers on both curves, then forget tau
class KZGSetup:
    @staticmethod
    def generate(max_degree: int, D: int = D_CELL_SIZE) -> SRS:
        tau = secrets.randbelow(FIELD_PRIME - 2) + 1  # secret — never stored

        # G1 powers: [tau^0]_1, [tau^1]_1, ..., [tau^max_degree]_1
        g1_powers = []
        tau_power = 1
        for _ in range(max_degree + 1):
            g1_powers.append(g1_mul(tau_power))
            tau_power = tau_power * tau % FIELD_PRIME

        # G2 powers: same thing on the G2 curve
        g2_powers = []
        tau_power = 1
        for _ in range(max_degree + 1):
            g2_powers.append(g2_mul(tau_power))
            tau_power = tau_power * tau % FIELD_PRIME

        # [tau^D]_2 is used in every verification so precompute it once
        g2_tauD = g2_mul(pow(tau, D, FIELD_PRIME))

        return SRS(
            g1_powers=g1_powers,
            g2_powers=g2_powers,
            g2_tauD=g2_tauD,
            max_degree=max_degree,
        )


# Compute the KZG commitment to a polynomial: [f(tau)]_1
# We never know tau — we evaluate f at tau using the SRS points instead
def _commit_poly(srs: SRS, poly: Poly):
    if poly.deg() > srs.max_degree:
        raise ValueError(
            f"Polynomial degree {poly.deg()} exceeds SRS max {srs.max_degree}"
        )
    result = Z1  # start at the identity (zero) point
    for i, coeff in enumerate(poly.coeffs()):
        # add coeff_i * [tau^i]_1 to the running total
        result = add(
            result, multiply(srs.g1_powers[i], int(coeff) % FIELD_PRIME)
        )
    return result


# KZGProver creates commitments and opening proofs
class KZGProver:
    def __init__(self, srs: SRS, domain: RootsOfUnity, D: int = D_CELL_SIZE):
        self.srs = srs
        self.domain = domain
        self.D = D

    def commit(self, poly: Poly):
        return _commit_poly(self.srs, poly)

    def multi_open(self, poly: Poly, cell_index: int):
        # cell_index is 0-based (paper uses 1-based,
        # so subtract 1 when bridging)
        D = self.D
        r, coset_root = self.domain.coset_vanishing(D, cell_index)

        # Evaluate f at each of the D points belonging to this cell's coset
        cell_values = [
            poly(self.domain.element(cell_index * D + i)) for i in range(D)
        ]

        # Build I(X): the unique polynomial that matches f at those D points
        interpolant = self.domain.lagrange_interpolate_coset(D, cell_index, cell_values)

        # z(X) = X^D - coset_root is the vanishing polynomial of this
        # cell's coset
        z = Poly([-coset_root % FIELD_PRIME] + [0] * (D - 1) + [1])

        # Q(X) = (f(X) - I(X)) / z(X) — this division is exact because f and I
        # agree on all D coset points, so f - I vanishes there
        f_minus_interpolant = poly - interpolant
        quotient, remainder = Poly.divmod(f_minus_interpolant, z, FIELD_PRIME)

        if any(c % FIELD_PRIME != 0 for c in remainder.coeffs()):
            raise RuntimeError(
                "Non-zero remainder in multi_open — bug in coset setup"
            )

        # The proof is just the commitment to Q
        proof = _commit_poly(self.srs, quotient)
        return cell_values, proof

    def prove_all_cells(self, poly: Poly, n_cells: int = N_CELLS_EXT):
        # Naive: compute each cell's proof separately
        return [self.multi_open(poly, j) for j in range(n_cells)]


# KZGVerifier checks that a set of cell values really came
# from the committed polynomial
class KZGVerifier:
    def __init__(self, srs: SRS, domain: RootsOfUnity, D: int = D_CELL_SIZE):
        self.srs = srs
        self.domain = domain
        self.D = D

    def multi_verify(
        self, commitment, cell_index: int, cell_values: list, proof
    ) -> bool:
        # cell_index is 0-based
        D = self.D
        r, coset_root = self.domain.coset_vanishing(D, cell_index)

        # Rebuild interpolant(X) from the claimed cell values
        interpolant = self.domain.lagrange_interpolate_coset(
            D, cell_index, cell_values
        )
        I_tau_g1 = _commit_poly(self.srs, interpolant)  # [I(tau)]_1

        # [com - I(tau)]_1
        lhs_g1 = add(commitment, neg(I_tau_g1))

        # [z(tau)]_2 = [tau^D]_2 - [coset_root]_2
        z_tau_g2 = add(self.srs.g2_tauD, neg(g2_mul(coset_root)))

        # Pairing check: e(com - [I(tau)]_1, [1]_2) == e(proof, [z(tau)]_2)
        # This works because if the proof is honest then
        # com - [I(tau)]_1 = [Q(tau)*z(tau)]_1
        lhs = pairing(G2, lhs_g1)
        rhs = pairing(z_tau_g2, proof)
        return lhs == rhs

    def batch_verify(
        self,
        commitments: list,
        cell_indices: list,
        row_indices: list,
        cells: list,
        proofs: list,
    ) -> bool:
        L = len(proofs)
        assert len(cell_indices) == L
        assert len(row_indices) == L
        assert len(cells) == L

        D = self.D

        # Derive a random scalar r by hashing all the inputs together
        # This collapses L separate pairing checks into just 2 pairings
        h = hashlib.sha256()
        for com in commitments:
            h.update(str(com).encode())
        for ik, jk, cell, pi in zip(row_indices, cell_indices, cells, proofs):
            h.update(str(ik).encode())
            h.update(str(jk).encode())
            h.update(str(cell).encode())
            h.update(str(pi).encode())
        r = int.from_bytes(h.digest(), "big") % FIELD_PRIME

        # LHS accumulator: sum of r^k * proof_k in G1
        lhs_sum = Z1
        r_power = 1
        for pi in proofs:
            lhs_sum = add(lhs_sum, multiply(pi, r_power))
            r_power = r_power * r % FIELD_PRIME

        # RHS accumulator: sum of r^k *
        # (com_ik - [I_k(tau)]_1 + coset_root_k * proof_k)
        rhs_sum = Z1
        r_power = 1
        for ik, jk, cell, pi in zip(row_indices, cell_indices, cells, proofs):
            _, coset_root = self.domain.coset_vanishing(D, jk)
            I_tau = _commit_poly(
                self.srs, self.domain.lagrange_interpolate_coset(D, jk, cell)
            )
            term = add(
                add(commitments[ik], neg(I_tau)), multiply(pi, coset_root)
            )
            rhs_sum = add(rhs_sum, multiply(term, r_power))
            r_power = r_power * r % FIELD_PRIME

        # Two pairings instead of 2*L
        lhs = pairing(self.srs.g2_tauD, lhs_sum)
        rhs = pairing(G2, rhs_sum)
        return lhs == rhs


# CCrow handles a single blob: commit to it, open any cell, verify any cell
class CCrow:
    def __init__(
        self,
        srs: SRS,
        domain: RootsOfUnity,
        D: int = D_CELL_SIZE,
        k: int = K_CELLS_BLOB,
        n: int = N_CELLS_EXT,
    ):
        self.srs = srs
        self.domain = domain
        self.D = D
        self.k = k
        self.n = n
        self.prover = KZGProver(srs, domain, D)
        self.verifier = KZGVerifier(srs, domain, D)

    def commit(self, blob_data: list):
        # blob_data is D*k raw field elements — the actual data to commit to
        # We find the unique polynomial f of degree < D*k that evaluates to
        # each blob element at the corresponding domain point
        assert (
            len(blob_data) == self.D * self.k
        ), (
            f"blob_data must have D*k={self.D * self.k} elements, "
            f"got {len(blob_data)}"
        )
        points = [self.domain.element(i) for i in range(self.D * self.k)]
        f = Poly.lagrange_interpolate(points, blob_data, self.domain.p)
        com = self.prover.commit(f)
        return com, f  # f is the state — keep it for opening cells later

    def open(self, state: Poly, cell_index: int):
        return self.prover.multi_open(state, cell_index)

    def verify(
        self, commitment, cell_index: int, cell_values: list, proof
    ) -> bool:
        return self.verifier.multi_verify(
            commitment, cell_index, cell_values, proof
        )


# reconstruct_extended_blob recovers all n*D evaluations when
# some cells are missing
# You need at least k cells (half the extended blob) to reconstruct
def reconstruct_extended_blob(
    domain: RootsOfUnity,
    cells: dict,
    D: int = D_CELL_SIZE,
    k: int = K_CELLS_BLOB,
    n: int = N_CELLS_EXT,
) -> list:
    # cells is a dict: {cell_index -> [D field elements]}
    p = domain.p
    m = domain.m
    assert m == n * D, f"domain size {m} must equal n*D = {n*D}"
    assert (
        len(cells) >= k
    ), f"Need at least k={k} cells to reconstruct, got {len(cells)}"

    # Work out which individual positions are missing
    available_positions = set()
    for cell_idx, cell_vals in cells.items():
        for i in range(D):
            available_positions.add(cell_idx * D + i)
    missing = [i for i in range(m) if i not in available_positions]

    # Z(X) = product of (X - omega_tilde_i) for every missing position i
    # Build it by multiplying in one linear factor at a time
    Z_coeffs = [1]
    for pos in missing:
        point = domain.element(pos)
        new_Z = [0] * (len(Z_coeffs) + 1)
        for j, c in enumerate(Z_coeffs):
            new_Z[j + 1] = (new_Z[j + 1] + c) % p
            new_Z[j] = (new_Z[j] - c * point) % p
        Z_coeffs = new_Z

    Z_padded = Z_coeffs + [0] * (m - len(Z_coeffs))  # pad to length m for FFT
    Z_eval = domain.fft(Z_padded)  # Z in evaluation form over H

    # e is the known evaluations with zeros in the missing slots
    e = [0] * m
    for cell_idx, cell_vals in cells.items():
        for i, val in enumerate(cell_vals):
            e[cell_idx * D + i] = int(val) % p

    # E(X) interpolates e — it agrees with f where data exists, but is wrong
    # at the missing positions because we put zeros there instead
    E_coeffs = domain.ifft(e)

    # E(X)*Z(X) cancels the wrong values: at available points Z = 0 so the
    # product equals 0; at missing points E is wrong but Z is also 0 on H
    # so the product is still 0. P(X) = E(X) is recovered by dividing out Z
    E_eval = domain.fft(E_coeffs)
    EZ_eval = [(E_eval[i] * Z_eval[i]) % p for i in range(m)]
    EZ_coeffs = domain.ifft(EZ_eval)

    # We can't divide by Z in evaluation form over H because Z is zero there
    # Instead evaluate both over the coset 7*H where Z is nonzero, divide
    # pointwise, then interpolate back to get P(X) = (E*Z)(X) / Z(X)
    beta = 7  # 7 is not a root of unity of any relevant order for BLS12-381

    EZ_coset = domain.coset_fft(EZ_coeffs, beta)
    Z_coset = domain.coset_fft(Z_padded, beta)
    P_coset = [EZ_coset[i] * pow(Z_coset[i], p - 2, p) % p for i in range(m)]
    P_coeffs = domain.coset_ifft(P_coset, beta)

    # Evaluate P over H to get all n*D recovered field elements
    return domain.fft(P_coeffs)


# CCfull handles the full PeerDAS matrix: ell blobs stacked as rows,
# opened and verified column by column
class CCfull:
    def __init__(
        self,
        srs: SRS,
        domain: RootsOfUnity,
        ell: int,
        D: int = D_CELL_SIZE,
        k: int = K_CELLS_BLOB,
        n: int = N_CELLS_EXT,
    ):
        self.ell = ell  # number of blob rows
        self.n = n
        self.ccrow = CCrow(srs, domain, D, k, n)
        self.verifier = self.ccrow.verifier

    def commit(self, blobs: list):
        # blobs is a list of ell raw blob data arrays
        assert len(blobs) == self.ell
        commitments, states = [], []
        for blob_data in blobs:
            com, st = self.ccrow.commit(blob_data)
            commitments.append(com)
            states.append(st)
        return commitments, states

    def open(self, states: list, col_index: int):
        # Open the same column across every row, producing ell
        # cell+proof pairs
        cells, proofs = [], []
        for st in states:
            cv, pf = self.ccrow.open(st, col_index)
            cells.append(cv)
            proofs.append(pf)
        return cells, proofs

    def verify_column(
        self, commitments: list, col_index: int, cells: list, proofs: list
    ) -> bool:
        # Check each row's proof individually (2*ell pairings)
        assert len(commitments) == self.ell
        for com, cv, pf in zip(commitments, cells, proofs):
            if not self.ccrow.verify(com, col_index, cv, pf):
                return False
        return True

    def batch_verify(
        self,
        commitments: list,
        col_indices: list,
        row_indices: list,
        cells: list,
        proofs: list,
    ) -> bool:
        # Check any subset of (row, col) cell openings using only 2
        # pairings total
        return self.verifier.batch_verify(
            commitments, col_indices, row_indices, cells, proofs
        )

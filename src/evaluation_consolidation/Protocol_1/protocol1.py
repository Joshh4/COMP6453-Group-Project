"""
Protocol 1 — Multilinear Evaluation Reduction (CONDA, Section V-A).

Reduces a claim ``\\tilde{f}(\\vec{z}) = y`` to ``\\tilde{f}(\\vec{r}) = y_r`` for a
verifier-chosen random ``\\vec{r}``, using only univariate *linear* messages per round.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable, List, Sequence, Tuple

import galois as gl


class Protocol1Error(Exception):
    """Raised when an honest verifier rejects a prover message."""


@dataclass(frozen=True)
class LinearPoly:
    """
    Univariate linear polynomial l(X) = l(0) + X * (l(1) - l(0)) over the field.

    For multilinear ``\\tilde{f}``, the restriction ``\\tilde{f}(\\ldots, X, \\ldots)``
    to one free variable is always at most linear in ``X``.
    """

    l0: Any
    l1: Any

    def eval(self, x: Any) -> Any:
        return self.l0 + x * (self.l1 - self.l0)


class MultilinearExtension:
    """
    ``\\mu``-variate multilinear polynomial given by its values on ``{0,1}^\\mu``.

    Index ``mask`` encodes ``(b_0,\\ldots,b_{\\mu-1})`` with bit ``i`` of ``mask``
    equal to ``b_i`` (LSB = ``X_0``).
    """

    def __init__(self, values: Sequence[Any], field: Any):
        self._field = field
        vals = field(values)
        self._values = vals
        self.mu = vals.size.bit_length() - 1
        if vals.size != 1 << self.mu:
            raise ValueError("values length must be a power of two")

    @property
    def field(self) -> Any:
        return self._field

    @classmethod
    def from_hypercube_values(
        cls, values: Sequence[Any], field: Any
    ) -> MultilinearExtension:
        return cls(values, field)

    def evaluate(self, point: Sequence[Any]) -> Any:
        """Evaluate the MLE at ``point`` (``\\mu`` field elements)."""
        if len(point) != self.mu:
            raise ValueError("point length must equal mu")
        acc = self._field(0)
        one = self._field(1)
        for mask in range(1 << self.mu):
            eq = one
            for i in range(self.mu):
                bit = (mask >> i) & 1
                if bit:
                    eq = eq * point[i]
                else:
                    eq = eq * (one - point[i])
            acc = acc + self._values[mask] * eq
        return acc


def prover_first_message(
    f: MultilinearExtension, z: Sequence[Any]
) -> LinearPoly:
    """Step 1: ``l_1(X) = \\tilde{f}(X, z_2, \\ldots, z_\\mu)``."""
    gf = f.field
    z_rest = list(z[1:])
    p0 = [gf(0)] + z_rest
    p1 = [gf(1)] + z_rest
    return LinearPoly(f.evaluate(p0), f.evaluate(p1))


def prover_round_message(
    f: MultilinearExtension,
    z: Sequence[Any],
    r_prefix: Sequence[Any],
    round_index: int,
) -> LinearPoly:
    """
    Step 3b for round ``round_index`` in ``{2, \\ldots, \\mu}``:

    ``l_i(X) = \\tilde{f}(r_1,\\ldots,r_{i-1}, X, z_{i+1},\\ldots,z_\\mu)``.
    """
    mu = len(z)
    if not (2 <= round_index <= mu):
        raise ValueError("round_index must be in [2, mu]")
    if len(r_prefix) != round_index - 1:
        raise ValueError("r_prefix must have length i-1 for round i")
    gf = f.field
    z_tail = list(z[round_index:])
    p0 = list(r_prefix) + [gf(0)] + z_tail
    p1 = list(r_prefix) + [gf(1)] + z_tail
    return LinearPoly(f.evaluate(p0), f.evaluate(p1))


def protocol1_reduce(
    f: MultilinearExtension,
    z: Sequence[Any],
    y: Any,
    next_challenge: Callable[[], Any],
) -> Tuple[Tuple[Any, ...], Any]:
    """
    Run Protocol 1 with an honest prover and verifier that uses ``next_challenge``
    to sample challenges (interactive).

    Returns ``(\\vec{r}, y_r)`` with ``y_r = l_\\mu(r_\\mu)`` as in the paper.
    Completeness: for honest inputs, ``y_r = \\tilde{f}(\\vec{r})``.
    """
    mu = len(z)
    gf = f.field
    l1 = prover_first_message(f, z)
    if l1.eval(z[0]) != y:
        raise Protocol1Error("l_1(z_1) != y")

    prev = l1
    r_vec: List[Any] = []

    if mu == 1:
        r_mu = next_challenge()
        r_vec.append(r_mu)
        yr = prev.eval(r_mu)
        return (tuple(r_vec), yr)

    for i in range(2, mu + 1):
        r_im1 = next_challenge()
        r_vec.append(r_im1)
        curr = prover_round_message(f, z, r_vec[: i - 1], i)
        if prev.eval(r_im1) != curr.eval(z[i - 1]):
            raise Protocol1Error(f"round {i}: l_{{i-1}}(r_{{i-1}}) != l_i(z_i)")
        prev = curr

    r_mu = next_challenge()
    r_vec.append(r_mu)
    yr = prev.eval(r_mu)
    return (tuple(r_vec), yr)


def verify_consolidated_evaluation(
    f: MultilinearExtension,
    r_vec: Sequence[Any],
    yr: Any,
) -> bool:
    """Check ``y_r == \\tilde{f}(\\vec{r})`` (final PCS claim)."""
    if len(r_vec) != f.mu:
        return False
    return f.evaluate(r_vec) == yr

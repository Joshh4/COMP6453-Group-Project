"""Tests for CONDA Protocol 1 (multilinear evaluation reduction)."""

import galois as gl
import pytest

from src.evaluation_consolidation.Protocol_1.protocol1 import (
    MultilinearExtension,
    Protocol1Error,
    protocol1_reduce,
    verify_consolidated_evaluation,
)


def _rng_factory(GF):
    state = [3]

    def _next():
        state[0] = (state[0] * 7 + 11) % GF.order
        return GF(state[0])

    return _next


@pytest.mark.parametrize("mu", [1, 2, 3, 4])
def test_protocol1_completeness_random_mle(mu):
    GF = gl.GF(97)
    n = 1 << mu
    values = GF.Random(n, seed=40 + mu)
    f = MultilinearExtension(values, GF)
    point = GF([GF(i + 1) for i in range(mu)])
    y = f.evaluate(point)
    r_vec, yr = protocol1_reduce(f, point, y, _rng_factory(GF))
    assert verify_consolidated_evaluation(f, r_vec, yr)
    assert f.evaluate(r_vec) == yr


def test_protocol1_rejects_wrong_y():
    GF = gl.GF(17)
    mu = 2
    values = GF.Random(1 << mu, seed=1)
    f = MultilinearExtension(values, GF)
    z = GF([GF(3), GF(5)])
    y_wrong = GF(0)
    with pytest.raises(Protocol1Error):
        protocol1_reduce(f, z, y_wrong, _rng_factory(GF))

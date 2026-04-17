from itertools import zip_longest


"""
	For coefficients (a_0, ..., a_n),
	interpret this as

	a_0 + a_1 X + a_2 X^2 + ... + a_n X^n
"""


class Poly:
    def __init__(self, coeffs=[]):
        self._coeffs = (
            Poly._trim_trailing_zeros(coeffs) if len(coeffs) != 0 else [0]
        )

    def __str__(self):
        terms = []

        zero = self._coeffs[0] * 0

        for i, a in enumerate(self._coeffs):
            if a == zero:
                continue

            if i == 0:
                terms.append(f"{a}")
            elif i == 1:
                terms.append(f"{a} X")
            else:
                terms.append(f"{a} X^{i}")

        return " + ".join(terms) if terms else "0"

    def __repr__(self):
        return self.__str__()

    def __eq__(self, other):
        if not isinstance(other, Poly):
            return NotImplemented

        return self._coeffs == other._coeffs

    def __call__(self, x):
        y = self._coeffs[0] * 0

        for a in reversed(self._coeffs):
            y = y * x + a

        return y

    def __add__(self, other):
        if not isinstance(other, Poly):
            return NotImplemented

        zero = self._coeffs[0] * 0
        # fixed: was other._coeefs (typo)
        return Poly(
            [
                x + y
                for x, y in zip_longest(
                    self._coeffs, other._coeffs, fillvalue=zero
                )
            ]
        )

    def __sub__(self, other):
        if not isinstance(other, Poly):
            return NotImplemented

        zero = self._coeffs[0] * 0
        return Poly(
            [
                x - y
                for x, y in zip_longest(
                    self._coeffs, other._coeffs, fillvalue=zero
                )
            ]
        )

    def __mul__(self, other):
        if isinstance(other, Poly):
            zero = self._coeffs[0] * 0
            coeffs = [
                zero for _ in range(len(self._coeffs) + len(other._coeffs) - 1)
            ]

            for i, a in enumerate(self._coeffs):
                for j, b in enumerate(other._coeffs):
                    coeffs[i + j] += a * b

            return Poly(coeffs)

        if isinstance(other, int):
            return Poly([other * x for x in self._coeffs])

        return NotImplemented

    def __rmul__(self, other):
        # allows scalar * poly as well as poly * scalar
        return self.__mul__(other)

    @staticmethod
    def _trim_trailing_zeros(coeffs):
        if len(coeffs) == 0:
            return coeffs

        zero = coeffs[0] * 0

        while len(coeffs) > 1 and coeffs[-1] == zero:
            coeffs.pop()

        return coeffs

    @staticmethod
    def divmod(f, g, p=None):
        if not isinstance(f, Poly) or not isinstance(g, Poly):
            return NotImplemented

        # fixed: was returning plain list [0] instead of Poly([0])
        if f.deg() < g.deg():
            return Poly([0]), f

        zero = f._coeffs[0] * 0
        r = f._coeffs[:]
        q = [zero for _ in range(f.deg() - g.deg() + 1)]

        for i in reversed(range(g.deg(), f.deg() + 1)):
            if p is not None:
                # modular inverse of leading coefficient via Fermat's little theorem
                g_lead = int(g._coeffs[g.deg()]) % p
                coeff = int(r[i]) * pow(g_lead, p - 2, p) % p
            else:
                coeff = r[i] / g._coeffs[g.deg()]

            q[i - g.deg()] = coeff

            for j in range(g.deg() + 1):
                r[i - g.deg() + j] -= coeff * g._coeffs[j]
                if p is not None:
                    r[i - g.deg() + j] = int(r[i - g.deg() + j]) % p

        return Poly(q), Poly(r)

    @staticmethod
    def lagrange_interpolate(points, values, p=None):
        """
        Return the unique polynomial f of degree < n such that
        f(points[i]) == values[i] for all i.

        p: if given, all arithmetic is done mod p (required for KZG).
           p must be prime (used for modular inverse via Fermat's little theorem).
        """
        n = len(points)
        assert len(values) == n, (
            f"points and values must have the same length, "
            f"got {len(points)} and {len(values)}"
        )

        result = Poly([0])

        for i in range(n):
            # Build the i-th Lagrange basis polynomial L_i(X):
            #   numerator:   prod_{j != i} (X - points[j])
            #   denominator: prod_{j != i} (points[i] - points[j])
            num = Poly([1])
            for j in range(n):
                if j != i:
                    if p is not None:
                        num = num * Poly([-points[j] % p, 1])
                    else:
                        num = num * Poly([-points[j], 1])

            denom = 1
            for j in range(n):
                if j != i:
                    denom = denom * (points[i] - points[j])
                    if p is not None:
                        denom = denom % p

            if p is not None:
                denom_inv = pow(int(denom), p - 2, p)
                scalar = int(values[i]) * denom_inv % p
            else:
                scalar = values[i] / denom

            result = result + num * scalar

        if p is not None:
            return Poly([int(c) % p for c in result.coeffs()])
        return result

    def deg(self):
        return len(self._coeffs) - 1

    def coeffs(self):
        return self._coeffs

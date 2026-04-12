import galois
from itertools import zip_longest


"""
	For coefficients (a_0, ..., a_n),
	interpret this as

	a_0 + a_1 X + a_2 X^2 + ... + a_n X^n
"""
class Poly:
	def __init__(self, coeffs=[]):
		self._coeffs = Poly._trim_trailing_zeros(coeffs) if len(coeffs) != 0 else [0]

	def __str__(self):	
		terms = []

		zero = self._coeffs[0] * 0

		for i, a in enumerate(self._coeffs):
			if a == zero:
				continue

			if i == 0:
				terms.append(f'{a}')
			elif i == 1:
				terms.append(f'{a} X')
			else:
				terms.append(f'{a} X^{i}')

		return ' + '.join(terms) if terms else '0'

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
		return Poly([x + y for x, y in zip_longest(self._coeffs, other._coeefs, fillvalue=zero)])

	def __sub__(self, other):
		if not isinstance(other, Poly):
			return NotImplemented

		zero = self._coeffs[0] * 0
		return Poly([x - y for x, y in zip_longest(self._coeffs, other._coeffs, fillvalue=zero)])

	def __mul__(self, other):
		if isinstance(other, Poly):
			zero = self._coeffs[0] * 0
			coeffs = [zero for _ in range(len(self._coeffs) + len(other._coeffs) - 1)]

			for i, a in enumerate(self._coeffs):
				for j, b in enumerate(other._coeffs):
					coeffs[i + j] += a * b

			return Poly(coeffs)

		if isinstance(other, int):
			return Poly([other * x for x in self._coeffs])

		return NotImplemented

	@staticmethod
	def _trim_trailing_zeros(coeffs):
		if len(coeffs) == 0:
			return coeffs

		zero = coeffs[0] * 0

		while len(coeffs) > 1 and coeffs[-1] == zero:
			coeffs.pop()

		return coeffs

	@staticmethod
	def divmod(f, g):
		if not isinstance(f, Poly) or not isinstance(g, Poly):
			return NotImplemented

		if f.deg() < g.deg():
			return [0], f

		zero = f._coeffs[0] * 0

		r = f._coeffs[:]

		q = [zero for _ in range(f.deg() - g.deg() + 1)]

		for i in reversed(range(g.deg(), f.deg() + 1)):
			coeff = r[i] / g._coeffs[g.deg()]
			q[i - g.deg()] = coeff

			for j in range(g.deg() + 1):
				r[i - g.deg() + j] -= coeff * g._coeffs[j]

		return Poly(q), Poly(r)

	def deg(self):
		return len(self._coeffs) - 1

	def coeffs(self):
		return self._coeffs

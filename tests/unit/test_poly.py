import pytest
from src.reedsolomon.polynomial import Poly



# Test that a correct proof verifies successfully
def test_empty():
	p = Poly()
	q = Poly([0])

	assert p == q

def test_add():

	a = [1, 2, 3, 4]
	b = [6, 5, 4, 3]

	c = [i + j for i, j in zip(a, b)]

	p = Poly(a)
	q = Poly(b)

	f = Poly(c)
	
	assert p + q == f

def test_add_2():

	a = [1, 2]
	b = [6, 5, 4, 3]

	c = [7, 7, 4, 3]

	p = Poly(a)
	q = Poly(b)

	f = Poly(c)
	
	assert p + q == f

def test_add_3():

	a = []
	b = [6, 5, 4, 3]

	c = [6, 5, 4, 3]

	p = Poly(a)
	q = Poly(b)

	f = Poly(c)
	
	assert p + q == f

def test_sub():

	a = [1, 2, 3, 4]
	b = [6, 5, 4, 3]

	c = [i - j for i, j in zip(a, b)]

	p = Poly(a)
	q = Poly(b)

	f = Poly(c)
	
	assert p - q == f

def test_mul():

	a = [1, 2, 3, 4]
	b = [6, 5, 4, 3]

	c = [6, 17, 32, 50, 38, 25, 12]

	p = Poly(a)
	q = Poly(b)

	f = Poly(c)
	
	assert p * q == f

def test_mul_2():

	a = [1, 0, 0, -4]
	b = [0, -2, 1]

	c = [0, -2, 1, 0, 8, -4]

	p = Poly(a)
	q = Poly(b)

	f = Poly(c)
	
	assert p * q == f

def test_interpolate():
	f = Poly([6.0, 2.0, 6.0, -8.0, 0.0, 0.0, -2.0])

	points = [5, 6, 7, 8, -1, 0, 123]
	values = [f(x) for x in points]

	p = Poly.lagrange_interpolate(points, values)

	assert p.equal(f)

def test_interpolate_2():
	f = Poly([-10.0, -7.0, -5.0, 0.0, 0.0, 7.0, 43.0, 129.0])

	points = [2 * x for x in range(f.deg() + 1)]
	values = [f(x) for x in points]

	p = Poly.lagrange_interpolate(points, values)

	assert p.equal(f)

def test_interpolate_3():
	f = Poly([float(i) for i in range(10)])

	points = [2 * x - 7 for x in range(f.deg() + 1)]
	values = [f(x) for x in points]

	p = Poly.lagrange_interpolate(points, values)

	assert p.equal(f)

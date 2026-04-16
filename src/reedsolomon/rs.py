from block import Block

"""
	Reed Solomon encoding class.
"""
class RS:
	"""
		Create an RS class that encodes blocks of size k, expanding
		it to a block of size n.

		Parameters:
			k: the number of bytes in a block to be encoded
			n: the desired number of bytes in the expanded encoded block
	"""
	def __init__(self, k : int, n : int):

		field_order = 256

		if k < 1:
			raise ValueError(f'k must be a positive integer; k={k}')
		
		if n < 1:
			raise ValueError(f'n must be a positive integer; n={n}')

		if k > n:
			raise ValueError(f'k must be less than n; k={k}, n={n}')
		
		if n >= field_order:
			raise ValueError(f'n must be less than the field order; n={n}, field_order={field_order}')

		self.k = k
		self.n = n
		self.q = field_order

		gf = galois.GF(field_order)

		self.gf = gf

		self.eval_points = tuple(gf.primitive_element ** i for i in range(n))

	def __str__(self):
		return f'RS: k={self.k}, n={self.n}, q={self.q}'
	
	def __repr__(self):
		return self.__str__()

	def __eq__(self, other):
		if isinstance(other, RS):
			return self.k == other.k and self.n == other.n and self.gf == other.gf
		return NotImplemented

	"""
		Encode a block of size k, expanding it to size n

		Parameters:
			block: block to be encoded
		
		Returns:
			encoded block
	"""
	def encode(self, block : Block) -> Block:
		if len(block) != self.k:
			raise ValueError(f'Block size does not match k; len(block)={len(block)}, k={self.k}')

		# interpret the bytes as elements of the field GF(256)
		data_galois = self.gf(list(block.data()))

		out_arr = bytearray(self.n)

		for i in range(self.n):
			p = self.gf(0)
			x = self.eval_points[i]
			for j in reversed(range(self.k)):
				p = p * x + data_galois[j]
			out_arr[i] = int(p)

		out = Block(out_arr, self.n, block.underlying_len(), encoded=True)
		return out

	"""
		Decode a block, inverse of encode_block.

		Parameters:
			block: block to be decoded

		Returns:
			decoded block
	"""
	def decode(self, block : Block) -> Block:
		if len(block) < self.k:
			raise ValueError(f'block length must be larger than k; len(block)={len(block)}, k={self.k}')

		k_inputs = self.gf(self.eval_points[:self.k])
		k_outputs = self.gf(list(block._data[:self.k]))

		# using only k out of n points, interpolate the polynomial
		poly = galois.lagrange_poly(k_inputs, k_outputs)

		d = bytearray(poly.coeffs[::-1])
		d += bytearray(self.k - len(d))

		b = Block(d, self.k, block.underlying_len())

		return b
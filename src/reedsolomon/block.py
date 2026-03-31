
"""
	Block class that encapsulates a raw data string and data length

	This class acts as the input to Reed Solomon.
"""
class Block:
	"""
		Init block class

		Parameters:
			data: byte array to be held by the block
			block_len: intended length of the block, must be greater than
				len(data), will be padded with 0s to obtain this
				length
			underlying_len: length of the data prior to padding or encoding
			encoded: flag to indicate whether the block represents encoded
				or raw data

	"""
	def __init__(self, data : bytes, block_len : int, underlying_len : int=0, encoded : bool=False):
		if len(data) < underlying_len:
			raise ValueError(f'underlying_len must be at most len(data); len(data)={len(data)}, underlying_len={underlying_len}')

		if block_len < 1:
			raise ValueError(f'block_len must be a positive integer; block_len={block_len}')

		if block_len < len(data):
			raise ValueError(f'block_len must be greater than len(data); block_len={block_len}, len(data)={len(data)}')

		self._data = data + bytes(block_len - len(data))
		self._underlying_len = len(data) if underlying_len <= 0 else underlying_len
		self._encoded = encoded

	"""
		Return the length of the data.
	"""
	def __len__(self):
		return len(self._data)

	def __str__(self):
		return f'data={self._data}, _underlying_len={self._underlying_len}'
	
	def __repr__(self):
		return self.__str__()
	
	def __eq__(self, other):
		if isinstance(other, Block):
			return self._data == other.data and self.length == other.length
		return NotImplemented

	"""
		Extract the underlying data of the block.
		
		Cases:
			self.encoded == True:
				Return all data as we want to
				see redundancies
			self.encoded == False:
				Return the unpadded original data.

		Returns:
			data in bytes
	"""
	def data(self) -> bytes:
		if self._encoded:
			return self._data
		return self._data[:self._underlying_len]
	
	def underlying_len(self) -> int:
		return self._underlying_len

	"""
		Helper function to transform a stream of data into a tuple of blocks

		Parameters:
			data: byte array to be transformed into a list of blocks
			block_len: the length of each block after padding
		Returns:
			A tuple of blocks, only the final block in the tuple will
			have padding
	"""
	@staticmethod
	def create_block_list(data : bytes, block_len : int):
		if block_len < 1:
			raise ValueError(f'block_len must be a positive integer; block_len={block_len}')

		block_arr = []

		i = 0
		while i < len(data):
			sub_data = data[i : min(i + block_len, len(data))]
			b = Block(sub_data, block_len)
			block_arr.append(b)
			i += block_len

		return tuple(block_arr)

from block import Block
from rs import RS

def extract_data(blocks : tuple[Block]) -> bytearray:
	data = b''
	for block in blocks:
		data += block.data()

	return data

def encode_data(rs : RS, data : bytearray) -> tuple[Block]:
	lst = Block.create_block_list(data, rs.k)
	lst_encoded = tuple(rs.encode(block) for block in lst)
	return lst_encoded

def decode_data(rs : RS, lst : tuple[Block]) -> bytearray:
	lst_decoded = tuple(rs.decode(block) for block in lst)
	data_decoded = extract_data(lst_decoded)
	return data_decoded

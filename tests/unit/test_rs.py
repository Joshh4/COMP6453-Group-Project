import pytest
from src.reedsolomon.block import Block
from src.reedsolomon.rs import RS
import src.reedsolomon.encode as encode


# Test that encode and decode are exact inverses
def test_encode_decode_block():
    msg = b"this is my message!"

    # we set the block length to be the same as the message
    k = len(msg)

    # set the expansion to be 10 bytes more than the message
    n = k + 10

    block = Block(msg, k, len(msg))

    rs = RS(k, n)

    msg_enc = rs.encode(block)
    msg_dec = rs.decode(msg_enc)

    msg_dec_data = msg_dec.data()

    assert msg_dec_data == msg


# Test that encode and decode are exact inverses
def test_encode_decode_block_2():
    msg = b"akskhdgaksjdhga"

    # we set the block length to be the same as the message
    k = len(msg)

    # set the expansion to be 10 bytes more than the message
    n = k + 10

    block = Block(msg, k, len(msg))

    rs = RS(k, n)

    msg_enc = rs.encode(block)
    msg_dec = rs.decode(msg_enc)

    msg_dec_data = msg_dec.data()

    assert msg_dec_data == msg

    # Test that encode and decode are exact inverses


def test_encode_decode_block_3():
    msg = bytes([i for i in range(100)])

    # we set the block length to be the same as the message
    k = len(msg)

    # set the expansion to be 10 bytes more than the message
    n = k + 10

    block = Block(msg, k, len(msg))

    rs = RS(k, n)

    msg_enc = rs.encode(block)
    msg_dec = rs.decode(msg_enc)

    msg_dec_data = msg_dec.data()

    assert msg_dec_data == msg


# Test that encode and decode are exact inverses
def test_encode_decode_block_padded():
    msg = b"abcdefghijk"

    # we set the block length to be the message len plus 10
    k = len(msg) + 10

    # set the expansion to be 2x bytes more than the message
    n = 2 * k

    block = Block(msg, k, len(msg))

    rs = RS(k, n)

    msg_enc = rs.encode(block)
    msg_dec = rs.decode(msg_enc)

    msg_dec_data = msg_dec.data()

    assert msg_dec_data == msg


# Test that encode and decode are exact inverses
def test_encode_decode_block_padded_2():
    msg = b"akskhdgaksjdhga"

    k = 2 * len(msg)
    n = k + 50

    block = Block(msg, k, len(msg))

    rs = RS(k, n)

    msg_enc = rs.encode(block)
    msg_dec = rs.decode(msg_enc)

    msg_dec_data = msg_dec.data()

    assert msg_dec_data == msg


# Test that encode and decode are exact inverses
def test_encode_decode_block_padded_3():
    msg = bytes([i for i in range(100)])

    k = 2 * len(msg)
    n = k + 50

    block = Block(msg, k, len(msg))

    rs = RS(k, n)

    msg_enc = rs.encode(block)
    msg_dec = rs.decode(msg_enc)

    msg_dec_data = msg_dec.data()

    assert msg_dec_data == msg


# Test that encode and decode are exact inverses
def test_encode_decode_raw_data():
    msg = b"this is my message!"

    # we set the block length to be the same as the message
    k = len(msg)

    # set the expansion to be 10 bytes more than the message
    n = k + 10

    rs = RS(k, n)

    msg_blocks = encode.encode_data(rs, msg)
    msg_dec = encode.decode_data(rs, msg_blocks)

    assert msg_dec == msg


def test_encode_decode_raw_data_2():
    msg = bytes([i for i in range(100)])

    k = len(msg) // 2

    n = k + 67

    rs = RS(k, n)

    msg_blocks = encode.encode_data(rs, msg)
    msg_dec = encode.decode_data(rs, msg_blocks)

    assert msg_dec == msg


def test_encode_decode_raw_data_3():
    msg = bytes([i for i in range(100)])

    k = len(msg) // 10
    n = 2 * k

    rs = RS(k, n)

    msg_blocks = encode.encode_data(rs, msg)
    msg_dec = encode.decode_data(rs, msg_blocks)

    assert msg_dec == msg

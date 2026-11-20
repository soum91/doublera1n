#!/usr/bin/env python3
"""Offline size/round-trip audit only; never emits firmware or touches USB.

DBZBLK01 is an experimental HOST format, not supported by current Pico firmware.
Independent blocks bound decoder output to 32 KiB. The portable C reader is
host-tested; target linking, board mapping and physical validation are pending.
"""
import argparse
import json
from pathlib import Path
import struct
import zlib

try:
    from .verify_uf2_for_board import inspect_uf2
except ImportError:
    from verify_uf2_for_board import inspect_uf2

HEADER = struct.Struct('<8s6I')
RECORD = struct.Struct('<3I')
MAGIC = b'DBZBLK01'
BLOCK = 32768
RAW = 0x80000000
STAGE_BYTES = 2842448


def extract_stage(path):
    """Validate UF2 framing, original first-stage length and CRC; keep bytes private.

    This checks transport integrity, NOT firmware authenticity or device binding.
    """
    report = inspect_uf2(path)
    family = int(report['main_family'], 16)
    blocks = {}
    data = path.read_bytes()
    for offset in range(0, len(data), 512):
        block = data[offset:offset + 512]
        fields = struct.unpack_from('<8I', block)
        if fields[7] == family:
            blocks[fields[3]] = block[32:288]
    header = blocks.get(0x10100000, b'')
    if header[:8] != b'L8BOOT01':
        raise ValueError('missing original boot image header')
    length, crc = struct.unpack_from('<II', header, 8)
    if length != STAGE_BYTES:
        raise ValueError('unexpected first-stage size')
    try:
        stage = b''.join(blocks[a] for a in range(
            0x10100100, 0x10100100 + length, 256))[:length]
    except KeyError as error:
        raise ValueError('missing first-stage flash block') from error
    if zlib.crc32(stage) != crc:
        raise ValueError('first-stage CRC mismatch')
    return stage


def pack_blocks(raw):
    if not raw or len(raw) > STAGE_BYTES:
        raise ValueError('invalid input length')
    records = []
    for start in range(0, len(raw), BLOCK):
        chunk = raw[start:start + BLOCK]
        encoded = zlib.compress(chunk, 9)
        stored_raw = len(encoded) >= len(chunk)
        payload = chunk if stored_raw else encoded
        flags_size = len(payload) | (RAW if stored_raw else 0)
        records.append(RECORD.pack(flags_size, len(chunk), zlib.crc32(chunk)) + payload)
    return HEADER.pack(MAGIC, 1, len(raw), BLOCK, len(records), zlib.crc32(raw), 0) + b''.join(records)


def unpack_blocks(data):
    """Yield bounded decoded blocks; reject truncation, corruption and extra bytes.

    Consumers must exhaust this generator for the whole-image check to run.
    A hardware reader must validate a full pass BEFORE performing USB writes.
    """
    if len(data) < HEADER.size:
        raise ValueError('truncated header')
    magic, version, length, block_size, count, expected_crc, reserved = HEADER.unpack_from(data)
    if (magic != MAGIC or version != 1 or reserved or block_size != BLOCK or
            not 0 < length <= STAGE_BYTES or count != (length + BLOCK - 1) // BLOCK):
        raise ValueError('invalid header')
    offset, total, crc = HEADER.size, 0, 0
    for index in range(count):
        if offset + RECORD.size > len(data):
            raise ValueError('truncated block record')
        flags_size, out_size, block_crc = RECORD.unpack_from(data, offset)
        offset += RECORD.size
        size = flags_size & ~RAW
        expected_size = min(BLOCK, length - total)
        if out_size != expected_size or not 0 < size <= BLOCK or offset + size > len(data):
            raise ValueError('invalid block lengths')
        payload = data[offset:offset + size]
        offset += size
        if flags_size & RAW:
            chunk = payload
        else:
            decoder = zlib.decompressobj()
            try:
                chunk = decoder.decompress(payload, out_size + 1)
            except zlib.error as error:
                raise ValueError('invalid compressed block') from error
            if not decoder.eof or decoder.unused_data or decoder.unconsumed_tail:
                raise ValueError('incomplete or oversized compressed block')
        if len(chunk) != out_size or zlib.crc32(chunk) != block_crc:
            raise ValueError('block integrity mismatch')
        total += len(chunk)
        crc = zlib.crc32(chunk, crc)
        yield chunk
    if offset != len(data) or total != length or crc != expected_crc:
        raise ValueError('whole-image integrity mismatch')


def audit(stage):
    packed = pack_blocks(stage)
    position = 0
    for chunk in unpack_blocks(packed):
        if chunk != stage[position:position + len(chunk)]:
            raise ValueError('round-trip mismatch')
        position += len(chunk)
    capacity = 2 * 1024 * 1024
    return {'raw_bytes': len(stage), 'block_bytes': BLOCK,
            'packed_bytes_including_headers': len(packed),
            'round_trip': 'PASS',
            'remaining_for_firmware_and_metadata': capacity - len(packed),
            'remaining_with_128k_firmware_and_256b_metadata': capacity - 131072 - 256 - len(packed),
            'firmware_reservation': '128 KiB is hypothetical; no target link performed',
            'embedded_decoder': 'portable C reader available; target link NOT TESTED',
            'hardware_boot': 'NOT TESTED'}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--uf2', type=Path, required=True)
    args = parser.parse_args()
    try:
        print(json.dumps(audit(extract_stage(args.uf2)), indent=2))
    except (ValueError, OSError, struct.error) as error:
        parser.exit(1, 'STOP: ' + str(error) + '\n')


if __name__ == '__main__':
    main()

"""Create and apply the same-size BPS deltas produced by this project."""

import argparse
import hashlib
import mmap
from pathlib import Path
import os
import struct
import tempfile
import zlib

SECTOR = 2048
BASE_SIZE = 382828544
BASE_SHA256 = '8a3541f6185a781a738e162fda8147dcaa436a757914a134a53f4ea662808b06'
CHUNK = 4 * 1024 * 1024


def check_base(source):
    if len(source) != BASE_SIZE or hashlib.sha256(source).hexdigest() != BASE_SHA256:
        raise ValueError(f'Base ISO mismatch. Expected {BASE_SIZE} bytes and SHA-256 {BASE_SHA256}')


def number(value):
    encoded = bytearray()
    while value >= 128:
        encoded.append(value & 127)
        value = (value >> 7) - 1
    encoded.append(value | 128)
    return encoded


def read_number(data, pos, end):
    value = 0
    scale = 1
    for _ in range(9):
        if pos >= end:
            break
        byte = data[pos]
        pos += 1
        value += (byte & 127) * scale
        if byte & 128:
            return value, pos
        scale <<= 7
        value += scale
    raise ValueError('Invalid BPS number')


def encode_patch(source, edits):
    patch = bytearray(b'BPS1') + number(len(source)) * 2 + number(0)
    cursor = 0
    target_crc = 0
    target_hash = hashlib.sha256()

    def add_unchanged(end):
        nonlocal target_crc
        if end > cursor:
            patch.extend(number((end - cursor - 1) << 2))
        for start in range(cursor, end, CHUNK):
            data = source[start:min(start + CHUNK, end)]
            target_crc = zlib.crc32(data, target_crc)
            target_hash.update(data)

    for offset, data in sorted(edits):
        if not data or not cursor <= offset <= len(source) - len(data):
            raise ValueError('Empty, overlapping, or out-of-range ISO edit')
        add_unchanged(offset)
        patch.extend(number(((len(data) - 1) << 2) | 1))
        patch.extend(data)
        target_crc = zlib.crc32(data, target_crc)
        target_hash.update(data)
        cursor = offset + len(data)
    add_unchanged(len(source))
    patch.extend(struct.pack('<II', zlib.crc32(source), target_crc))
    patch.extend(struct.pack('<I', zlib.crc32(patch)))
    return bytes(patch), target_hash.hexdigest()


def apply_patch(source, patch, output):
    if len(patch) < 19 or patch[:4] != b'BPS1':
        raise ValueError('Expected a BPS1 patch')
    end = len(patch) - 12
    source_crc, expected_crc, patch_crc = struct.unpack_from('<III', patch, end)
    if zlib.crc32(patch[:-4]) != patch_crc or zlib.crc32(source) != source_crc:
        raise ValueError('BPS checksum mismatch')
    source_size, pos = read_number(patch, 4, end)
    target_size, pos = read_number(patch, pos, end)
    metadata_size, pos = read_number(patch, pos, end)
    pos += metadata_size
    if source_size != len(source) or target_size != source_size or pos > end:
        raise ValueError('Unexpected BPS sizes')

    cursor = 0
    crc = 0
    sha256 = hashlib.sha256()
    while pos < end:
        command, pos = read_number(patch, pos, end)
        length = (command >> 2) + 1
        mode = command & 3
        if cursor + length > target_size:
            raise ValueError('BPS action exceeds target size')
        if mode == 0:
            data, start = source, cursor
        elif mode == 1 and pos + length <= end:
            data, start = patch, pos
            pos += length
        else:
            raise ValueError('Unsupported or incomplete BPS action')
        for offset in range(start, start + length, CHUNK):
            chunk = data[offset:min(offset + CHUNK, start + length)]
            output.write(chunk)
            crc = zlib.crc32(chunk, crc)
            sha256.update(chunk)
        cursor += length
    if cursor != target_size or crc != expected_crc:
        raise ValueError('Patched ISO checksum mismatch')
    return sha256.hexdigest()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('base', type=Path, help='Unmodified ULJS00374 ISO')
    parser.add_argument('patch', type=Path, help='Project .bps file')
    parser.add_argument('output', type=Path, help='New patched ISO path')
    args = parser.parse_args()
    temp = None
    try:
        if args.output.exists():
            raise ValueError(f'Output already exists: {args.output}')
        patch = args.patch.read_bytes()
        with args.base.open('rb') as source, mmap.mmap(source.fileno(), 0, access=mmap.ACCESS_READ) as iso:
            check_base(iso)
            with tempfile.NamedTemporaryFile(dir=args.output.parent, delete=False) as target:
                temp = Path(target.name)
                target_hash = apply_patch(iso, patch, target)
        os.link(temp, args.output)
    except (ValueError, OSError, struct.error) as exc:
        parser.exit(1, f'{exc}\n')
    finally:
        if temp is not None:
            temp.unlink()
    print(f'ISO SHA-256 {target_hash}')


if __name__ == '__main__':
    main()

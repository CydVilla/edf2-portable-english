"""Replace display strings in the verified ULJS00374 ELF and game script."""

import hashlib
import json
from pathlib import Path
import re
import struct
import subprocess
import tempfile
import unicodedata

PROJECT = Path(__file__).resolve().parent
ELF_SHA256 = '2eb8238073260d9ac14c9f0f99b23192eef6adea1fbe2f3f13390804d292ce83'
SCRIPT_SHA256 = '2c1e02f296d88cb9bffe3c966cca9f502cbef2bffc933f70778bc68b63e07ab8'
WEAPON_RECORD = re.compile(rb'Weapon\\([\w-]+)\.Vob\0+([^\0]{2,100})\0', re.I)
FORMAT = re.compile(rb'%(?:%|[0-9]*[dsuf])')

# These display names have smaller slots in the executable than in the detail panel.
SHORT_WEAPON_NAMES = {
    'MISSILELAUNCHER025': 'Sky Turtle Proto',
    'MISSILELAUNCHER024': 'Sky Turtle Proto Beta',
    'FLAMETHROWER025': 'Flamer',
    'FLAMETHROWER045': 'Scorch Gun',
    'ENERGY_CLUSTERBEAM02': 'Pandora C',
    'ENERGY_CLUSTERBEAM03': 'Pandora B',
    'ENERGY_CLUSTERBEAM04': 'Pandora A',
}


def manifest_offsets(filename):
    return {int(key, 16): label
            for key, label in json.loads((PROJECT / filename).read_text()).items()}


def write_strings(original, labels, aligned):
    result = bytearray(original)
    previous_end = 0
    for start, label in sorted(labels.items()):
        if start < previous_end or (aligned and start % 4):
            raise ValueError(f'Invalid display-string offset {start:#x}')
        end = original.index(b'\0', start)
        limit = (end + 4) & ~3 if aligned else end + 1
        old = original[start:end]
        new = label.encode('ascii')
        if not old or not new or len(new) >= limit - start or any(original[end:limit]):
            raise ValueError(f'Display string exceeds its slot at {start:#x}: {label!r}')
        if FORMAT.findall(old) != FORMAT.findall(new):
            raise ValueError(f'Display string changes format arguments at {start:#x}')
        result[start:limit] = new.ljust(limit - start, b'\0')
        previous_end = limit
    return bytes(result)


def translate_sequence(original):
    if hashlib.sha256(original).hexdigest() != SCRIPT_SHA256:
        raise ValueError('Unexpected GAMESEQUENCE.BVM checksum')
    return write_strings(original, manifest_offsets('sequence-v04.json'), aligned=False)


def executable_labels(elf):
    labels = manifest_offsets('executable-v04.json')
    names = json.loads((PROJECT / 'weapon-names-v03.json').read_text())
    weapon_offsets = {}
    for match in WEAPON_RECORD.finditer(elf, 0x1a4f00, 0x1a8f2c):
        original = unicodedata.normalize('NFKC', match[2].decode('cp932', errors='replace'))
        if not original.isprintable() or '\ufffd' in original:
            continue
        key = match[1].decode('ascii').upper()
        start = match.start(2)
        if key in weapon_offsets or start in labels:
            raise ValueError(f'Duplicate weapon display slot for {key}')
        weapon_offsets[key] = start
    if weapon_offsets.keys() != names.keys():
        raise ValueError('Unexpected weapon name table')
    labels.update({start: SHORT_WEAPON_NAMES.get(key, names[key])
                   for key, start in weapon_offsets.items()})
    return labels


def translate_executable(original, tool):
    with tempfile.TemporaryDirectory(prefix='edf2p-eboot-') as scratch:
        encrypted = Path(scratch) / 'eboot.bin'
        decrypted = Path(scratch) / 'eboot.elf'
        encrypted.write_bytes(original)
        subprocess.run([str(tool.resolve()), str(encrypted), str(decrypted)], check=True)
        elf = decrypted.read_bytes()
    if hashlib.sha256(elf).hexdigest() != ELF_SHA256:
        raise ValueError('Unexpected decrypted EBOOT checksum')
    return write_strings(elf, executable_labels(elf), aligned=True)


def translate_iso_title(original, version='0.4'):
    magic, _, key_table, value_table, count = struct.unpack_from('<4s4I', original)
    if magic != b'\0PSF':
        raise ValueError('Unexpected PARAM.SFO header')
    for index in range(count):
        entry = 20 + 16 * index
        key, kind, _, capacity, value = struct.unpack_from('<HHIII', original, entry)
        if original[key_table + key:key_table + key + 6] != b'TITLE\0':
            continue
        title = f'Earth Defense Force 2 Portable (English v{version})\0'.encode('ascii')
        start = value_table + value
        if kind != 0x0204 or len(title) > capacity or start + capacity > len(original):
            raise ValueError('Unexpected PARAM.SFO TITLE slot')
        result = bytearray(original)
        struct.pack_into('<I', result, entry + 4, len(title))
        result[start:start + capacity] = title.ljust(capacity, b'\0')
        return bytes(result)
    raise ValueError('Missing PARAM.SFO TITLE entry')

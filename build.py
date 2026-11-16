"""Build the native-asset BPS patch for the verified EDF2 Portable ISO."""

import argparse
from collections import defaultdict
import hashlib
import json
import mmap
from pathlib import Path
import re
import struct
import subprocess
import tempfile
import unicodedata

from bps import BASE_SIZE, SECTOR, check_base, encode_patch
from textures import (
    EXTRA_TEXTURES, HEADQUARTERS_TEXTURES, native_texture, opening_story, translate_label_texture,
)

PROJECT = Path(__file__).resolve().parent
JPN_LBA = 56512
JPN_OFFSET = JPN_LBA * SECTOR
JPN_SIZE = 35885056
USA_OFFSET = 142080 * SECTOR
USA_SIZE = 55074816
MISSION_INDEX = 'GAMESEQUENCE/MISSIONCOMMENTLISTTEXT.VFS'
DONOR_INDEX = 'GAMESEQUENCE/MISSIONCOMMENTLIST.VFS'
WEAPON_INDEX = 'WEAPON/WEAPONCOMMENTLIST.VFS'
STORY = 'GAMESEQUENCE/STORY00.TAE_TEXS'
INSTALL_OFFSET = 168976 * SECTOR
INSTALL_SIZE = 36445904
EBOOT_LBA = 576
EBOOT_SIZE = 2285536
SFO_OFFSET = 55568 * SECTOR
SFO_SIZE = 560
SEQUENCE = 'GAMESEQUENCE/GAMESEQUENCE.BVM'
EPILOGUE = 'GAMESEQUENCE/ENDTELOP.TAE_TEXS'
CREDITS = 'GAMESEQUENCE/ENDING.TAE_TEXS'


def sha256(data):
    return hashlib.sha256(data).hexdigest()


def archive_entries(data, unique=True):
    """Read VFS entries as (name, record, offset, stored size, decoded size)."""
    magic, count, table, _ = struct.unpack_from('<4sIII', data)
    if magic != b'VFS\0' or table != 16:
        raise ValueError('Unexpected VFS header')

    def name_at(offset):
        return data[offset:data.index(b'\0', offset)].decode('cp932')

    entries = {}
    for folder_record in range(table, table + count * 16, 16):
        name, count, first, _ = struct.unpack_from('<4I', data, folder_record)
        folder = name_at(folder_record + name).rstrip('\\')
        for record in range(first, first + count * 20, 20):
            stored, offset, name, decoded, flags = struct.unpack_from('<5I', data, record)
            path = folder + '/' + name_at(record + name)
            if flags or offset + stored > len(data) or (unique and path in entries):
                raise ValueError(f'Unexpected VFS entry for {path}')
            # Top-level archives have duplicates. Retain every record for extent checks.
            key = (path, record) if not unique else path
            entries[key] = (record, offset, stored, decoded)
    return entries


def unpack(data, entry):
    _, offset, stored, size = entry
    payload = data[offset:offset + stored]
    return decompress(payload, size) if size else payload


def decompress(payload, size):
    if int.from_bytes(payload[:4], 'little') != size:
        raise ValueError('Inconsistent LZSS size')
    ring = bytearray(4096)
    cursor = 0xFEE
    pos = 4
    output = bytearray()
    while len(output) < size:
        flags = payload[pos]
        pos += 1
        for bit in range(8):
            if len(output) == size:
                break
            if flags & (1 << bit):
                chunk = payload[pos:pos + 1]
                pos += 1
                output.extend(chunk)
                ring[cursor] = chunk[0]
                cursor = (cursor + 1) & 4095
            else:
                low, high = payload[pos:pos + 2]
                pos += 2
                ref = low | ((high & 0xF0) << 4)
                for i in range(3 + (high & 15)):
                    byte = ring[(ref + i) & 4095]
                    output.append(byte)
                    ring[cursor] = byte
                    cursor = (cursor + 1) & 4095
    if len(output) != size or pos != len(payload):
        raise ValueError('Inconsistent LZSS payload length')
    return bytes(output)


def compress(data):
    """Encode the game's LZSS dialect and check the result with the decoder."""
    prefix = 18
    padded = bytes(prefix) + data
    pos = prefix
    candidates = defaultdict(list)
    for start in range(prefix):
        candidates[padded[start:start + 3]].append(start)
    output = bytearray(struct.pack('<I', len(data)))
    while pos < len(padded):
        flag_position = len(output)
        output.append(0)
        for bit in range(8):
            if pos == len(padded):
                break
            longest = 2
            match = None
            limit = min(18, len(padded) - pos)
            for ref in reversed(candidates.get(padded[pos:pos + 3], [])[-64:]):
                if pos - ref > 4096:
                    break
                length = 3
                while length < limit and padded[ref + length] == padded[pos + length]:
                    length += 1
                if length > longest:
                    longest, match = length, ref
                if longest == limit:
                    break
            if match is None:
                output[flag_position] |= 1 << bit
                output.append(padded[pos])
                length = 1
            else:
                ring_offset = (0xFEE + match - prefix) & 4095
                output.extend((ring_offset & 255, ((ring_offset >> 4) & 0xF0) | (longest - 3)))
                length = longest
            for start in range(pos, pos + length):
                candidates[padded[start:start + 3]].append(start)
            pos += length
    compressed = bytes(output)
    if decompress(compressed, len(data)) != data:
        raise ValueError('LZSS round trip failed')
    return compressed


def normalized_text(payload):
    return ''.join(unicodedata.normalize('NFKC', payload.decode('cp932')).split())


def mission_text(original, donor, authored=None, layout=None):
    """Keep the Japanese index and change only text with a matching JP companion."""
    originals = archive_entries(original)
    donors = archive_entries(donor)
    result = bytearray(original)
    if authored is not None:
        clear_replaced_text(result, originals)
    updates = {}
    if layout is not None:
        from expanded_text import format_mission_text

    for name, entry in originals.items():
        if not re.fullmatch(r'MISSION\d{3}/(?:TITLE|COMMENT)\.TXT', name):
            raise ValueError(f'Unexpected mission entry {name}')
        translated = unpack(original, entry)
        companion = name.replace('.TXT', '_JP.TXT')
        if name in donors and companion in donors:
            donor_jp = unpack(donor, donors[companion])
            donor_en = unpack(donor, donors[name])
            if (normalized_text(translated) == normalized_text(donor_jp)
                    and re.search(r'[a-zA-Z]{2}', normalized_text(donor_en))):
                updates[name] = donor_en
        if authored is not None and name in authored:
            if name in updates:
                raise ValueError(f'Authored mission overlaps the verified donor: {name}')
            updates[name] = authored[name]
        if name in updates:
            if layout is not None:
                updates[name] = format_mission_text(name, updates[name], layout)
            append_text(result, entry, updates[name])
    if authored is not None and (updates.keys() != originals.keys() or not authored.keys() <= updates.keys()):
        raise ValueError('Expanded mission text does not cover the original mission index')
    rebuilt = bytes(result)
    rebuilt_entries = archive_entries(rebuilt)
    for name, entry in originals.items():
        expected = updates[name] if name in updates else unpack(original, entry)
        if unpack(rebuilt, rebuilt_entries[name]) != expected:
            raise ValueError(f'Mission text round trip failed for {name}')
    return rebuilt, list(updates)


def append_text(result, entry, payload):
    # Directory tables and payloads are interleaved. Append only new text.
    result.extend(bytes((-len(result)) % 16))
    struct.pack_into('<II', result, entry[0], len(payload), len(result))
    struct.pack_into('<I', result, entry[0] + 12, 0)
    result.extend(payload)


def clear_replaced_text(result, entries):
    """Release old text bytes inside an index whose entries will all be replaced."""
    for _, offset, stored, _ in entries.values():
        result[offset:offset + stored] = bytes(stored)


def expanded_weapons(original, donor, descriptions=None):
    from expanded_text import weapon_text

    authored = json.loads((PROJECT / 'weapons-v03.json').read_text())
    if descriptions is not None:
        authored.update(descriptions)
    names = json.loads((PROJECT / 'weapon-names-v03.json').read_text())
    original_entries = archive_entries(original)
    donor_entries = archive_entries(donor)
    result = bytearray(original)
    clear_replaced_text(result, original_entries)
    expected = {}
    for path, entry in original_entries.items():
        match = re.fullmatch(r'WEAPON/([A-Z0-9_-]+)\.TXT', path)
        if not match:
            raise ValueError(f'Unexpected weapon entry: {path}')
        value = unpack(donor, donor_entries[path]) if path in donor_entries else None
        expected[path] = weapon_text(
            unpack(original, entry), value, authored, match[1], names.get(match[1])
        )
        append_text(result, entry, expected[path])
    entries = archive_entries(result)
    if entries.keys() != original_entries.keys():
        raise ValueError('Expanded weapon archive changed its entry list')
    for path, entry in entries.items():
        if unpack(result, entry) != expected[path]:
            raise ValueError(f'Weapon text round trip failed for {path}')
    return bytes(result)


def plan_edits(jpn, usa, pack, manifest, text_enabled, expanded_menus=False, complete=False,
               localized=False, layout=None):
    records = archive_entries(jpn, unique=False)
    by_path = defaultdict(list)
    for (path, _), entry in records.items():
        by_path[path].append(entry)

    def one(name):
        if len(by_path[name]) != 1:
            raise ValueError(f'Expected one entry for {name}')
        return by_path[name][0]

    replacements = {}
    for name, spec in manifest.items():
        png = (pack / 'ui' / spec['png']).read_bytes()
        if sha256(png) != spec['sha256']:
            raise ValueError(f'PNG hash mismatch for {spec["png"]}')
        replacements[name] = native_texture(
            unpack(jpn, one(name)), png, spec['colors'], spec.get('warning_text')
        )
    if expanded_menus:
        for name in HEADQUARTERS_TEXTURES:
            replacements[name] = translate_label_texture(name, unpack(jpn, one(name)))
    if localized:
        from ending import translate_credits, translate_epilogue
        from localized_text import translate_sequence

        for name in EXTRA_TEXTURES:
            replacements[name] = translate_label_texture(name, unpack(jpn, one(name)))
        ending = json.loads((PROJECT / 'ending-v04.json').read_text())
        replacements[SEQUENCE] = translate_sequence(unpack(jpn, one(SEQUENCE)))
        replacements[EPILOGUE] = translate_epilogue(unpack(jpn, one(EPILOGUE)), ending['epilogue'])
        replacements[CREDITS] = translate_credits(unpack(jpn, one(CREDITS)), ending['credits'])
    updates = []
    if text_enabled:
        donor_entries = archive_entries(usa, unique=False)
        donor = [entry for (name, _), entry in donor_entries.items() if name == DONOR_INDEX]
        if len(donor) != 1:
            raise ValueError('Expected one donor mission index')
        authored = None
        if complete:
            from expanded_text import new_mission_lines

            authored = new_mission_lines(json.loads((PROJECT / 'missions-v03.json').read_text()))
        replacements[MISSION_INDEX], updates = mission_text(
            unpack(jpn, one(MISSION_INDEX)), unpack(usa, donor[0]), authored, layout
        )
        if complete:
            weapon_donor = [entry for (name, _), entry in donor_entries.items() if name == WEAPON_INDEX]
            if len(weapon_donor) != 1:
                raise ValueError('Expected one donor weapon index')
            replacements[WEAPON_INDEX] = expanded_weapons(
                unpack(jpn, one(WEAPON_INDEX)), unpack(usa, weapon_donor[0]),
                layout['weapons'] if layout is not None else None,
            )
            story_hashes = json.loads((PROJECT / 'story-v03.json').read_text())
            images = []
            for filename in ('story2.png', 'story1.png'):
                data = (pack / 'ui' / filename).read_bytes()
                if sha256(data) != story_hashes[filename]:
                    raise ValueError(f'PNG hash mismatch for {filename}')
                images.append(data)
            replacements[STORY] = opening_story(unpack(jpn, one(STORY)), images)

    # The caller verifies any additional sectors before extending the ISO file record.
    tail = len(jpn)
    _, folder_count, table, _ = struct.unpack_from('<4sIII', jpn)
    folder_tables = {
        struct.unpack_from('<I', jpn, record + 8)[0]
        for record in range(table, table + folder_count * 16, 16)
    }
    offsets = sorted({entry[1] for entry in records.values()} | folder_tables | {len(jpn)})
    limits = dict(zip(offsets, offsets[1:]))
    counts = defaultdict(int)
    for _, offset, _, _ in records.values():
        counts[offset] += 1
    placements = []
    spill = []
    free = []
    for name, data in replacements.items():
        record, offset, stored, _ = one(name)
        encoded = compress(data)
        if len(encoded) >= len(data):
            encoded = data
            decoded_size = 0
        else:
            decoded_size = len(data)
        extra = jpn[offset + stored:offset + len(encoded)] if len(encoded) > stored else b''
        in_place = counts[offset] == 1 and offset + len(encoded) <= limits[offset] and not any(extra)
        if complete and counts[offset] == 1 and offset % SECTOR == 0:
            # Only reuse sectors in the old allocation of a replaced entry.
            end = min(sector_ceil(offset + stored), limits[offset] // SECTOR * SECTOR)
            begin = sector_ceil(offset + len(encoded)) if in_place else offset
            if begin < end and not any(jpn[offset + stored:end]):
                free.append((begin, end))
        if in_place:
            placements.append((record, offset, encoded, decoded_size))
        else:
            spill.append((name, record, encoded, decoded_size))
    if complete:
        spill.sort(key=lambda item: -len(item[2]))
    for name, record, encoded, decoded_size in spill:
        amount = sector_ceil(len(encoded))
        if complete:
            available = [(end - begin, begin, i) for i, (begin, end) in enumerate(free)
                         if end - begin >= amount]
            if not available:
                raise ValueError(f'No free sector range for {name} ({len(encoded)} bytes)')
            _, offset, index = min(available)
            _, end = free[index]
            free[index] = (offset + amount, end)
        else:
            offset = tail
            tail += amount
        placements.append((record, offset, encoded, decoded_size))
    edits = []
    for record, offset, encoded, decoded_size in placements:
        edits.append((JPN_OFFSET + record, struct.pack('<II', len(encoded), offset)))
        edits.append((JPN_OFFSET + record + 12, struct.pack('<I', decoded_size)))
        edits.append((JPN_OFFSET + offset, encoded))
    return edits, tail, updates


def sector_ceil(size):
    return (size + SECTOR - 1) // SECTOR * SECTOR


def install_edits(iso, jpn, archive_edits, tool):
    original = iso[INSTALL_OFFSET:INSTALL_OFFSET + INSTALL_SIZE]
    translated = bytearray(jpn)
    for offset, data in archive_edits:
        start = offset - JPN_OFFSET
        if start < 0 or start + len(data) > len(translated):
            raise ValueError('Rebuilt archive does not fit the original Data Install package')
        translated[start:start + len(data)] = data
    with tempfile.TemporaryDirectory(prefix='edf2p-install-') as scratch:
        scratch = Path(scratch)
        paths = [scratch / name for name in ('original.pgd', 'original.vfs', 'translated.vfs', 'new.pgd')]
        for path, data in zip(paths, (original, jpn, translated)):
            path.write_bytes(data)
        subprocess.run([str(tool.resolve()), *(str(path) for path in paths)], check=True)
        updated = paths[-1].read_bytes()
    if len(updated) != len(original):
        raise ValueError('Unexpected rebuilt Data Install package length')
    # Only changed runs of encrypted blocks need to be present in the BPS.
    edits = []
    begin = None
    for pos in range(0, len(original), 1024):
        if original[pos:pos + 1024] != updated[pos:pos + 1024]:
            if begin is None:
                begin = pos
        elif begin is not None:
            edits.append((INSTALL_OFFSET + begin, updated[begin:pos]))
            begin = None
    if begin is not None:
        edits.append((INSTALL_OFFSET + begin, updated[begin:]))
    return edits


def iso_size_edit(iso, new_size, *, directory=53, name=b'EDF2.DAT',
                  lba=JPN_LBA, old_size=JPN_SIZE):
    start = directory * SECTOR
    record = start
    while record < start + SECTOR and iso[record]:
        length = iso[record]
        name_length = iso[record + 32]
        extent = iso[record + 2:record + 10]
        size = iso[record + 10:record + 18]
        if (
            iso[record + 33:record + 33 + name_length] == name
            and extent == struct.pack('<I', lba) + struct.pack('>I', lba)
            and size == struct.pack('<I', old_size) + struct.pack('>I', old_size)
        ):
            return record + 10, struct.pack('<I', new_size) + struct.pack('>I', new_size)
        record += length
    raise ValueError(f'Could not locate the original ISO file record for {name!r}')


def localization_iso_edits(iso, tool, version='0.4'):
    from localized_text import translate_executable, translate_iso_title

    start = EBOOT_LBA * SECTOR
    eboot = translate_executable(iso[start:start + EBOOT_SIZE], tool)
    if len(eboot) > EBOOT_SIZE:
        raise ValueError('Localized EBOOT exceeds the original extent')
    title = translate_iso_title(iso[SFO_OFFSET:SFO_OFFSET + SFO_SIZE], version)
    return [
        iso_size_edit(iso, len(eboot), directory=25, name=b'EBOOT.BIN',
                      lba=EBOOT_LBA, old_size=EBOOT_SIZE),
        (start, eboot.ljust(EBOOT_SIZE, b'\0')),
        (SFO_OFFSET, title),
    ]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('base', type=Path, help='Unmodified ULJS00374 ISO')
    parser.add_argument('texture_pack', type=Path, help='Downloaded ULJS00374 directory')
    parser.add_argument('patch', type=Path, help='New .bps output path')
    parser.add_argument('--ui-only', action='store_true', help='Exclude experimental mission text')
    parser.add_argument('--expanded-menus', action='store_true', help='Include the v0.2 menu translation')
    parser.add_argument('--complete', metavar='PGD_TOOL', type=Path,
                        help='Build v0.3 with expanded text, story, and translated Data Install')
    parser.add_argument('--localize', metavar='PRX_TOOL', type=Path,
                        help='Build v0.4, including executable text, ending, and remaining UI')
    parser.add_argument('--layout-polish', action='store_true',
                        help='Build v0.5 with shorter mission labels and reflowed briefings')
    args = parser.parse_args()
    if args.layout_polish and not args.localize:
        parser.error('--layout-polish requires --localize')
    if args.complete and args.ui_only:
        parser.error('--complete includes mission text and cannot be combined with --ui-only')
    if args.localize and not args.complete:
        parser.error('--localize requires --complete so Data Install includes the new translation')
    expanded_menus = args.expanded_menus or args.complete is not None
    try:
        layout = json.loads((PROJECT / 'layout-v05.json').read_text()) if args.layout_polish else None
        manifest = json.loads((PROJECT / 'textures.json').read_text())
        if expanded_menus:
            manifest.update(json.loads((PROJECT / 'textures-v02.json').read_text()))
        with args.base.open('rb') as source, mmap.mmap(source.fileno(), 0, access=mmap.ACCESS_READ) as iso:
            check_base(iso)
            jpn = iso[JPN_OFFSET:JPN_OFFSET + JPN_SIZE]
            usa = b'' if args.ui_only else iso[USA_OFFSET:USA_OFFSET + USA_SIZE]
            edits, new_size, updates = plan_edits(
                jpn, usa, args.texture_pack, manifest, not args.ui_only,
                expanded_menus, args.complete is not None, args.localize is not None, layout,
            )
            if new_size != JPN_SIZE:
                limit = 74048 * SECTOR
                end = JPN_OFFSET + new_size
                if end > limit or any(iso[JPN_OFFSET + JPN_SIZE:end]):
                    raise ValueError(f'Archive needs {new_size - JPN_SIZE} bytes of verified ISO padding; '
                                     f'at most {limit - JPN_OFFSET - JPN_SIZE} bytes are available')
                edits.append(iso_size_edit(iso, new_size))
            if args.complete:
                edits.extend(install_edits(iso, jpn, edits, args.complete))
            if args.localize:
                version = '0.5' if args.layout_polish else '0.4'
                edits.extend(localization_iso_edits(iso, args.localize, version))
            patch, target_hash = encode_patch(iso, edits)
        with args.patch.open('xb') as output:
            output.write(patch)
    except (ValueError, OSError, IndexError, ImportError, struct.error, subprocess.CalledProcessError) as exc:
        parser.exit(1, f'{exc}\n')
    print(f'Native textures   {len(manifest)}')
    if expanded_menus:
        print('HQ text textures  3')
    if args.complete:
        print('Weapon details    337')
        print('Story textures    2')
    if args.localize:
        print('Runtime names     328')
        print('Localized ending, credits, title, and additional interface text')
    print(f'Mission titles    {sum(name.endswith("/TITLE.TXT") for name in updates)}')
    print(f'Mission briefings {sum(name.endswith("/COMMENT.TXT") for name in updates)}')
    print(f'ISO size          {BASE_SIZE}')
    print(f'ISO SHA-256       {target_hash}')
    print(f'BPS SHA-256       {sha256(patch)}')


if __name__ == '__main__':
    main()

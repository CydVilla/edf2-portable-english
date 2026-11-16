"""Render end captions and staff credit labels in their original EFT slots."""

from itertools import groupby
import struct

from PIL import Image, ImageDraw, ImageFont

from textures import palette_slot

EFT_HEADER = struct.Struct('<4s6I')
TEXT_DIMENSION = 256
EFT_OFFSETS = {
    'epilogue': (0x30, 0x59150),
    'credits': (0x190, 0x10610, 0x20a90, 0x30f10, 0x41390, 0x51810, 0x61c90, 0x72110),
}


def decode_tiles(encoded, width, height):
    if width % 8 or height % 8:
        raise ValueError('Invalid EFT tile dimensions')
    out = bytearray(width * height)
    pos = 0
    for y in range(0, height, 8):
        for x in range(0, width, 8):
            first = encoded[pos]
            pos += 1
            if first != 0xBA:
                tile = bytes((first,)) * 64
            else:
                tile = bytearray()
                while len(tile) < 64:
                    code = encoded[pos]
                    pos += 1
                    count = code & 127
                    if not count or len(tile) + count > 64:
                        raise ValueError('Invalid EFT tile run')
                    if code & 128:
                        tile.extend(bytes((encoded[pos],)) * count)
                        pos += 1
                    else:
                        tile.extend(encoded[pos:pos + count])
                        pos += count
            for row in range(8):
                start = (y + row) * width + x
                out[start:start + 8] = tile[row * 8:row * 8 + 8]
    return bytes(out), pos


def encode_tiles(pixels, width, height):
    out = bytearray()
    for y in range(0, height, 8):
        for x in range(0, width, 8):
            tile = b''.join(pixels[(y + r) * width + x:(y + r) * width + x + 8]
                            for r in range(8))
            if len(set(tile)) == 1 and tile[0] != 0xBA:
                out.append(tile[0])
                continue
            out.append(0xBA)
            literal = bytearray()
            for value, group in groupby(tile):
                count = sum(1 for _ in group)
                if count < 3:
                    literal.extend(bytes((value,)) * count)
                    continue
                if literal:
                    out.extend(bytes((len(literal),)) + literal)
                    literal.clear()
                out.extend((128 | count, value))
            if literal:
                out.extend(bytes((len(literal),)) + literal)
    encoded = bytes(out)
    if decode_tiles(encoded, width, height) != (pixels, len(encoded)):
        raise ValueError('EFT tile round trip failed')
    return encoded


def eft_alpha(data, offset, end):
    magic, mode, w, h, clut, pixels, packed_size = EFT_HEADER.unpack_from(data, offset)
    if (magic, w, h) != (b'EFT\0', TEXT_DIMENSION, TEXT_DIMENSION):
        raise ValueError('Unexpected EFT text atlas')
    start = offset + pixels
    if (mode, clut, pixels, packed_size) == (1, 128, 1152, 0):
        indices = data[start:start + w * h]
        if start + len(indices) != end:
            raise ValueError('Unexpected raw EFT atlas length')
    elif (mode, clut, pixels) == (65537, 32, 1056):
        indices, consumed = decode_tiles(data[start:end], w, h)
        if consumed != packed_size or any(data[start + consumed:end]):
            raise ValueError('Unexpected compressed EFT atlas length')
    else:
        raise ValueError('Unsupported EFT text format')
    alpha = [min(255, data[offset + clut + 4 * palette_slot(i) + 3] * 2)
             for i in range(256)]
    return Image.frombytes('L', (w, h), bytes(alpha[i] for i in indices))


def store_alpha(result, offset, end, image, keep_palette=False):
    # Verify the original dimensions and its declared packed extent.
    eft_alpha(result, offset, end)
    _, mode, w, h, clut, pixels, _ = EFT_HEADER.unpack_from(result, offset)
    if image.size != (w, h):
        raise ValueError('EFT atlas dimensions changed')
    if keep_palette:
        palette = result[offset + clut:offset + clut + 1024]
        values = {
            palette[4 * palette_slot(i) + 3] * 2: i for i in range(256)
            if palette[4 * palette_slot(i):4 * palette_slot(i) + 3] == bytes((226,) * 3)
        }
        if len(values) != 16 or palette[3] != 0:
            raise ValueError('Unexpected EFT credit palette')
        values[0] = 0
        lookup = bytes(values[min(values, key=lambda v: abs(v - a))]
                       for a in range(256))
        indices = image.tobytes().translate(lookup)
    else:
        palette = bytearray(1024)
        for alpha in range(129):
            p = 4 * palette_slot(alpha)
            palette[p:p + 4] = bytes((255, 255, 255, alpha))
        indices = bytes((v + 1) // 2 for v in image.tobytes())
    payload = indices if mode == 1 else encode_tiles(indices, w, h)
    start = offset + pixels
    if start + len(payload) > end:
        raise ValueError(f'Translated EFT atlas overflows its slot at {offset:#x}')
    result[offset + clut:offset + clut + 1024] = palette
    result[start:end] = payload.ljust(end - start, b'\0')
    if mode == 65537:
        struct.pack_into('<I', result, offset + 24, len(payload))
    eft_alpha(result, offset, end)


def text_line(canvas, bounds, label, size):
    x, y, right, bottom = bounds
    draw = ImageDraw.Draw(canvas)
    draw.rectangle((x, y, right - 1, bottom - 1), fill=0)
    for size in range(size, 10, -1):
        font = ImageFont.load_default(size=size)
        l, t, r, b = font.getbbox(label)
        if r - l <= right - x - 6 and b - t <= bottom - y:
            draw.text((x + 3 - l, y + (bottom - y - (b - t)) // 2 - t),
                      label, font=font, fill=255)
            return
    raise ValueError(f'English ending label is too long: {label}')


def translate_epilogue(data, labels):
    if len(data) != 390272 or len(labels) != 10:
        raise ValueError('Unexpected end caption container')
    left, right = EFT_OFFSETS['epilogue']
    canvas = Image.new('L', (512, 256))
    for row, label in enumerate(labels):
        y = 2 + row * 25
        text_line(canvas, (0, y, 490, y + 23), label, 18)
    result = bytearray(data)
    store_alpha(result, left, 0x104b0, canvas.crop((0, 0, 256, 256)))
    store_alpha(result, right, len(data), canvas.crop((256, 0, 512, 256)))
    return bytes(result)


def translate_credits(data, pages):
    if len(data) != 3705120 or set(pages) != set('01234567'):
        raise ValueError('Unexpected credits container')
    result = bytearray(data)
    slots = (*EFT_OFFSETS['credits'], 0x78c30)
    for page, (offset, end) in enumerate(zip(slots, slots[1:])):
        image = eft_alpha(result, offset, end)
        for key, label in pages[str(page)].items():
            row = int(key.rstrip('LR'))
            y = round(row * 23.3)
            x, right = (0, 126) if key.endswith('L') else (
                (126, 256) if key.endswith('R') else (0, 256)
            )
            if page == 7 and row == 0:
                right = 148  # The first name begins farther right on this row.
            text_line(image, (x, y, right, min(256, y + 23)), label, 16)
        store_alpha(result, offset, end, image, keep_palette=True)
    return bytes(result)

"""Encode native TIM2 textures and render additional English menu labels."""

from functools import lru_cache
from io import BytesIO
import struct

from PIL import Image, ImageDraw, ImageFont

HEADING = 'EDF-BASE/FLAME_HEADQUARTERS.TM2'
STATS = 'SYS/FLAME_PLAYER_DATA.TM2'
HELP = 'EDF-BASE/EXPLANATION_UNDER.TM2'
HEADQUARTERS_TEXTURES = (HEADING, STATS, HELP)
GRENADE_TAB = 'EDF-BASE/HAND_GRENADE.TM2'
RESCUE_PROMPT = 'GAUGE/UI_01.TM2'
BATTLE_MODE = 'EDF-BASE/FLAME_BATTLE.TM2'
CONTROL_LEGEND = 'SYS/FLAME_CONTROL_INFO.TM2'
EQUIPMENT_LABELS = 'SYS/FLAME_EQUIP.TM2'
EXTRA_TEXTURES = (GRENADE_TAB, RESCUE_PROMPT, BATTLE_MODE, CONTROL_LEGEND, EQUIPMENT_LABELS)


def draw_label(tile, label, size, color, centered=False, stroke=0):
    font = ImageFont.load_default(size=size)
    left, top, right, bottom = font.getbbox(label, stroke_width=stroke)
    width, height = right - left, bottom - top
    if width > tile.width or height > tile.height:
        raise ValueError(f'English label exceeds its original tile: {label}')
    x = (tile.width - width) // 2 if centered else 0
    ImageDraw.Draw(tile).text(
        (x - left, (tile.height - height) // 2 - top), label, font=font,
        fill=color, stroke_width=stroke, stroke_fill=(30, 22, 9, 255),
    )


def warning_lines(panel, lines):
    font = ImageFont.load_default(size=12)
    draw = ImageDraw.Draw(panel)
    top = 7 + (3 - len(lines)) * 5
    for i, line in enumerate(lines):
        if font.getlength(line) > 251 or len(lines) > 3:
            raise ValueError(f'Warning text exceeds the original panel: {line}')
        draw.text((5, top + i * 11), line, font=font, fill=(38, 35, 30, 255), anchor='lt')
    return panel


def complete_warnings(image, page):
    if image.size != (512, 512):
        raise ValueError('Unexpected warning atlas dimensions')
    if page == 'save':
        # The last box in the pack is empty. It supplies clean art for both messages.
        empty = image.crop((0, 416, 267, 468))
        entries = {
            7: ('Insert storage media to save.', 'Save data requires 400 KB of free space.'),
            8: ('Storage is full. Delete data?', 'At least 400 KB is needed to save.'),
        }
    elif page == 'general':
        empty = image.crop((0, 416, 267, 468))
        entries = {
            1: ('This nickname will not display correctly.',),
            2: ('Your nickname was not applied.',),
            8: ('Data Install is now off.', 'Reinsert the media with installed data.'),
        }
        vertical = (
            ('Insert the storage media', 'that contains the installed data.'),
            ('Not enough Memory Stick space.', 'You need at least 400 KB to save.'),
            ('To add players, close this room', 'and create a new one.'),
            ('Storage may have been removed,', 'or the PSP may have entered sleep mode.', 'Autosave is now off.'),
        )
        for i, lines in enumerate(vertical):
            x = 269 + i * 52
            panel = image.crop((x, 139, x + 52, 406)).transpose(Image.Transpose.ROTATE_90)
            panel = warning_lines(panel, lines).transpose(Image.Transpose.ROTATE_270)
            image.paste(panel, (x, 139))
    else:
        raise ValueError(f'Unexpected warning atlas: {page}')
    for row, lines in entries.items():
        image.paste(warning_lines(empty.copy(), lines), (0, row * 52))


def translate_label_texture(name, original):
    width, height = tim2_dimensions(original)
    end = 64 + width * height
    pixels = bytearray(original[64:end])
    colors = [tuple(original[end + 4 * palette_slot(i):end + 4 * palette_slot(i) + 4])
              for i in range(256)]
    # Match only colors used in this texture. Some unused palette entries are blank.
    used = sorted(set(pixels))

    @lru_cache(maxsize=None)
    def nearest(color):
        return min(used, key=lambda i: sum((a - b) ** 2 for a, b in zip(color, colors[i])))

    def place(x, y, tile):
        if x + tile.width > width or y + tile.height > height:
            raise ValueError('English label exceeds its original atlas')
        data = list(tile.getdata())
        for row in range(tile.height):
            start = (y + row) * width + x
            region = data[row * tile.width:(row + 1) * tile.width]
            pixels[start:start + tile.width] = bytes(map(nearest, region))

    def label_on_strip(x, y, w, h, sample_x, label, size, color):
        tile = Image.new('RGBA', (w, h))
        tile.putdata([colors[pixels[row * width + sample_x]]
                      for row in range(y, y + h) for _ in range(w)])
        draw_label(tile, label, size, color, centered=True)
        place(x, y, tile)

    if name == HEADING and (width, height) == (256, 32):
        # Fill the old glyph area from clean blue strips on either side of the plaque.
        left = [colors[pixels[row * width + 34]] for row in range(17)]
        right = [colors[pixels[row * width + 114]] for row in range(17)]
        tile = Image.new('RGBA', (79, 17))
        tile.putdata([
            tuple((a * (78 - x) + b * x) // 78 for a, b in zip(l, r))
            for l, r in zip(left, right) for x in range(79)
        ])
        draw_label(tile, 'EDF HQ', 15, (255, 233, 155, 255), centered=True, stroke=1)
        place(35, 0, tile)
    elif name == STATS and (width, height) == (256, 64):
        # Keep the beveled border and leave room for the game-drawn numbers.
        for y, label in zip((3, 22, 41), ('Armor', 'Weapons Found', 'Completion')):
            # At the left bevel, erase only grayscale glyph pixels inside each row.
            for row in range(y, y + 13):
                for x in range(100):
                    pos = row * width + x
                    r, g, b, a = colors[pixels[pos]]
                    if r == g == b and a == 255:
                        pixels[pos] = 0
            tile = Image.new('RGBA', (93, 13), colors[0])
            draw_label(tile, label, 12, colors[4])
            place(7, y, tile)
    elif name == HELP and (width, height) == (512, 128):
        labels = (
            'Choose a mission and deploy.',
            'Choose up to two weapons.',
            'Save your progress.',
            'Change controls, sound, and other settings.',
            'Multiplayer.',
            'Return to title.',
        )
        for y, label in enumerate(labels):
            tile = Image.new('RGBA', (512, 16), colors[16])
            draw_label(tile, label, 13, colors[1])
            place(0, y * 16, tile)
    elif name == GRENADE_TAB and (width, height) == (256, 64):
        for y in (5, 35):
            # The unlettered vertical strip has the same gradient as the center.
            tile = Image.new('RGBA', (134, 20))
            tile.putdata([colors[pixels[row * width + 24]]
                          for row in range(y, y + 20) for _ in range(tile.width)])
            draw_label(tile, 'Hand Grenade', 17, (250, 244, 229, 128),
                       centered=True, stroke=1)
            place(26, y, tile)
    elif name == RESCUE_PROMPT and (width, height) == (256, 256):
        label_on_strip(70, 157, 133, 16, 70, 'Press SELECT to rescue', 12, (255, 244, 220, 128))
    elif name == BATTLE_MODE and (width, height) == (128, 128):
        for i, label in enumerate(('Co-op', 'Versus', 'Co-op', 'Versus')):
            label_on_strip(36, 2 + i * 20, 52, 15, 32, label, 14, (43, 22, 3, 128))
    elif name == CONTROL_LEGEND and (width, height) == (256, 32):
        for x, w, sample, label in (
            (51, 43, 90, 'Select'), (125, 44, 164, 'Confirm'), (199, 35, 232, 'Back')
        ):
            label_on_strip(x, 1, w, 16, sample, label, 12, (255, 255, 255, 128))
    elif name == EQUIPMENT_LABELS and (width, height) == (256, 256):
        labels = ('Class', 'Equip 1', 'Equip 2')
        color = (87, 49, 16, 128)
        for i, label in enumerate(labels):
            label_on_strip(183, 69 + i * 15, 50, 13, 182, label, 11, color)
        for i, label in enumerate((*labels, 'Mission', 'Armor', 'Vehicle Lv.', 'Map')):
            label_on_strip(173, 113 + i * 16, 67, 13, 172, label, 12, color)
    else:
        raise ValueError(f'Unexpected label texture: {name}')
    return original[:64] + bytes(pixels) + original[end:]


def tim2_dimensions(original):
    if original[:8] != b'TIM2\x04\x00\x01\x00':
        raise ValueError('Expected one TIM2 v4 image')
    _, palette_size, image_size, header, count, _, mips, clut_type, pixel_type, width, height = (
        struct.unpack_from('<IIIHHBBBBHH', original, 16)
    )
    if (palette_size, image_size, header, count, mips, clut_type, pixel_type) != (
        1024, width * height, 48, 256, 1, 3, 5
    ) or len(original) != 64 + image_size + palette_size:
        raise ValueError('Unexpected TIM2 format')
    return width, height


def palette_slot(index):
    return (index & ~24) | ((index & 8) << 1) | ((index & 16) >> 1)


def native_texture(original, png, colors, warning_text=None):
    width, height = tim2_dimensions(original)
    with Image.open(BytesIO(png)) as source:
        if source.format != 'PNG' or source.size != (width * 4, height * 4):
            raise ValueError('Expected 4× PNG with native atlas proportions')
        image = source.convert('RGBA').resize((width, height), Image.Resampling.LANCZOS)
    if warning_text is not None:
        complete_warnings(image, warning_text)
    if image.getextrema()[3] == (255, 255):
        indexed = image.convert('RGB').quantize(colors=colors, method=Image.Quantize.MEDIANCUT)
    else:
        indexed = image.quantize(colors=colors, method=Image.Quantize.FASTOCTREE)
    palette = indexed.getpalette('RGBA')
    palette += [0] * (1024 - len(palette))
    interleaved = bytearray(1024)
    for index in range(256):
        destination = palette_slot(index)
        interleaved[destination * 4:destination * 4 + 4] = palette[index * 4:index * 4 + 4]
    return original[:64] + indexed.tobytes() + interleaved


def opening_story(original, images):
    """Replace the two 256x256 text atlases in the original story container."""
    rebuilt = bytearray(original)
    if len(images) != 2 or len(original) != 1133792:
        raise ValueError('Unexpected opening story layout')
    for offset, png in zip((0x60, 0x104e0), images):
        header = struct.unpack_from('<4s6I', original, offset)
        if header != (b'EFT\0', 1, 256, 256, 128, 1152, 0):
            raise ValueError('Unexpected opening story texture')
        with Image.open(BytesIO(png)) as source:
            if source.format != 'PNG' or source.size != (512, 512):
                raise ValueError('Unexpected opening story PNG')
            image = source.convert('RGBA').resize((256, 256), Image.Resampling.LANCZOS)
        # Original EFT story textures use the PS2-style interleaved palette
        # and the 0..128 alpha scale. Preserve dimensions and texture indices.
        indexed = image.quantize(colors=128, method=Image.Quantize.FASTOCTREE)
        palette = indexed.getpalette('RGBA')
        packed_palette = bytearray(1024)
        for i in range(len(palette) // 4):
            r, g, b, a = palette[i * 4:i * 4 + 4]
            slot = 4 * palette_slot(i)
            packed_palette[slot:slot + 4] = bytes((r, g, b, (a + 1) // 2))
        rebuilt[offset + 128:offset + 1152] = packed_palette
        rebuilt[offset + 1152:offset + 1152 + 256 * 256] = indexed.tobytes()
    return bytes(rebuilt)

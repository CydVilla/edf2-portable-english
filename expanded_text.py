"""Build expanded English mission and weapon text from the pinned game archives."""

import re
import textwrap
import unicodedata

STAT_LABELS = {
    'ダメージ': 'Damage', '連射速度': 'Fire Rate', '有効射程距離': 'Range',
    '精度': 'Accuracy', '弾数': 'Ammo', '消費エネルギー': 'Energy Cost',
    'リロード時間': 'Reload Time', '爆破範囲': 'Blast Radius',
    'チャージ時間': 'Charge Time', 'ズーム': 'Zoom', '起爆条件': 'Fuse',
    '起爆時間': 'Fuse Time', '誘導性能': 'Homing', '集弾率': 'Grouping',
    '発射数': 'Shots', 'タイプ': 'Type', '回復量': 'Recovery', '噴霧数': 'Sprays',
}
VALUE_TERMS = {
    '発/秒': ' rounds/s', '半径': '', '秒': ' s', '倍': 'x',
    '×': 'x', '接触': 'Impact', '時間': 'Timed', '下方': 'Down',
    '上方': 'Up', '前方': 'Forward', '全方位': 'All directions', '特殊': 'Special',
    '連射不能': 'Single shot', 'ムズムズする?': 'Itchy?', '小': 'Low',
    '中': 'Medium', '大': 'High', 'ー': '-', '‐': '-', '〜': '~', '∼': '~',
}
# Follow the format used by the game's existing English mission text.
WIDTH_MAP = {i: chr(i + 0xFEE0) for i in range(0x21, 0x7F)}
WIDTH_MAP[ord(' ')] = '\u3000'
WIDTH_MAP[ord('~')] = '～'


def fullwidth(text):
    return text.translate(WIDTH_MAP)


def english_lines(text, width=34):
    return textwrap.wrap(text, width=width, break_long_words=False, break_on_hyphens=False)


def new_mission_lines(manifest):
    titles = {}
    for number, title in manifest['titles'].items():
        if not re.fullmatch(r'\d{3}', number) or not title.isascii() or len(title) > 22:
            raise ValueError(f'Unexpected mission title: {number}')
        titles[f'MISSION{number}/TITLE.TXT'] = fullwidth(title).encode('cp932')
    for number, prose in manifest['briefings'].items():
        if not re.fullmatch(r'\d{3}', number) or not prose.isascii():
            raise ValueError(f'Unexpected mission briefing: {number}')
        lines = english_lines(prose)
        if len(lines) > 12:
            raise ValueError(f'Mission briefing too long: {number}')
        titles[f'MISSION{number}/COMMENT.TXT'] = fullwidth('\n'.join(lines)).encode('cp932')
    return titles


def format_mission_text(path, payload, layout):
    number = path[7:10]
    if path.endswith('/TITLE.TXT'):
        title = layout['titles'].get(number)
        return fullwidth(title).encode('cp932') if title is not None else payload

    prose = layout['briefings'].get(number)
    if prose is None:
        prose = unicodedata.normalize('NFKC', payload.decode('cp932'))
    # Keep paragraph breaks when they fit the 12-line briefing panel.
    paragraphs = re.split(r'\n[ \t\r]*\n', prose.strip())
    formatted = '\n\n'.join('\n'.join(english_lines(' '.join(p.split()), 32)) for p in paragraphs)
    if len(formatted.splitlines()) > 12:
        formatted = '\n'.join(english_lines(' '.join(prose.split()), 32))
    if len(formatted.splitlines()) > 12:
        raise ValueError(f'Mission briefing exceeds the display panel: {path}')
    return fullwidth(formatted).encode('cp932')


def stat_line(line):
    key, sep, value = line[1:].strip().partition(':')
    if not sep or key.strip() not in STAT_LABELS:
        raise ValueError(f'Unexpected weapon stat: {line}')
    digits = re.findall(r'\d+(?:\.\d+)?', value)
    value = value.strip()
    for japanese, english in VALUE_TERMS.items():
        value = value.replace(japanese, english)
    if not value.isascii() or re.findall(r'\d+(?:\.\d+)?', value) != digits:
        raise ValueError(f'Weapon stat lost its original value: {line}')
    return '!' + fullwidth(f'{STAT_LABELS[key.strip()]}: {value}')


def donor_prose(donor):
    # The donor's descriptive paragraphs are useful. Its stat rows sometimes
    # describe a different weapon revision, so the Japanese file supplies all stats.
    labels = {
        'damage', 'damege', 'fire speed', 'range', 'accuracy', 'ammo', 'reload',
        'blast radius', 'homing', 'fuse', 'fuse length', 'spray focus', 'type',
        'energy consumption', 'charge time', 'no. of shots', 'recovery', 'zoom',
    }
    lines = []
    for raw in donor.splitlines():
        line = raw.strip()
        key, separator, _ = line.partition(':')
        if not line or (separator and key.strip().lower() in labels) or line.startswith(('$', '!', '★')):
            continue
        if re.search(r'[A-Za-z]{3}', line):
            lines.append(line)
    text = re.sub(r'\$c[0-9a-fA-F]{4}', '', ' '.join(lines))
    text = text.translate(str.maketrans({'“': '"', '”': '"', '‘': "'", '’': "'",
                                        'α': ' Alpha', 'β': ' Beta', 'γ': ' Gamma',
                                        '–': '-', '—': '-', '…': '...', '×': 'x',
                                        '°': ' degrees', '・': ' ', 'ー': '-'}))
    if any(ord(c) > 127 for c in text):
        raise ValueError('Donor weapon description contains an unsupported character')
    return text


def weapon_text(original, donor, authored, name, display_name=None):
    japanese = unicodedata.normalize('NFKC', original.decode('cp932')).splitlines()
    labels = []
    if display_name:
        if not display_name.isascii() or len(display_name) > 32:
            raise ValueError(f'Invalid English weapon name: {name}')
        labels.append(fullwidth(display_name))
    labels.extend(stat_line(line) for line in japanese if line.startswith('!'))
    for line in japanese:
        if line.startswith('$c'):
            if line.startswith('$c6228') and 'ズーム可能' in line:
                labels.append('$c6228' + fullwidth('Zoom available'))
            elif line.startswith('$c0008') and 'リロード' in line:
                labels.append('$c0008' + fullwidth('Cannot reload'))
            elif name not in authored:
                raise ValueError(f'Unrecognized weapon text markup: {line}')
    prose = authored.get(name)
    if prose is None:
        if donor is None:
            raise ValueError(f'No English description for {name}')
        prose = donor_prose(unicodedata.normalize('NFKC', donor.decode('cp932')))
    if not prose or not prose.isascii():
        raise ValueError(f'Missing or invalid English weapon description: {name}')
    return ('\r\n'.join(labels + ['', ''] + [fullwidth(x) for x in english_lines(prose, 34)])
            + '\r\n').encode('cp932')

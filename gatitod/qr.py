"""Minimal QR code (ISO/IEC 18004) to pair the phone, with no internet needed.

Only what is needed here: byte mode, M error correction, versions 1-10 (up to 213
bytes; a pairing URL takes ~70). Follows the design of Nayuki's reference
implementation (MIT) and is tested against the `qrcode` library in
tests/test_qr.py.

    qr.matrix('text')   -> list of bool rows (True = dark)
    qr.svg('text')      -> SVG
"""
from __future__ import annotations

import re

# per version 1..10, M correction: error-correction codewords per block and number of blocks
ECC_BLOCK = [10, 16, 26, 18, 24, 16, 18, 22, 22, 26]
BLOCKS = [1, 1, 1, 2, 2, 4, 4, 4, 5, 5]
FORMATO_M = 0   # format bits of level M (L=1, M=0, Q=3, H=2)


def _mul(x: int, y: int) -> int:
    """Product in GF(256) modulo x^8 + x^4 + x^3 + x^2 + 1."""
    z = 0
    for i in reversed(range(8)):
        z = (z << 1) ^ ((z >> 7) * 0x11D)
        z ^= ((y >> i) & 1) * x
    return z


def _divisor(degree: int) -> list[int]:
    r, root = [0] * (degree - 1) + [1], 1
    for _ in range(degree):
        for j in range(degree):
            r[j] = _mul(r[j], root) ^ (r[j + 1] if j + 1 < degree else 0)
        root = _mul(root, 2)
    return r


def _rest(data: list[int], div: list[int]) -> list[int]:
    r = [0] * len(div)
    for b in data:
        f = b ^ r.pop(0)
        r.append(0)
        r = [x ^ _mul(c, f) for x, c in zip(r, div)]
    return r


def _modules_data(v: int) -> int:
    n = (16 * v + 128) * v + 64
    if v >= 2:
        a = v // 7 + 2
        n -= (25 * a - 10) * a - 55
        if v >= 7:
            n -= 36
    return n


def _alignment(v: int, side: int) -> list[int]:
    if v == 1:
        return []
    a = v // 7 + 2
    step = (v * 8 + a * 3 + 5) // (a * 4 - 4) * 2
    return [6] + sorted(side - 7 - i * step for i in range(a - 1))


def _codewords(data: bytes, v: int) -> list[int]:
    ecc, nb = ECC_BLOCK[v - 1], BLOCKS[v - 1]
    total = _modules_data(v) // 8
    cap = total - ecc * nb
    bits = '0100' + format(len(data), '08b' if v < 10 else '016b') + ''.join(format(b, '08b') for b in data)
    bits += '0' * min(4, cap * 8 - len(bits))
    bits += '0' * (-len(bits) % 8)
    cw = [int(bits[i:i + 8], 2) for i in range(0, len(bits), 8)]
    cw += [(0xEC, 0x11)[i % 2] for i in range(cap - len(cw))]
    short, long_short = nb - total % nb, total // nb
    div, blocks, k = _divisor(ecc), [], 0
    for i in range(nb):
        dat = cw[k:k + long_short - ecc + (0 if i < short else 1)]
        k += len(dat)
        blocks.append(dat + ([0] if i < short else []) + _rest(dat, div))
    return [b[i] for i in range(len(blocks[0])) for j, b in enumerate(blocks)
            if i != long_short - ecc or j >= short]


MASKS = [lambda x, y: (x + y) % 2 == 0, lambda x, y: y % 2 == 0, lambda x, y: x % 3 == 0,
            lambda x, y: (x + y) % 3 == 0, lambda x, y: (x // 3 + y // 2) % 2 == 0,
            lambda x, y: x * y % 2 + x * y % 3 == 0, lambda x, y: (x * y % 2 + x * y % 3) % 2 == 0,
            lambda x, y: ((x + y) % 2 + x * y % 3) % 2 == 0]


def _draw(v: int, cw: list[int], mascara: int) -> list[list[bool]]:
    side = v * 4 + 17
    m = [[False] * side for _ in range(side)]
    fixed = [[False] * side for _ in range(side)]

    def pon(x, y, dark):
        m[y][x], fixed[y][x] = bool(dark), True

    for i in range(side):   # timing patterns
        pon(6, i, i % 2 == 0)
        pon(i, 6, i % 2 == 0)
    for cx, cy in ((3, 3), (side - 4, 3), (3, side - 4)):   # finder patterns with their separator
        for dy in range(-4, 5):
            for dx in range(-4, 5):
                if 0 <= cx + dx < side and 0 <= cy + dy < side:
                    pon(cx + dx, cy + dy, max(abs(dx), abs(dy)) not in (2, 4))
    al = _alignment(v, side)
    for i in al:
        for j in al:
            if (i, j) not in ((6, 6), (6, al[-1]), (al[-1], 6)):
                for dy in range(-2, 3):
                    for dx in range(-2, 3):
                        pon(i + dx, j + dy, max(abs(dx), abs(dy)) != 1)
    d = FORMATO_M << 3 | mascara
    r = d
    for _ in range(10):
        r = (r << 1) ^ ((r >> 9) * 0x537)
    f = (d << 10 | r) ^ 0x5412
    b = [(f >> i) & 1 for i in range(15)]
    for i in range(6):
        pon(8, i, b[i])
    pon(8, 7, b[6]), pon(8, 8, b[7]), pon(7, 8, b[8])
    for i in range(9, 15):
        pon(14 - i, 8, b[i])
    for i in range(8):
        pon(side - 1 - i, 8, b[i])
    for i in range(8, 15):
        pon(8, side - 15 + i, b[i])
    pon(8, side - 8, True)
    if v >= 7:
        r = v
        for _ in range(12):
            r = (r << 1) ^ ((r >> 11) * 0x1F25)
        vb = v << 12 | r
        for i in range(18):
            x, y = side - 11 + i % 3, i // 3
            pon(x, y, (vb >> i) & 1)
            pon(y, x, (vb >> i) & 1)
    i, der = 0, side - 1
    while der >= 1:   # data in zigzag, two columns at a time
        if der == 6:
            der = 5
        for vert in range(side):
            for j in range(2):
                x = der - j
                y = side - 1 - vert if ((der + 1) & 2) == 0 else vert
                if not fixed[y][x] and i < len(cw) * 8:
                    m[y][x] = bool((cw[i >> 3] >> (7 - (i & 7))) & 1)
                    i += 1
        der -= 2
    f = MASKS[mascara]
    return [[c ^ (not fixed[y][x] and f(x, y)) for x, c in enumerate(row)] for y, row in enumerate(m)]


def _penalizacion(m: list[list[bool]]) -> int:
    lines = [''.join('1' if c else '0' for c in f) for f in m]
    lines += [''.join(col) for col in zip(*lines)]
    p = sum(len(t) - 2 for s in lines for t in re.findall(r'0{5,}|1{5,}', s))
    p += 40 * sum(len(re.findall(r'(?=10111010000|00001011101)', s)) for s in lines)
    n = len(m)
    p += 3 * sum(m[y][x] == m[y][x + 1] == m[y + 1][x] == m[y + 1][x + 1]
                 for y in range(n - 1) for x in range(n - 1))
    darks = sum(map(sum, m))
    return p + 10 * ((abs(darks * 20 - n * n * 10) + n * n - 1) // (n * n) - 1)


def matrix(text: str, mascara: int | None = None) -> list[list[bool]]:
    data = text.encode('utf-8')
    for v in range(1, 11):
        if len(data) * 8 + 4 + (8 if v < 10 else 16) <= (_modules_data(v) // 8 - ECC_BLOCK[v - 1] * BLOCKS[v - 1]) * 8:
            cw = _codewords(data, v)
            if mascara is not None:
                return _draw(v, cw, mascara)
            return min((_draw(v, cw, k) for k in range(8)), key=_penalizacion)
    raise ValueError(f'too long for a version <= 10 QR ({len(data)} bytes)')


def svg(text: str, border: int = 4, px: int = 280) -> str:
    m = matrix(text)
    side = len(m) + 2 * border
    d = ''.join(f'M{x + border},{y + border}h1v1h-1z' for y, f in enumerate(m) for x, c in enumerate(f) if c)
    return (f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {side} {side}" width="{px}" height="{px}" '
            f'shape-rendering="crispEdges"><rect width="{side}" height="{side}" fill="#fff"/>'
            f'<path d="{d}" fill="#000"/></svg>')

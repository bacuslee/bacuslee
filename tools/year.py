"""A year in characters: ink/year.svg.

The contribution calendar, written the way the site's opening draws Latte
(moji-e): every day of the last year is one character from the same ramp,
ranked by how much ink it puts down, so a busier day is a heavier character.
The grid is a calligraphy practice sheet with faint vermilion rules, the rows
are the days of the week in kanji (日 sun, 月 moon, 火 fire, 水 water, 木 wood,
金 metal, 土 earth) and the months are written in numerals.

Each season writes in its own ink (紅梅 plum, 萌黄 new green, 藍 indigo, 鬱金
turmeric), and under each character the ink soaks into the paper as a nioi
gradient, the colour pooled in the middle and its lighter companion at the
edge. Lightness says how much: every ink shares the same five steps, so a busy
day is as heavy in summer as in winter, and the key in the corner runs from
less to more. Hue only says when, which the month names already say.

The busiest day is written in vermilion, and each month's best day, when it is
better than a usual day, gets the teacher's double circle in shuzumi, as on a
corrected practice sheet. Today's square waits, ringed, like the next key of
the evening's phrase. The year writes itself in, a week on every sixteenth
note at 90 BPM, holds, and writes itself again.

tools/bath.py calls this with the same calendar, so one request draws both.
Standard library only, so it runs in a GitHub Action.
"""
from __future__ import annotations

import bisect
import datetime as dt
import math
import statistics

PAPER = '#efe9dd'
SUMI = '#1b1a19'
SHU = '#b4321f'
MUTE = '#6d6c66'
BEAT = 60 / 90

# Shippori Mincho B1 ExtraBold glyphs ranked by ink, lightest first, as
# tools/build.py ranked_glyphs() measures them (the opening's moji-e ramp)
RAMP = '一二へ工大口水来林雨猫鬱'
WEEKDAYS = '日月火水木金土'
NUMERALS = ['一', '二', '三', '四', '五', '六', '七', '八', '九', '十', '十一', '十二']
# what the font subsets must hold for this drawing (tools/build.py writes them)
CHARS_800 = '一年' + RAMP
CHARS_500 = WEEKDAYS + '一二三四五六七八九十月'

W, H = 1600, 410

# ---- the inks ----
# One per season, from named traditional colours (NC: nipponcolors.com,
# WD: 和色大辞典 colordic.org), each with a lighter companion for the edge of
# the wash. Reds are avoided so the vermilion of the busiest day and the
# teacher's circles stays unmistakable. Chosen and checked in the research for
# this graph: neighbouring seasons stay apart for full colour vision, and are
# also told apart by the month names for readers who see colour differently.
SEASONS = {           # deep, light, chroma
    'winter': ('#E16B8C', '#FEDFE1', 0.12),   # 紅梅 kōbai NC, edged 桜 sakura NC: plum in the snow
    'spring': ('#7BA23F', '#aacf53', 0.12),   # 萌黄 moegi NC, edged 萌黄 WD: new leaves
    'summer': ('#165e83', '#4c6cb3', 0.12),   # 藍 ai WD, edged 群青 gunjō WD: the indigo of suminagashi
    'autumn': ('#EFBB24', '#FFB11B', 0.15),   # 鬱金 ukon NC, edged 山吹 yamabuki NC: the kin of the kasumi
}
SEASON_OF = {12: 'winter', 1: 'winter', 2: 'winter', 3: 'spring', 4: 'spring', 5: 'spring',
             6: 'summer', 7: 'summer', 8: 'summer', 9: 'autumn', 10: 'autumn', 11: 'autumn'}
# five lightness steps (GitHub's graph has four), the same for every ink; the
# characters keep all twelve levels, and a black-ish character reads on each
WASH = [0.90, 0.835, 0.77, 0.705, 0.64]
MUTED = 0.72   # watercolour strength rather than poster paint


def oklch(hexv: str) -> tuple[float, float, float]:
    def lin(c):
        return c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4
    r, g, b = (lin(int(hexv[i:i + 2], 16) / 255) for i in (1, 3, 5))
    l, m, s = ((0.4122214708 * r + 0.5363325363 * g + 0.0514459929 * b) ** (1 / 3),
               (0.2119034982 * r + 0.6806995451 * g + 0.1073969566 * b) ** (1 / 3),
               (0.0883024619 * r + 0.2817188376 * g + 0.6299787005 * b) ** (1 / 3))
    L = 0.2104542553 * l + 0.7936177850 * m - 0.0040720468 * s
    a = 1.9779984951 * l - 2.4285922050 * m + 0.4505937099 * s
    bb = 0.0259040371 * l + 0.7827717662 * m - 0.8086757660 * s
    return L, math.hypot(a, bb), math.degrees(math.atan2(bb, a)) % 360


def _rgb(L: float, C: float, H: float) -> tuple[float, float, float]:
    a, b = C * math.cos(math.radians(H)), C * math.sin(math.radians(H))
    l = (L + 0.3963377774 * a + 0.2158037573 * b) ** 3
    m = (L - 0.1055613458 * a - 0.0638541728 * b) ** 3
    s = (L - 0.0894841775 * a - 1.2914855480 * b) ** 3
    return (4.0767416621 * l - 3.3077115913 * m + 0.2309699292 * s,
            -1.2684380046 * l + 2.6097574011 * m - 0.3413193965 * s,
            -0.0041960863 * l - 0.7034186147 * m + 1.7076147010 * s)


def to_hex(L: float, C: float, H: float) -> str:
    """OKLCH to sRGB hex, giving up chroma (never lightness or hue) to stay in gamut."""
    def inside(c):
        return all(-1e-4 <= v <= 1 + 1e-4 for v in _rgb(L, c, H))
    if not inside(C):
        lo, hi = 0.0, C
        for _ in range(24):
            mid = (lo + hi) / 2
            lo, hi = (mid, hi) if inside(mid) else (lo, mid)
        C = lo

    def enc(v):
        v = max(0.0, min(1.0, v))
        return 12.92 * v if v <= 0.0031308 else 1.055 * v ** (1 / 2.4) - 0.055
    return '#' + ''.join(f'{round(enc(v) * 255):02x}' for v in _rgb(L, C, H))


def ink(d: dt.date, lv: int) -> tuple[str, str, str]:
    """The wash's pooled colour, its edge colour and the character's colour for
    a day at level 1 to 12. Watered-down ink is nearly grey; colour comes where it pools."""
    deep, light, cmax = SEASONS[SEASON_OF[d.month]]
    step = math.ceil(lv * len(WASH) / len(RAMP))
    L = WASH[step - 1]
    c = cmax * MUTED * (0.2 + 0.8 * (step / len(WASH)) ** 1.4)
    return (to_hex(L, c, oklch(deep)[2]), to_hex(min(0.95, L + 0.045), c * 0.7, oklch(light)[2]),
            to_hex(0.27, cmax * 0.5, oklch(deep)[2]))


# ---- the calendar ----

def esc(s: str) -> str:
    return s.replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;')


def level(n: int, active: list[int]) -> int:
    """0 for a day off, else 1 to 12 by rank among the days with work (GitHub
    uses quartiles; this uses the whole ramp), so the year shows its texture."""
    if n <= 0 or not active:
        return 0
    return max(1, math.ceil(len(RAMP) * bisect.bisect_right(active, n) / len(active)))


def runs(days: list[tuple[str, int]]) -> tuple[int, int]:
    """Longest run of days with contributions, and the run ending today
    (or yesterday, while today is still empty)."""
    longest = cur = 0
    for _, n in days:
        cur = cur + 1 if n else 0
        longest = max(longest, cur)
    tail = days[:-1] if days and not days[-1][1] else days
    current = 0
    for _, n in reversed(tail):
        if not n:
            break
        current += 1
    return longest, current


def doc_width(label: str) -> float:
    """Rough width of a 13px tracked Inter Tight label, for placing things beside it."""
    return len(label) * 10.6


def pct(t: float, cycle: float) -> str:
    return f'{max(0.0, min(100.0, 100 * t / cycle)):.3f}%'


def maru(cx: float, cy: float, rad: float, seed: int) -> str:
    """The teacher's double circle, drawn in one loose stroke."""
    pts = []
    wob = (seed * 7919) % 97 / 97
    for j in range(90):
        u = j / 89
        a = -math.pi * 0.6 + u * 2 * math.pi * 1.85
        rr = rad * (0.9 + 0.16 * u) * (1 + 0.03 * math.sin(7 * u + wob * 6))
        pts.append(f'{cx + rr * math.cos(a) * 1.06:.1f} {cy + rr * math.sin(a) * 0.98:.1f}')
    return 'M' + ' L'.join(pts)


def render(days: list[tuple[str, int]], css_fonts: str, waiting: bool = False) -> str:
    """`days` is the calendar, oldest first. With `waiting`, the counts are not
    known yet: the sheet is drawn, ruled and labelled, with nothing written."""
    first = dt.date.fromisoformat(days[0][0])
    start = first - dt.timedelta(days=(first.weekday() + 1) % 7)   # the Sunday on or before
    cols = (dt.date.fromisoformat(days[-1][0]) - start).days // 7 + 1
    x0, y0, right = 112, 150, 64
    cell = (W - x0 - right) / cols
    active = sorted(n for _, n in days if n > 0)
    busiest = max(range(len(days)), key=lambda i: days[i][1])

    # one group per week, so the year can write itself in a week at a time
    weeks: dict[int, list[tuple[float, float, int, dt.date]]] = {}
    shu = None
    for i, (date, n) in enumerate(days):
        d = dt.date.fromisoformat(date)
        c, r = (d - start).days // 7, (d.weekday() + 1) % 7
        lv = 0 if waiting else level(n, active)
        if not lv:
            continue
        mark = (x0 + c * cell, y0 + r * cell, lv, d)
        if i == busiest:
            shu = (mark, c)
        else:
            weeks.setdefault(c, []).append(mark)

    step = BEAT / 4
    cycle = BEAT * 36
    fade = cycle - BEAT
    css, body, grads = [], [], {}

    def write_in(cls: str, t: float):
        css.append(f'@keyframes {cls}{{0%,{pct(t, cycle)}{{opacity:0}}{pct(t + 0.001, cycle)}{{opacity:.4}}'
                   f'{pct(t + 1 / 12, cycle)},{pct(fade, cycle)}{{opacity:1}}{pct(fade + BEAT * 0.75, cycle)},100%{{opacity:0}}}}'
                   f'.{cls}{{animation:{cls} {cycle:.3f}s step-end infinite}}')

    def wash(x, y, lv, d, vermilion=False, size=None):
        size = size or cell
        box = f'x="{x + 1.5:.1f}" y="{y + 1.5:.1f}" width="{size - 3:.1f}" height="{size - 3:.1f}" rx="{size * 0.22:.1f}"'
        if vermilion:
            return f'<rect {box} fill="url(#washshu)" fill-opacity="{0.05 + 0.3 * (lv / len(RAMP)) ** 1.3:.3f}"/>'
        core, edge, _ = ink(d, lv)
        gid = grads.setdefault((core, edge), f'n{len(grads)}')
        return f'<rect {box} fill="url(#{gid})"/>'

    def glyphs(marks, fill, size=None):
        size = size or cell
        f = size * 0.84
        s = ''.join(RAMP[m[2] - 1] for m in marks)
        xs = ' '.join(f'{m[0] + (size - f) / 2:.1f}' for m in marks)
        ys = ' '.join(f'{m[1] + size / 2 + f * 0.36:.1f}' for m in marks)
        return (f'<text x="{xs}" y="{ys}" font-family="Shippori,serif" font-weight="800" '
                f'font-size="{f:.2f}" fill="{fill}">{s}</text>')

    def written(marks, size=None):
        """Washes, then the characters grouped by their ink."""
        by_ink: dict[str, list] = {}
        for m in marks:
            by_ink.setdefault(ink(m[3], m[2])[2], []).append(m)
        return ''.join(wash(*m, size=size) for m in marks) + ''.join(glyphs(ms, g, size) for g, ms in by_ink.items())

    for c in sorted(weeks):
        write_in(f'w{c}', BEAT + c * step)
        body.append(f'<g class="w{c}">{written(weeks[c])}</g>')
    if shu:
        write_in('ws', BEAT + shu[1] * step)
        body.append(f'<g class="ws">{wash(*shu[0], vermilion=True)}{glyphs([shu[0]], SHU)}</g>')

    # the teacher's circles: each month's best day, when it beats a usual day
    if not waiting and active:
        usual = statistics.median(active)
        best: dict[str, int] = {}
        for i, (date, n) in enumerate(days):
            if n > usual and i != busiest and (date[:7] not in best or n > days[best[date[:7]]][1]):
                best[date[:7]] = i
        for i in best.values():
            d = dt.date.fromisoformat(days[i][0])
            c, r = (d - start).days // 7, (d.weekday() + 1) % 7
            t = BEAT * 2 + c * step
            cls = f'm{c}{r}'
            css.append(f'@keyframes {cls}{{0%,{pct(t, cycle)}{{stroke-dashoffset:1;opacity:0}}'
                       f'{pct(t + 0.001, cycle)}{{stroke-dashoffset:1;opacity:.88}}'
                       f'{pct(t + BEAT * 0.75, cycle)},{pct(fade, cycle)}{{stroke-dashoffset:0;opacity:.88}}'
                       f'{pct(fade + BEAT * 0.75, cycle)},100%{{stroke-dashoffset:0;opacity:0}}}}'
                       f'.{cls}{{animation:{cls} {cycle:.3f}s linear infinite}}')
            body.append(f'<path class="{cls}" d="{maru(x0 + c * cell + cell / 2, y0 + r * cell + cell / 2, cell * 0.56, c * 7 + r)}" '
                        f'pathLength="1" stroke-dasharray="1 1" fill="none" stroke="{SHU}" stroke-width="1.5" '
                        f'stroke-linecap="round" opacity="0.88"/>')

    # the key: less to more, as on GitHub's graph, in the season's own ink
    k = cell * 0.92
    key_lv = [1, 3, 5, 7, 9, 11, 12]
    kx = W - right - doc_width('MORE') - 10 - len(key_lv) * (k + 3)
    ky = H - 34 - k * 0.72
    today = dt.date.fromisoformat(days[-1][0])
    key = [f'<text x="{kx - 10:.1f}" y="{H - 34}" text-anchor="end" font-family="InterTight,sans-serif" font-weight="600" '
           f'font-size="13" letter-spacing="1.8" fill="{SUMI}" opacity="0.66">LESS</text>',
           written([(kx + j * (k + 3), ky, lv, today) for j, lv in enumerate(key_lv)], size=k),
           f'<text x="{W - right}" y="{H - 34}" text-anchor="end" font-family="InterTight,sans-serif" font-weight="600" '
           f'font-size="13" letter-spacing="1.8" fill="{SUMI}" opacity="0.66">MORE</text>']
    note = "EACH MONTH'S BEST DAY"
    nx = W - right - len(note) * 9.4          # this label is mostly narrow capitals
    key.append(f'<path d="{maru(nx - 14, 92, 8, 3)}" fill="none" stroke="{SHU}" stroke-width="1.3" opacity="0.88"/>'
               f'<text x="{W - right}" y="97" text-anchor="end" font-family="InterTight,sans-serif" font-weight="600" '
               f'font-size="13" letter-spacing="1.8" fill="{SUMI}" opacity="0.66">{esc(note)}</text>')

    # the practice sheet's rules
    rules = [f'M{x0:.1f} {y0 + r * cell:.1f}H{x0 + cols * cell:.1f}' for r in range(8)]
    rules += [f'M{x0 + c * cell:.1f} {y0:.1f}V{y0 + 7 * cell:.1f}' for c in range(cols + 1)]
    sheet = f'<path d="{"".join(rules)}" stroke="{SHU}" stroke-opacity="0.16" stroke-width="1" fill="none"/>'

    # today waits, ringed in vermilion
    tc, tr = (today - start).days // 7, (today.weekday() + 1) % 7
    css.append(f'@keyframes today{{0%,100%{{opacity:.25}}50%{{opacity:1}}}}'
               f'.today{{animation:today {BEAT * 2:.3f}s ease-in-out infinite}}')
    ring = (f'<rect class="today" x="{x0 + tc * cell + 1.5:.1f}" y="{y0 + tr * cell + 1.5:.1f}" width="{cell - 3:.1f}" '
            f'height="{cell - 3:.1f}" fill="none" stroke="{SHU}" stroke-width="2"/>')

    labels = []
    for r, ch in enumerate(WEEKDAYS):
        labels.append(f'<text x="{x0 - 16}" y="{y0 + r * cell + cell / 2 + 6:.1f}" text-anchor="end" font-family="Shippori,serif" '
                      f'font-weight="500" font-size="17" fill="{MUTE}">{ch}</text>')
    # a month is named over the first week it starts in, unless the next name is too close
    starts, prev = [], None
    for c in range(cols):
        m = max(first, start + dt.timedelta(days=7 * c)).month
        if m != prev:
            starts.append((c, m))
            prev = m
    for j, (c, m) in enumerate(starts):
        nxt = starts[j + 1][0] if j + 1 < len(starts) else cols
        if nxt - c >= 3:
            labels.append(f'<text x="{x0 + c * cell + 2:.1f}" y="{y0 - 14}" font-family="Shippori,serif" font-weight="500" '
                          f'font-size="17" fill="{MUTE}">{NUMERALS[m - 1]}月</text>')

    total = sum(n for _, n in days)
    longest, current = runs(days)
    if waiting:
        stats = 'STILL PAPER UNTIL THE FIRST MORNING RUN'
    else:
        stats = (f'{total:,} contributions in the last year · longest run {longest} days · '
                 f'current run {current} days · busiest {dt.date.fromisoformat(days[busiest][0]):%b %d} '
                 f'({days[busiest][1]}), in vermilion').upper()
    css.append('@media (prefers-reduced-motion:reduce){g,path,.today{animation:none!important;opacity:1!important;'
               'stroke-dashoffset:0!important}}')
    title = 'A year in characters'
    desc = ('Every day of the last year written as one character on a practice sheet, each season in its own ink; '
            'the more I committed, the more ink the character takes, and the best day of each month is circled. '
            f'{stats.capitalize()}.')
    gradients = ''.join(f'<radialGradient id="{gid}" r="0.72"><stop offset="0" stop-color="{a}"/><stop offset="0.55" '
                        f'stop-color="{a}"/><stop offset="1" stop-color="{b}" stop-opacity="0.55"/></radialGradient>'
                        for (a, b), gid in grads.items())
    return (
        f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {W} {H}" width="{W}" height="{H}" role="img" aria-labelledby="t d">'
        f'<title id="t">{title}</title><desc id="d">{esc(desc)}</desc><style>{css_fonts}{"".join(css)}</style>'
        f'<rect width="{W}" height="{H}" fill="{PAPER}"/>'
        f'<text x="64" y="64" font-family="Shippori,serif" font-weight="800" font-size="36" fill="{SUMI}">一年 · A year in characters</text>'
        f'<text x="64" y="98" font-family="Shippori,serif" font-weight="500" font-size="20" fill="{SUMI}" opacity="0.8">'
        f'Every day is one character; the more I committed, the more ink it takes.</text>'
        f'<defs><radialGradient id="washshu" r="0.7"><stop offset="0" stop-color="{SHU}"/><stop offset="0.6" stop-color="{SHU}" '
        f'stop-opacity="0.85"/><stop offset="1" stop-color="{SHU}" stop-opacity="0.35"/></radialGradient>{gradients}</defs>'
        f'{sheet}{"".join(labels)}{"".join(body)}{ring}{"".join(key)}'
        f'<text x="64" y="{H - 34}" font-family="InterTight,sans-serif" font-weight="600" font-size="13" letter-spacing="1.8" '
        f'fill="{SUMI}" opacity="0.66">{esc(stats)}</text>'
        f'<text x="{W - 64}" y="64" text-anchor="end" font-family="InterTight,sans-serif" font-weight="600" '
        f'font-size="13" letter-spacing="1.8" fill="{SUMI}" opacity="0.66">REDRAWN EACH MORNING</text></svg>')

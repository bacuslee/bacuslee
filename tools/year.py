"""A year in characters: ink/year.svg.

The contribution calendar, written the way the site's opening draws Latte
(moji-e): every day of the last year is one character from the same ramp,
ranked by how much ink it puts down, so a busier day is a heavier character.
The grid is a calligraphy practice sheet with faint vermilion rules, the rows
are the days of the week in kanji (日 sun, 月 moon, 火 fire, 水 water, 木 wood,
金 metal, 土 earth) and the months are written in numerals. The busiest day is
the one character in vermilion; today's square waits, ringed, like the next
key of the evening's phrase. The year writes itself in, a week on every
sixteenth note at 90 BPM, holds, and writes itself again.

tools/bath.py calls this with the same calendar, so one request draws both.
"""
from __future__ import annotations

import bisect
import datetime as dt
import math

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


def pct(t: float, cycle: float) -> str:
    return f'{max(0.0, min(100.0, 100 * t / cycle)):.3f}%'


def render(days: list[tuple[str, int]], css_fonts: str, waiting: bool = False) -> str:
    """`days` is the calendar, oldest first. With `waiting`, the counts are not
    known yet: the sheet is drawn, ruled and labelled, with nothing written."""
    first = dt.date.fromisoformat(days[0][0])
    start = first - dt.timedelta(days=(first.weekday() + 1) % 7)   # the Sunday on or before
    cols = (dt.date.fromisoformat(days[-1][0]) - start).days // 7 + 1
    x0, y0, right = 112, 150, 64
    cell = (W - x0 - right) / cols
    fs = cell * 0.84
    active = sorted(n for _, n in days if n > 0)
    busiest = max(range(len(days)), key=lambda i: days[i][1])

    # one <text> per week, so the year can write itself in a week at a time
    weeks: dict[int, list[tuple[float, float, str]]] = {}
    shu = None
    for i, (date, n) in enumerate(days):
        d = dt.date.fromisoformat(date)
        c, r = (d - start).days // 7, (d.weekday() + 1) % 7
        lv = 0 if waiting else level(n, active)
        if not lv:
            continue
        gx = x0 + c * cell + (cell - fs) / 2
        gy = y0 + r * cell + cell / 2 + fs * 0.36
        if i == busiest:
            shu = (gx, gy, RAMP[lv - 1], c)
        else:
            weeks.setdefault(c, []).append((gx, gy, RAMP[lv - 1]))

    step = BEAT / 4
    cycle = BEAT * 36
    fade = cycle - BEAT
    css, body = [], []

    def column(cells, c, fill):
        cls = f'w{c}' if fill == SUMI else 'ws'
        t = BEAT + c * step
        css.append(f'@keyframes {cls}{{0%,{pct(t, cycle)}{{opacity:0}}{pct(t + 0.001, cycle)}{{opacity:.4}}'
                   f'{pct(t + 1 / 12, cycle)},{pct(fade, cycle)}{{opacity:1}}{pct(fade + BEAT * 0.75, cycle)},100%{{opacity:0}}}}'
                   f'.{cls}{{animation:{cls} {cycle:.3f}s step-end infinite}}')
        s = ''.join(ch for _, _, ch in cells)
        xs = ' '.join(f'{x:.1f}' for x, _, _ in cells)
        ys = ' '.join(f'{y:.1f}' for _, y, _ in cells)
        return (f'<text class="{cls}" x="{xs}" y="{ys}" font-family="Shippori,serif" font-weight="800" '
                f'font-size="{fs:.2f}" fill="{fill}">{s}</text>')

    for c in sorted(weeks):
        body.append(column(weeks[c], c, SUMI))
    if shu:
        body.append(column([shu[:3]], shu[3], SHU))

    # the practice sheet's rules
    rules = [f'M{x0:.1f} {y0 + r * cell:.1f}H{x0 + cols * cell:.1f}' for r in range(8)]
    rules += [f'M{x0 + c * cell:.1f} {y0:.1f}V{y0 + 7 * cell:.1f}' for c in range(cols + 1)]
    sheet = f'<path d="{"".join(rules)}" stroke="{SHU}" stroke-opacity="0.16" stroke-width="1" fill="none"/>'

    # today waits, ringed in vermilion
    last = dt.date.fromisoformat(days[-1][0])
    tc, tr = (last - start).days // 7, (last.weekday() + 1) % 7
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
    for k, (c, m) in enumerate(starts):
        nxt = starts[k + 1][0] if k + 1 < len(starts) else cols
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
    css.append('@media (prefers-reduced-motion:reduce){text,.today{animation:none!important;opacity:1!important}}')
    title = 'A year in characters'
    desc = ('Every day of the last year written as one character on a practice sheet; the more I committed, '
            f'the more ink the character takes. {stats.capitalize()}.')
    return (
        f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {W} {H}" width="{W}" height="{H}" role="img" aria-labelledby="t d">'
        f'<title id="t">{title}</title><desc id="d">{esc(desc)}</desc><style>{css_fonts}{"".join(css)}</style>'
        f'<rect width="{W}" height="{H}" fill="{PAPER}"/>'
        f'<text x="64" y="64" font-family="Shippori,serif" font-weight="800" font-size="36" fill="{SUMI}">一年 · A year in characters</text>'
        f'<text x="64" y="98" font-family="Shippori,serif" font-weight="500" font-size="20" fill="{SUMI}" opacity="0.8">'
        f'Every day is one character; the more I committed, the more ink it takes.</text>'
        f'{sheet}{"".join(labels)}{"".join(body)}{ring}'
        f'<text x="64" y="{H - 34}" font-family="InterTight,sans-serif" font-weight="600" font-size="13" letter-spacing="1.8" '
        f'fill="{SUMI}" opacity="0.66">{esc(stats)}</text>'
        f'<text x="{W - 64}" y="{H - 34}" text-anchor="end" font-family="InterTight,sans-serif" font-weight="600" '
        f'font-size="13" letter-spacing="1.8" fill="{SUMI}" opacity="0.66">REDRAWN EACH MORNING</text></svg>')

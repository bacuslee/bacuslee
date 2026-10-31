#!/usr/bin/env python3
"""Suminagashi from a contribution calendar: ink/bath.svg.

  GITHUB_TOKEN=... python3 tools/bath.py --login bacuslee
  python3 tools/bath.py --sample            # made-up month, no network

The last four weeks fall into a bath of still water, one day on every beat at
90 BPM. A day with commits is a drop of ink, wider for a busier day, and a drop
of clear water after it, which is what makes the rings; a day off is only
water. Each week pools around its own centre and pushes the weeks before it
aside. The busiest day is the one drop of vermilion. Two tines are drawn
through the bath, then a sheet of washi is laid on to take the print, and the
bath starts again.

The rings are exact, not simulated: every point is moved by the closed-form
drop and tine transforms from Lu, Jaffer, Jin, Zhao and Mao, "Mathematical
Marbling" (IEEE CG&A, 2012), as in the site's components/day/marbling.ts.
The same calendar, a whole year of it, is also written out as characters in
ink/year.svg (tools/year.py). Needs only the standard library and numpy, so
it runs in a GitHub Action.
"""
from __future__ import annotations

import argparse
import base64
import datetime as dt
import hashlib
import json
import math
import os
import pathlib
import urllib.request

import numpy as np

import year

HERE = pathlib.Path(__file__).resolve().parent
OUT = HERE.parent / 'ink' / 'bath.svg'
YEAR = HERE.parent / 'ink' / 'year.svg'
FONTS = HERE / 'fonts'

W, H = 1200, 580
BEAT = 60 / 90
PAPER = '#efe9dd'
SUMI = '#1b1a19'
SHU = '#b4321f'
DAYS = 28
TINES = [((0, H * 0.5), (1.0, 0.1)), ((W, H * 0.66), (-1.0, 0.06))]  # two strokes: there, and back


# ---- the calendar ----

QUERY = '''query($login: String!) { user(login: $login) { contributionsCollection {
  contributionCalendar { weeks { contributionDays { date contributionCount } } } } } }'''


def fetch(login: str, token: str) -> list[tuple[str, int]]:
    req = urllib.request.Request(
        'https://api.github.com/graphql',
        data=json.dumps({'query': QUERY, 'variables': {'login': login}}).encode(),
        headers={'Authorization': f'bearer {token}', 'Content-Type': 'application/json', 'User-Agent': 'ink-bath'})
    with urllib.request.urlopen(req, timeout=30) as r:
        data = json.load(r)
    if 'errors' in data:
        raise SystemExit(f'GitHub said: {data["errors"]}')
    weeks = data['data']['user']['contributionsCollection']['contributionCalendar']['weeks']
    return [(d['date'], d['contributionCount']) for w in weeks for d in w['contributionDays']]


def sample(length: int = 366) -> list[tuple[str, int]]:
    """A plausible year for trying the drawings without a token."""
    end = dt.date(2026, 10, 30)
    out = []
    for k in range(length):
        day = end - dt.timedelta(days=length - 1 - k)
        h = int(hashlib.sha1(day.isoformat().encode()).hexdigest(), 16)
        n = 0 if h % 9 == 0 else (h >> 8) % 24 + (8 if day.weekday() < 5 else 0)
        out.append((day.isoformat(), n))
    return out


# ---- the marbling ----

def h01(*xs) -> float:
    b = hashlib.blake2b(repr(xs).encode(), digest_size=8).digest()
    return int.from_bytes(b, 'big') / 2 ** 64


def drop(rings: list[np.ndarray], c: np.ndarray, r: float):
    """Ink of radius r at c: every earlier point moves out along its ray from c,
    so the area it encloses grows by exactly the drop's area."""
    for p in rings:
        d = p - c
        d2 = (d * d).sum(1, keepdims=True)
        p[:] = c + d * np.sqrt(1 + r * r / np.maximum(d2, 1e-9))


def tine(rings: list[np.ndarray], b: np.ndarray, m: np.ndarray, z: float, c: float):
    """A tine drawn through b along m: points near the line slide along it,
    less the further they are (u ** distance, u = 2 ** (-1 / c))."""
    m = m / np.linalg.norm(m)
    n = np.array([-m[1], m[0]])
    u = 2 ** (-1 / c)
    for p in rings:
        dist = np.abs((p - b) @ n)
        p += (z * u ** dist)[:, None] * m


def circle(c, r, n):
    a = np.linspace(0, 2 * np.pi, n, endpoint=False)
    return np.stack([c[0] + r * np.cos(a), c[1] + r * np.sin(a)], 1)


def plan(days: list[tuple[str, int]]):
    """Where and how big each day falls, and in what ink."""
    weeks = {}
    for i, (date, _) in enumerate(days):
        weeks.setdefault(i // 7, []).append(i)
    centres = {}
    # four pools across the bath, close enough to press on each other, nudged
    # by the dates so the print changes week to week
    slots = [(0.25, 0.55), (0.43, 0.63), (0.6, 0.5), (0.78, 0.6)]
    for w, idx in weeks.items():
        sx, sy = slots[w % 4]
        key = days[idx[0]][0]
        centres[w] = np.array([(sx + (h01('x', key) - 0.5) * 0.06) * W, (sy + (h01('y', key) - 0.5) * 0.08) * H])
    busiest = max(range(len(days)), key=lambda i: days[i][1])
    out = []
    for i, (date, n) in enumerate(days):
        c = centres[i // 7] + np.array([(h01('jx', date) - 0.5) * 12, (h01('jy', date) - 0.5) * 12])
        # one day = one beat: its ink (if any) and the clear water that rings it
        if n:
            color = SHU if i == busiest else (SUMI if h01('ink', date) > 0.12 else '#2b3a55')
            out.append(dict(date=date, n=n, c=c, r=min(44.0, 9 + 4.6 * math.sqrt(n)), color=color, beat=i))
        out.append(dict(date=date, n=n, c=c, r=27.0, color=PAPER, beat=i))
    return out


def simulate(drops):
    """Run the month twice: densely, to see where every ring ends up, then with
    each ring's points spaced evenly along its final shape. Returns, per ring,
    its points after each event (its own drop, every later drop, the tine)."""
    def run(counts):
        rings, states = [], []
        for k, d in enumerate(drops):
            drop(rings, d['c'], d['r'])
            rings.append(circle(d['c'], d['r'], counts[k]))
            states.append([p.copy() for p in rings])
        for b, m in TINES:
            tine(rings, np.array(b), np.array(m), 44, 30)
            states.append([p.copy() for p in rings])
        return states

    dense = run([1600] * len(drops))
    final = dense[-1]
    keep = []
    for p in final:
        seg = np.linalg.norm(np.diff(np.vstack([p, p[:1]]), axis=0), axis=1)
        length = seg.sum()
        n = int(np.clip(length / 18, 26, 160))
        at = np.concatenate([[0], np.cumsum(seg)[:-1]])
        idx = np.searchsorted(at, np.linspace(0, length, n, endpoint=False))
        keep.append(np.clip(idx, 0, len(p) - 1))
    # per ring: list of states from its birth on, sampled at the kept points
    out = []
    for k in range(len(drops)):
        out.append([s[k][keep[k]] for s in dense[k:]])
    return out


def path(p: np.ndarray) -> str:
    """Integer points as one move and relative lines, rounded from absolutes so nothing drifts."""
    q = np.rint(p).astype(int)
    d = np.diff(q, axis=0)
    body = ' '.join(f'{x} {y}' for x, y in d)
    return f'M{q[0, 0]} {q[0, 1]}l{body}z'


# ---- the drawing ----

def font_face(family: str, weight: int, file: str) -> str:
    b = base64.b64encode((FONTS / file).read_bytes()).decode()
    return f'@font-face{{font-family:{family};font-weight:{weight};src:url(data:font/woff2;base64,{b}) format("woff2")}}'


def fonts() -> str:
    """The subsets tools/build.py writes for the daily drawings."""
    return (font_face('Shippori', 800, 'mincho-800.woff2') + font_face('Shippori', 500, 'mincho-500.woff2')
            + font_face('InterTight', 600, 'sans-600.woff2'))


def esc(s: str) -> str:
    return s.replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;')


def render(days: list[tuple[str, int]]) -> str:
    if not days:
        return still_water()
    drops = plan(days)
    states = simulate(drops)
    start = 2 * BEAT
    # an ink drop lands on its day's beat, the water just after it
    t_ev = []
    for d in drops:
        t = start + d['beat'] * BEAT
        t_ev.append(t + (BEAT * 0.34 if d['color'] == PAPER and d['n'] else 0))
    t_tines = [start + (DAYS + 1 + 2 * j) * BEAT for j in range(len(TINES))]
    events = t_ev + t_tines
    t_lay = t_tines[-1] + 9 * BEAT       # a hold, then the sheet goes down
    cycle = t_lay + 4 * BEAT
    # Every event starts on its beat. A state is keyed at the next event, and
    # the spline starts fast and settles, so each change lands at once and the
    # water is still until the next.
    spline = '0 .8 .2 1'
    rings = []
    for k, d in enumerate(drops):
        seq = states[k]            # after its own drop, each later drop, each tine
        collapsed = np.repeat(d['c'][None, :], len(seq[0]), 0)
        keys = [(0.0, collapsed), (events[k], collapsed)]
        for j in range(k, len(events)):
            nxt = events[j + 1] if j + 1 < len(events) else events[j] + BEAT
            keys.append((nxt, seq[j - k]))
        keys.append((t_lay + BEAT * 1.5, seq[-1]))     # under the sheet now
        keys.append((t_lay + BEAT * 1.5 + 0.002, collapsed))
        keys.append((cycle, collapsed))
        kt = ';'.join(f'{t / cycle:.5f}' for t, _ in keys)
        vals = ';'.join(path(v) for _, v in keys)
        splines = ';'.join(spline for _ in range(len(keys) - 1))
        rings.append(
            f'<path fill="{d["color"]}" d="{path(collapsed)}"><animate attributeName="d" dur="{cycle:.3f}s" '
            f'repeatCount="indefinite" calcMode="spline" keySplines="{splines}" keyTimes="{kt}" values="{vals}"/></path>')
    final = ''.join(f'<path fill="{d["color"]}" d="{path(states[k][-1])}"/>' for k, d in enumerate(drops))

    first = dt.date.fromisoformat(days[0][0])
    last = dt.date.fromisoformat(days[-1][0])
    total = sum(c for _, c in days)
    active = sum(1 for _, c in days if c)
    bi = max(range(len(days)), key=lambda i: days[i][1])
    bday = dt.date.fromisoformat(days[bi][0])
    fmt = lambda d: d.strftime('%b %d').upper()
    stats = (f'{fmt(first)} – {fmt(last)} · {total} contributions on {active} of {len(days)} days · '
             f'busiest {fmt(bday)} ({days[bi][1]}), in vermilion').upper()

    # the sheet: laid down over two beats, then lifted with the print
    lay = (f'<rect width="{W}" height="{H}" fill="#f4efe4"><animate attributeName="opacity" dur="{cycle:.3f}s" '
           f'repeatCount="indefinite" keyTimes="0;{t_lay / cycle:.5f};{(t_lay + BEAT * 1.5) / cycle:.5f};'
           f'{(t_lay + BEAT * 2.5) / cycle:.5f};1" values="0;0;1;0;0"/></rect>')
    grain = ('<filter id="grain" x="0" y="0" width="100%" height="100%"><feTurbulence type="fractalNoise" '
             'baseFrequency="0.85 0.3" numOctaves="3" seed="5"/><feColorMatrix values="0 0 0 0 1  0 0 0 0 1  '
             '0 0 0 0 1  0 0 0 0.9 -0.42"/></filter>')
    css = (fonts()
           + '.still{display:none}@media (prefers-reduced-motion:reduce){.live{display:none}.still{display:inline}}')
    title = 'Suminagashi: four weeks of contributions as floating ink'
    desc = (f'Each day from {first:%d %B} to {last:%d %B %Y} falls into a bath of water as a drop of ink, '
            f'wider for a busier day: {total} contributions on {active} days.')
    return (
        f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {W} {H}" width="{W}" height="{H}" role="img" aria-labelledby="t d">'
        f'<title id="t">{esc(title)}</title><desc id="d">{esc(desc)}</desc><style>{css}</style>'
        f'<defs>{grain}</defs><rect width="{W}" height="{H}" fill="{PAPER}"/>'
        f'<g class="live">{"".join(rings)}{lay}</g><g class="still">{final}</g>'
        f'<rect width="{W}" height="{H}" filter="url(#grain)" opacity="0.5"/>'
        f'<text x="48" y="64" font-family="Shippori,serif" font-weight="800" font-size="36" fill="{SUMI}">墨流し · Floating ink</text>'
        f'<text x="48" y="97" font-family="Shippori,serif" font-weight="500" font-size="20" fill="{SUMI}" opacity="0.8">'
        f'A drop for every day of the last four weeks; a busier day, a wider ring.</text>'
        f'<text x="48" y="{H - 40}" font-family="InterTight,sans-serif" font-weight="600" font-size="13" letter-spacing="1.8" '
        f'fill="{SUMI}" opacity="0.66">{esc(stats)}</text>'
        f'<text x="{W - 48}" y="{H - 40}" text-anchor="end" font-family="InterTight,sans-serif" font-weight="600" '
        f'font-size="13" letter-spacing="1.8" fill="{SUMI}" opacity="0.66">REDRAWN EACH MORNING</text>'
        f'</svg>')


def still_water() -> str:
    """The bath before its first morning: no drops, and no numbers to stand in for real ones."""
    css = fonts()
    return (
        f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {W} {H}" width="{W}" height="{H}" role="img" aria-labelledby="t">'
        f'<title id="t">Suminagashi: still water until the first morning run</title><style>{css}</style>'
        f'<rect width="{W}" height="{H}" fill="{PAPER}"/>'
        f'<text x="48" y="64" font-family="Shippori,serif" font-weight="800" font-size="36" fill="{SUMI}">墨流し · Floating ink</text>'
        f'<text x="48" y="97" font-family="Shippori,serif" font-weight="500" font-size="20" fill="{SUMI}" opacity="0.8">'
        f'A drop for every day of the last four weeks; a busier day, a wider ring.</text>'
        f'<text x="48" y="{H - 40}" font-family="InterTight,sans-serif" font-weight="600" font-size="13" letter-spacing="1.8" '
        f'fill="{SUMI}" opacity="0.66">STILL WATER UNTIL THE FIRST MORNING RUN</text></svg>')


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--login', default=os.environ.get('GITHUB_LOGIN', 'bacuslee'))
    ap.add_argument('--sample', action='store_true', help='draw a made-up month instead of fetching')
    ap.add_argument('--data', type=pathlib.Path, help='a JSON list of [date, count] pairs')
    ap.add_argument('--still', action='store_true', help='draw the empty bath, before any data')
    args = ap.parse_args()
    if args.still:
        OUT.write_text(still_water(), encoding='utf-8')
        today = dt.date.today()
        blank = [((today - dt.timedelta(days=365 - k)).isoformat(), 0) for k in range(366)]
        YEAR.write_text(year.render(blank, fonts(), waiting=True), encoding='utf-8')
        print('ink/bath.svg, ink/year.svg  still water, still paper')
        return
    if args.data:
        days = [tuple(d) for d in json.loads(args.data.read_text())]
    elif args.sample:
        days = sample()
    else:
        token = os.environ.get('GITHUB_TOKEN')
        if not token:
            raise SystemExit('Set GITHUB_TOKEN, or pass --sample.')
        days = fetch(args.login, token)
    svg = render(days[-DAYS:])
    OUT.write_text(svg, encoding='utf-8')
    print(f'ink/bath.svg  {len(svg.encode()) / 1024:.0f} KB  ({days[-DAYS][0]} to {days[-1][0]})')
    svg = year.render(days, fonts())
    YEAR.write_text(svg, encoding='utf-8')
    print(f'ink/year.svg  {len(svg.encode()) / 1024:.0f} KB  ({days[0][0]} to {days[-1][0]})')


if __name__ == '__main__':
    main()

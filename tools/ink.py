"""Shared pieces for the profile's ink SVGs.

The profile is the same day as bacuslee.com, read top to bottom like an
unrolled handscroll. GitHub shows README images through <img>, so every panel
is a self-contained SVG: paintings and gold clouds are embedded as WebP, type
is embedded as a font subset, and all motion is CSS keyframes (no script, no
external requests). Everything moves on the site's one tempo, 90 BPM.
"""
from __future__ import annotations

import base64
import io
import json
import math
import pathlib
import re
from collections import defaultdict

from PIL import Image

HERE = pathlib.Path(__file__).resolve().parent
SOURCE = HERE / 'source'

# ---- the site's palette (index.css) ----
WASHI = '#efede8'
PAPER = '#f1f0eb'
SUMI = '#0b0b0c'
INK = '#0d0d0d'
MUTE = '#6d6c66'
SHU = '#c13a24'
SEAL_WHITE = '#fff6ef'
NIGHT = '#05070f'

# ---- one tempo (lib/motion.ts) ----
BPM = 90
BEAT = 60 / BPM


def beats(n: float) -> float:
    return n * BEAT


def jhk(t: float) -> float:
    """Jo-ha-kyū: a slow opening that settles, a break that gathers speed, a swift finish."""
    if t <= 0:
        return 0.0
    if t >= 1:
        return 1.0
    if t < 0.45:
        u = t / 0.45
        return 0.14 * u * u * (3 - 2 * u)
    if t < 0.8:
        u = (t - 0.45) / 0.35
        return 0.14 + 0.56 * u ** 2.4
    u = (t - 0.8) / 0.2
    return 0.7 + 0.3 * (1 - (1 - u) ** 4)


def twos(seconds: float) -> int:
    """Drawings for a duration drawn at 12 a second (anime 'on twos')."""
    return max(1, round(seconds * 12))


def pct(t: float, cycle: float) -> str:
    return f'{max(0.0, min(100.0, 100 * t / cycle)):.3f}%'


# ---- type ----
# Shippori Mincho B1 for Japanese and display, Inter Tight for labels: the
# site's voices on the day. Sources are the Google Fonts masters (SIL OFL 1.1);
# each SVG embeds only the glyphs it sets.
FONT_FILES = {
    ('mincho', 500): 'ShipporiMinchoB1-Medium.ttf',
    ('mincho', 800): 'ShipporiMinchoB1-ExtraBold.ttf',
    ('sans', 500): 'InterTight[wght].ttf',
    ('sans', 600): 'InterTight[wght].ttf',
    ('sans', 760): 'InterTight[wght].ttf',
}
FAMILY = {'mincho': 'Shippori', 'sans': 'InterTight'}
FALLBACK = {
    'mincho': '"Hiragino Mincho ProN","Yu Mincho","Noto Serif JP",Georgia,serif',
    'sans': 'system-ui,-apple-system,"Segoe UI",sans-serif',
}


class FontBook:
    """Loads the master fonts once and hands out subsets and measurements."""

    def __init__(self, font_dir: pathlib.Path):
        self.dir = pathlib.Path(font_dir)
        self._fonts: dict[tuple[str, int], object] = {}

    def font(self, family: str, weight: int):
        from fontTools.ttLib import TTFont
        key = (family, weight)
        if key not in self._fonts:
            f = TTFont(self.dir / FONT_FILES[key])
            if 'fvar' in f:
                from fontTools.varLib import instancer
                f = instancer.instantiateVariableFont(f, {'wght': weight})
            self._fonts[key] = f
        return self._fonts[key]

    def advance(self, family: str, weight: int, text: str, size: float, spacing: float = 0) -> float:
        """Width of a run in user units: advances only, which is how the SVGs set it."""
        f = self.font(family, weight)
        cmap = f.getBestCmap()
        hmtx = f['hmtx']
        upem = f['head'].unitsPerEm
        w = 0.0
        for ch in text:
            g = cmap.get(ord(ch))
            w += (hmtx[g][0] if g else upem / 2) / upem * size
        return w + spacing * size * max(0, len(text) - 1)

    def woff2(self, family: str, weight: int, chars: str) -> bytes:
        from copy import deepcopy
        from fontTools import subset
        f = deepcopy(self.font(family, weight))
        opts = subset.Options()
        opts.flavor = 'woff2'
        opts.layout_features = ['kern', 'liga', 'palt', 'vert', 'vrt2', 'ss01', 'zero']
        opts.hinting = False
        opts.desubroutinize = True
        opts.name_IDs = []
        opts.notdef_outline = False
        s = subset.Subsetter(opts)
        s.populate(text=chars)
        s.subset(f)
        f.flavor = 'woff2'
        buf = io.BytesIO()
        f.save(buf)
        return buf.getvalue()



# ---- images ----

def data_uri(path: pathlib.Path | Image.Image, width: int | None = None, quality: int = 80, crop=None) -> str:
    im = path if isinstance(path, Image.Image) else Image.open(path)
    if crop:
        im = im.crop(crop)
    if width and im.width != width:
        im = im.resize((width, round(im.height * width / im.width)), Image.LANCZOS)
    buf = io.BytesIO()
    im.save(buf, 'WEBP', quality=quality, method=6)
    return 'data:image/webp;base64,' + base64.b64encode(buf.getvalue()).decode()


def image_size(path: pathlib.Path) -> tuple[int, int]:
    with Image.open(path) as im:
        return im.size


# ---- the document ----

def esc(s: str) -> str:
    return s.replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;').replace('"', '&quot;')


class Svg:
    """A self-contained SVG: collects defs, CSS and body, and embeds the type it uses."""

    def __init__(self, w: int, h: int, title: str, desc: str, fonts: FontBook | None = None):
        self.w, self.h = w, h
        self.title, self.desc = title, desc
        self.fonts = fonts
        self.defs: list[str] = []
        self.css: list[str] = []
        self.body: list[str] = []
        self.used: dict[tuple[str, int], set[str]] = defaultdict(set)
        self.reduced: list[str] = []  # rules for prefers-reduced-motion
        self._ids = 0

    def uid(self, prefix='i') -> str:
        self._ids += 1
        return f'{prefix}{self._ids}'

    def add(self, s: str):
        self.body.append(s)

    def text(self, s: str, x: float, y: float, *, font='mincho', weight=800, size=40.0, fill=INK,
             anchor='start', spacing=0.0, upper=False, opacity=1.0, extra='', cls='') -> str:
        s = s.upper() if upper else s
        self.used[(font, weight)].update(s)
        attrs = [f'x="{x:.1f}"', f'y="{y:.1f}"', f'font-family="{FAMILY[font]},{esc(FALLBACK[font])}"',
                 f'font-weight="{weight}"', f'font-size="{size:.1f}"', f'fill="{fill}"']
        if anchor != 'start':
            attrs.append(f'text-anchor="{anchor}"')
        if spacing:
            attrs.append(f'letter-spacing="{spacing * size:.2f}"')
        if opacity != 1:
            attrs.append(f'opacity="{opacity:.2f}"')
        if cls:
            attrs.append(f'class="{cls}"')
        if extra:
            attrs.append(extra)
        return f'<text {" ".join(attrs)}>{esc(s)}</text>'

    def measure(self, s: str, font='mincho', weight=800, size=40.0, spacing=0.0, upper=False) -> float:
        s = s.upper() if upper else s
        return self.fonts.advance(font, weight, s, size, spacing)

    def wrap(self, s: str, width: float, **kw) -> list[str]:
        lines, cur = [], ''
        for word in s.split(' '):
            trial = f'{cur} {word}'.strip()
            if cur and self.measure(trial, **kw) > width:
                lines.append(cur)
                cur = word
            else:
                cur = trial
        if cur:
            lines.append(cur)
        return lines

    def font_css(self) -> str:
        out = []
        for (family, weight), chars in sorted(self.used.items()):
            if not chars or self.fonts is None:
                continue
            b = base64.b64encode(self.fonts.woff2(family, weight, ''.join(sorted(chars)))).decode()
            out.append(f'@font-face{{font-family:{FAMILY[family]};font-weight:{weight};'
                       f'src:url(data:font/woff2;base64,{b}) format("woff2")}}')
        return ''.join(out)

    def render(self) -> str:
        reduced = ''
        if self.reduced:
            reduced = '@media (prefers-reduced-motion:reduce){' + ''.join(self.reduced) + '}'
        style = self.font_css() + ''.join(self.css) + reduced
        return (
            f'<svg xmlns="http://www.w3.org/2000/svg" xmlns:xlink="http://www.w3.org/1999/xlink" '
            f'viewBox="0 0 {self.w} {self.h}" width="{self.w}" height="{self.h}" role="img" '
            f'aria-labelledby="t d">'
            f'<title id="t">{esc(self.title)}</title><desc id="d">{esc(self.desc)}</desc>'
            f'<style>{style}</style><defs>{"".join(self.defs)}</defs>{"".join(self.body)}</svg>'
        )

    def save(self, path: pathlib.Path) -> int:
        data = self.render()
        path.write_text(data, encoding='utf-8')
        return len(data.encode())


# ---- vertical writing ----

def is_cjk(ch: str) -> bool:
    return bool(re.match(r'[　-ヿ㐀-鿿＀-￯]', ch))


def tategaki(doc: Svg, s: str, x: float, y: float, *, font='sans', weight=600, size=22.0,
             spacing=0.22, fill=INK, opacity=0.72, cjk_font='mincho', cjk_weight=500) -> tuple[str, float]:
    """Vertical text set by hand so it reads the same in every browser: kana and
    kanji stand upright, Latin runs turn on their side, as in tategaki."""
    parts, y0 = [], y
    for run in re.findall(r'[　-ヿ㐀-鿿＀-￯]+|[^　-ヿ㐀-鿿＀-￯]+', s):
        if is_cjk(run[0]):
            for ch in run:
                parts.append(doc.text(ch, x, y0 + size * 0.88, font=cjk_font, weight=cjk_weight, size=size * 1.08,
                                      fill=fill, anchor='middle', opacity=opacity))
                y0 += size * 1.12
        else:
            run_s = run.upper()
            w = doc.measure(run_s, font=font, weight=weight, size=size, spacing=spacing)
            parts.append(f'<g transform="translate({x - size * 0.36:.1f} {y0:.1f}) rotate(90)">'
                         + doc.text(run_s, 0, 0, font=font, weight=weight, size=size, fill=fill,
                                    spacing=spacing, opacity=opacity) + '</g>')
            y0 += w + spacing * size
    return ''.join(parts), y0


# ---- KanjiVG strokes ----

def kanji_strokes(ch: str) -> list[str]:
    data = json.loads((HERE / 'kanjivg.json').read_text(encoding='utf-8'))
    return data['strokes'][ch]


def _path_points(d: str, steps=24) -> list[tuple[float, float]]:
    """Sample a KanjiVG path (M/C/S/c/s/L/l) into points, for lengths."""
    toks = re.findall(r'[MmCcSsLlZz]|-?\d*\.?\d+(?:e-?\d+)?', d)
    pts, i, cmd = [], 0, None
    cur = (0.0, 0.0)
    last_ctrl = None

    def num():
        nonlocal i
        v = float(toks[i]); i += 1
        return v

    def cubic(p0, p1, p2, p3):
        for k in range(1, steps + 1):
            t = k / steps
            a = (1 - t) ** 3; b = 3 * (1 - t) ** 2 * t; c = 3 * (1 - t) * t * t; e = t ** 3
            pts.append((a * p0[0] + b * p1[0] + c * p2[0] + e * p3[0], a * p0[1] + b * p1[1] + c * p2[1] + e * p3[1]))

    while i < len(toks):
        if re.match(r'[A-Za-z]', toks[i]):
            cmd = toks[i]; i += 1
            if cmd in 'Zz':
                continue
        if cmd in 'Mm':
            x, y = num(), num()
            cur = (cur[0] + x, cur[1] + y) if cmd == 'm' else (x, y)
            pts.append(cur); last_ctrl = None
            cmd = 'l' if cmd == 'm' else 'L'
        elif cmd in 'Cc':
            v = [num() for _ in range(6)]
            if cmd == 'c':
                v = [v[0] + cur[0], v[1] + cur[1], v[2] + cur[0], v[3] + cur[1], v[4] + cur[0], v[5] + cur[1]]
            cubic(cur, (v[0], v[1]), (v[2], v[3]), (v[4], v[5]))
            last_ctrl = (v[2], v[3]); cur = (v[4], v[5])
        elif cmd in 'Ss':
            v = [num() for _ in range(4)]
            if cmd == 's':
                v = [v[0] + cur[0], v[1] + cur[1], v[2] + cur[0], v[3] + cur[1]]
            c1 = (2 * cur[0] - last_ctrl[0], 2 * cur[1] - last_ctrl[1]) if last_ctrl else cur
            cubic(cur, c1, (v[0], v[1]), (v[2], v[3]))
            last_ctrl = (v[0], v[1]); cur = (v[2], v[3])
        elif cmd in 'Ll':
            x, y = num(), num()
            cur = (cur[0] + x, cur[1] + y) if cmd == 'l' else (x, y)
            pts.append(cur); last_ctrl = None
        else:
            i += 1
    return pts


def path_length(d: str) -> float:
    p = _path_points(d)
    return sum(math.dist(p[k], p[k + 1]) for k in range(len(p) - 1))


def write_kanji(doc: Svg, ch: str, x: float, y: float, size: float, *, color=INK, weight=5.2,
                start=0.0, seconds=2.4, cycle=None, fade_at=None, fade=0.5) -> str:
    """A kanji written with a brush, stroke by stroke (components/motion/InkKanji.tsx):
    KanjiVG centrelines stroked thick, edges roughened like ink in washi. With a
    cycle it loops: written at `start`, held, faded at `fade_at`, then blank."""
    strokes = kanji_strokes(ch)
    lens = [path_length(d) for d in strokes]
    total = sum(lens) or 1
    gap = min(0.08, seconds * 0.25 / max(1, len(strokes)))
    draw = max(0.2, seconds - gap * (len(strokes) - 1))
    fid = doc.uid('ink')
    doc.defs.append(
        f'<filter id="{fid}" x="-10%" y="-10%" width="120%" height="120%">'
        f'<feTurbulence type="fractalNoise" baseFrequency="0.8" numOctaves="2" seed="7" result="g"/>'
        f'<feDisplacementMap in="SourceGraphic" in2="g" scale="1.6" xChannelSelector="R" yChannelSelector="G"/></filter>')
    paths, at = [], start
    for k, (d, L) in enumerate(zip(strokes, lens)):
        dur = draw * (0.35 / len(strokes) + 0.65 * L / total)
        L1 = L + 2
        cls = doc.uid('s')
        if cycle:
            end = fade_at if fade_at is not None else cycle - fade
            doc.css.append(
                f'@keyframes {cls}{{0%,{pct(at, cycle)}{{stroke-dashoffset:{L1:.1f};opacity:0}}'
                f'{pct(at + 0.001, cycle)}{{stroke-dashoffset:{L1:.1f};opacity:1;animation-timing-function:cubic-bezier(.45,0,.55,1)}}'
                f'{pct(at + dur, cycle)},{pct(end, cycle)}{{stroke-dashoffset:0;opacity:1}}'
                f'{pct(end + fade, cycle)},100%{{stroke-dashoffset:0;opacity:0}}}}'
                f'.{cls}{{animation:{cls} {cycle:.3f}s linear infinite}}')
        else:
            doc.css.append(
                f'@keyframes {cls}{{0%{{stroke-dashoffset:{L1:.1f};opacity:1}}100%{{stroke-dashoffset:0;opacity:1}}}}'
                f'.{cls}{{opacity:0;animation:{cls} {dur:.3f}s cubic-bezier(.45,0,.55,1) {at:.3f}s both}}')
        doc.reduced.append(f'.{cls}{{animation:none;opacity:1;stroke-dashoffset:0}}')
        paths.append(f'<path class="{cls}" d="{d}" stroke-dasharray="{L1:.1f} {L1 + 4:.1f}"/>')
        at += dur + gap
    s = size / 109
    return (f'<g transform="translate({x:.1f} {y:.1f}) scale({s:.4f})" filter="url(#{fid})" fill="none" '
            f'stroke="{color}" stroke-width="{weight}" stroke-linecap="round" stroke-linejoin="round">'
            + ''.join(paths) + '</g>')


# ---- Latte's seal ----

def seal(doc: Svg, cx: float, cy: float, size: float, *, at: float | None = None, cycle: float | None = None,
         fade_at: float | None = None, fade=0.5, rest_rotation=-4.0) -> str:
    """Latte's hanko, ラテ in vermilion: pressed down oversized and tilted, then
    three drawings to rest (components/motion/Seal.tsx)."""
    r = size * 0.09
    inner = size * 0.12 / 1.0
    fs = size * 0.36
    body = (
        f'<rect x="{-size / 2:.1f}" y="{-size / 2:.1f}" width="{size:.1f}" height="{size:.1f}" rx="{r:.1f}" fill="{SHU}"/>'
        f'<rect x="{-size / 2 + inner * 0.6:.1f}" y="{-size / 2 + inner * 0.6:.1f}" width="{size - inner * 1.2:.1f}" '
        f'height="{size - inner * 1.2:.1f}" rx="{r * 0.6:.1f}" fill="none" stroke="{SEAL_WHITE}" stroke-width="{size * 0.035:.2f}"/>'
        + doc.text('ラ', 0, -fs * 0.08, font='mincho', weight=800, size=fs, fill=SEAL_WHITE, anchor='middle')
        + doc.text('テ', 0, fs * 0.92, font='mincho', weight=800, size=fs, fill=SEAL_WHITE, anchor='middle')
    )
    cls = doc.uid('seal')
    if at is not None:
        steps = twos(0.25)
        frames = []
        c = cycle or (at + steps / 12 + 1)
        frames.append(f'0%,{pct(at - 0.001, c)}{{opacity:0;transform:scale(1.7) rotate(-14deg)}}')
        for i in range(steps + 1):
            k = i / steps
            frames.append(f'{pct(at + i / 12, c)}{{opacity:1;transform:scale({1.7 - 0.7 * k:.3f}) '
                          f'rotate({-14 + (14 + rest_rotation) * k:.2f}deg)}}')
        if cycle:
            end = fade_at if fade_at is not None else cycle - fade
            frames.append(f'{pct(end, c)}{{opacity:1;transform:scale(1) rotate({rest_rotation}deg)}}')
            frames.append(f'{pct(end + fade, c)},100%{{opacity:0;transform:scale(1) rotate({rest_rotation}deg)}}')
            doc.css.append(f'@keyframes {cls}{{{"".join(frames)}}}.{cls}{{animation:{cls} {c:.3f}s step-end infinite}}')
        else:
            doc.css.append(f'@keyframes {cls}{{{"".join(frames)}}}.{cls}{{animation:{cls} {c:.3f}s step-end both}}')
        doc.css.append(f'.{cls}{{transform-box:fill-box;transform-origin:center}}')
        doc.reduced.append(f'.{cls}{{animation:none;opacity:1;transform:rotate({rest_rotation}deg)}}')
        return f'<g transform="translate({cx:.1f} {cy:.1f})"><g class="{cls}">{body}</g></g>'
    return f'<g transform="translate({cx:.1f} {cy:.1f}) rotate({rest_rotation})">{body}</g>'


def impact(doc: Svg, at: float, cycle: float) -> str:
    """One inverted frame on a payoff (FrameLayer.tsx), about two drawings at 24 fps."""
    cls = doc.uid('hit')
    doc.css.append(
        f'@keyframes {cls}{{0%,{pct(at, cycle)}{{opacity:0}}{pct(at + 0.001, cycle)},{pct(at + 0.084, cycle)}{{opacity:1}}'
        f'{pct(at + 0.085, cycle)},100%{{opacity:0}}}}.{cls}{{opacity:0;mix-blend-mode:difference;'
        f'animation:{cls} {cycle:.3f}s step-end infinite}}')
    doc.reduced.append(f'.{cls}{{animation:none;opacity:0}}')
    return f'<rect class="{cls}" width="{doc.w}" height="{doc.h}" fill="#fff"/>'


# ---- gold kasumi ----

CLOUDS = [SOURCE / f'cloud-{n}.webp' for n in range(1, 7)]


def cloud_symbols(doc: Svg, width=640) -> list[tuple[str, float, float]]:
    """Each painted band once in <defs>; returns (id, w, h) per band at `width`."""
    out = []
    for p in CLOUDS:
        w0, h0 = image_size(p)
        cid = doc.uid('c')
        h = h0 * width / w0
        doc.defs.append(f'<image id="{cid}" width="{width}" height="{h:.1f}" href="{data_uri(p, width=width, quality=78)}"/>')
        out.append((cid, width, h))
    return out

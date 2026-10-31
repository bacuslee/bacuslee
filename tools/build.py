#!/usr/bin/env python3
"""Build the profile's ink SVGs from the site's paintings.

  pip install fonttools brotli pillow numpy
  python3 tools/build.py --fonts DIR

DIR holds the Google Fonts masters (SIL OFL 1.1):
  ShipporiMinchoB1-Medium.ttf, ShipporiMinchoB1-ExtraBold.ttf  (ofl/shipporiminchob1)
  InterTight[wght].ttf                                         (ofl/intertight)

Writes ink/day.svg (the whole day, playing by itself), one hanging scroll per
app (ink/scroll-*.svg) and the small font subsets the daily bath uses
(tools/fonts/). Paintings, clouds and screens come from tools/source, copied
from the site's public/ folder; re-copy them after repainting the site.
"""
from __future__ import annotations

import argparse
import hashlib
import math
import pathlib

import numpy as np
from PIL import Image, ImageDraw, ImageFont

import ink
from ink import (BEAT, INK, SHU, SUMI, WASHI, SOURCE, Svg, beats, data_uri, jhk, pct,
                 seal, tategaki, write_kanji)

ROOT = ink.HERE.parent
OUT = ROOT / 'ink'
W, H = 1600, 900

# ---- the day, as time (components/day/timeline.ts, in beats instead of scroll) ----
# Holds are still frames (ma); hours change by nijimi (a wash soaking in) or
# kasumi (the seam sweeping behind gold mist). Night falls as ink, then a cut
# back to the opening.
STEPS = [
    ('hold', 'opening', 10),
    ('nijimi', 'opening', 'dawn', 3, (0.74, 0.42)),
    ('hold', 'dawn', 9),
    ('kasumi', 'dawn', 'afternoon', 3),
    ('hold', 'afternoon', 9),
    ('kasumi', 'afternoon', 'evening', 3),
    ('hold', 'evening', 14),
    ('nijimi', 'evening', 'night', 3, (0.55, 1.05)),
    ('hold', 'night', 9),
]
CYCLE = beats(sum(s[3] if s[0] != 'hold' else s[2] for s in STEPS))


def timeline():
    """Scene windows in seconds: when each hour starts arriving, has arrived, and is gone."""
    at, win, trans = 0.0, {}, []
    for s in STEPS:
        if s[0] == 'hold':
            d = beats(s[2])
            win.setdefault(s[1], {})['hold'] = (at, at + d)
        else:
            d = beats(s[3])
            win.setdefault(s[2], {})['in'] = (at, at + d)
            win.setdefault(s[1], {})['out'] = (at, at + d)
            trans.append({'kind': s[0], 'from': s[1], 'to': s[2], 't0': at, 't1': at + d,
                          'seed': s[4] if s[0] == 'nijimi' else None})
        at += d
    return win, trans


WIN, TRANS = timeline()


def arrived(scene):
    return WIN[scene]['hold'][0]


# ---- small helpers ----

def h01(*xs) -> float:
    """A stable hash in [0, 1), so every build draws the same picture."""
    b = hashlib.blake2b(repr(xs).encode(), digest_size=8).digest()
    return int.from_bytes(b, 'big') / 2 ** 64


def visible_between(doc: Svg, cls: str, t0: float, t1: float, base_hidden=True, nested=False):
    """Show an element only inside [t0, t1) of the cycle. Whole layers use
    visibility, so hidden hours cost nothing to paint; anything inside a layer
    uses opacity, because a visible child would show through a hidden parent."""
    on, off = ('opacity:1', 'opacity:0') if nested else ('visibility:visible', 'visibility:hidden')
    t0 = max(0.0, t0)
    frames = []
    if t0 > 0:
        frames.append(f'0%{{{off}}}')
    frames.append(f'{pct(t0, CYCLE)}{{{on}}}')
    if t1 < CYCLE:
        frames.append(f'{pct(t1, CYCLE)},100%{{{off}}}')
    doc.css.append(f'@keyframes {cls}v{{{"".join(frames)}}}'
                   f'.{cls}{{{off if base_hidden else on};animation:{cls}v {CYCLE:.3f}s step-end infinite}}')


def sampled(fn, t0, t1, n=14):
    """(time, eased progress) samples across a transition, on jo-ha-kyū."""
    return [(t0 + (t1 - t0) * k / n, jhk(k / n)) for k in range(n + 1)]


def translate_keyframes(doc: Svg, cls: str, windows: list[tuple[float, float, float, float]], rest: float, y=0.0):
    """Move along x across one or more windows (t0, t1, x0, x1) and rest at `rest` otherwise."""
    frames = [f'0%{{transform:translate({rest:.0f}px,{y:.0f}px)}}']
    for t0, t1, x0, x1 in windows:
        frames.append(f'{pct(t0 - 0.001, CYCLE)}{{transform:translate({rest:.0f}px,{y:.0f}px)}}')
        for t, e in sampled(jhk, t0, t1):
            frames.append(f'{pct(t, CYCLE)}{{transform:translate({x0 + (x1 - x0) * e:.0f}px,{y:.0f}px)}}')
        frames.append(f'{pct(t1 + 0.001, CYCLE)}{{transform:translate({rest:.0f}px,{y:.0f}px)}}')
    frames.append(f'100%{{transform:translate({rest:.0f}px,{y:.0f}px)}}')
    doc.css.append(f'@keyframes {cls}m{{{"".join(frames)}}}.{cls}{{animation:{cls}m {CYCLE:.3f}s linear infinite}}')


def smil_values(windows, rest, fmt='{:.1f}'):
    """keyTimes/values for a SMIL animation that eases across windows and holds otherwise."""
    kt, vals = [0.0], [rest(0)]
    for t0, t1, f in windows:
        for t, e in sampled(jhk, t0, t1):
            kt.append(t / CYCLE)
            vals.append(f(e))
    kt.append(1.0)
    vals.append(rest(1))
    # SMIL needs strictly increasing keyTimes
    out_kt, out_v = [], []
    for k, v in zip(kt, vals):
        if out_kt and k <= out_kt[-1]:
            k = out_kt[-1] + 1e-5
        out_kt.append(min(1.0, k))
        out_v.append(v)
    out_kt[-1] = 1.0
    return ';'.join(f'{k:.5f}' for k in out_kt), ';'.join(fmt.format(v) if not isinstance(v, str) else v for v in out_v)


def painting(path: pathlib.Path, focus=(0.5, 0.5), quality=74) -> str:
    """A painting covering the stage, cropped about its focus, as on the site."""
    im = Image.open(path).convert('RGB')
    s = max(W / im.width, H / im.height)
    w, h = round(im.width * s), round(im.height * s)
    im = im.resize((w, h), Image.LANCZOS)
    x = min(max(0, round(focus[0] * w - W / 2)), w - W)
    y = min(max(0, round(focus[1] * h - H / 2)), h - H)
    im = im.crop((x, y, x + W, y + H))
    return f'<image width="{W}" height="{H}" href="{data_uri(im, quality=quality)}"/>'


def print_card(doc: Svg, src: pathlib.Path, x: float, y: float, w: float, caption: str, color=INK) -> str:
    """One real screen lying on its hour like a print: an off-white mat, a soft shadow, a caption."""
    iw, ih = ink.image_size(src)
    h = w * ih / iw
    pad = max(6.0, w * 0.03)
    sid = doc.uid('sh')
    doc.defs.append(f'<filter id="{sid}" x="-20%" y="-20%" width="140%" height="140%">'
                    f'<feDropShadow dx="0" dy="{w * 0.012:.1f}" stdDeviation="{w * 0.03:.1f}" '
                    f'flood-color="#281e14" flood-opacity="0.24"/></filter>')
    img = data_uri(src, width=min(iw, round(w * 1.6)), quality=82)
    cap, cy = '', y + h + pad * 2 + 30
    for ln in doc.wrap(caption, min(max(w + 40, 300), W - x - 28), font='mincho', weight=500, size=20):
        cap += doc.text(ln, x, cy, font='mincho', weight=500, size=20, fill=color, opacity=0.78)
        cy += 28
    return (f'<rect x="{x - pad:.1f}" y="{y - pad:.1f}" width="{w + 2 * pad:.1f}" height="{h + 2 * pad:.1f}" '
            f'fill="#fbf8f2" stroke="#281e14" stroke-opacity="0.12" filter="url(#{sid})"/>'
            f'<image x="{x:.1f}" y="{y:.1f}" width="{w:.1f}" height="{h:.1f}" href="{img}"/>' + cap)


def hour_text(doc: Svg, *, x, y, width, char, label, title, line, tag, go, color=INK, kanji_at=None, kanji_size=104):
    """The text of an hour (DayScroll.tsx): the hour's character written with a
    brush beside its vertical label, then the title, the line and the way in."""
    parts = []
    if kanji_at is not None:
        parts.append(write_kanji(doc, char, x - 4, y, kanji_size, color=color, start=kanji_at, cycle=CYCLE,
                                 fade_at=CYCLE - 0.02, fade=0.01, weight=7.2))
    col, col_end = tategaki(doc, label, x + kanji_size + 22, y + 6, size=17, fill=color, opacity=0.74)
    parts.append(col)
    ty = max(y + kanji_size, col_end) + 26 + 70
    # the title soaks in with a faint vermilion copy that never quite lines up (.misreg)
    parts.append(doc.text(title, x + 2.5, ty + 1.5, size=92, fill=SHU, opacity=0.3))
    parts.append(doc.text(title, x, ty, size=92, fill=color))
    ly = ty + 56
    for ln in doc.wrap(line, width, font='mincho', weight=500, size=34):
        parts.append(doc.text(ln, x, ly, weight=500, size=34, fill=color))
        ly += 44
    ly += 10
    for ln in doc.wrap(tag, width, font='sans', weight=600, size=18, spacing=0.14, upper=True):
        parts.append(doc.text(ln, x, ly, font='sans', weight=600, size=18, spacing=0.14, upper=True, fill=color, opacity=0.7))
        ly += 28
    if go:
        ly += 34
        gw = doc.measure(go, font='mincho', weight=500, size=26)
        parts.append(doc.text(go, x, ly, weight=500, size=26, fill=color))
        parts.append(f'<rect x="{x}" y="{ly + 9}" width="{gw:.1f}" height="1.6" fill="{color}"/>')
    return ''.join(parts), ly


# ---- the opening: Latte drawn in characters (moji-e) ----

GLYPHS = '、丶ノ一二へのもじ人入八十上小土口三工大木水本禾米林来金雨森書猫龍鬱'
CELL = 12


def ranked_glyphs(fonts: ink.FontBook) -> list[str]:
    """Twelve glyphs as even in ink as the set allows, after a blank for bare paper (lib/ink/day.ts)."""
    G = 64
    font = ImageFont.truetype(str(fonts.dir / ink.FONT_FILES[('mincho', 800)]), round(G * 0.84))

    def coverage(c):
        im = Image.new('L', (G, G), 0)
        ImageDraw.Draw(im).text((G / 2, G / 2 + G * 0.05), c, font=font, fill=255, anchor='mm')
        return np.asarray(im, dtype=float).sum() / (255 * G * G)

    ranked = sorted(((coverage(c), c) for c in GLYPHS))
    top = ranked[-1][0]
    steps = [' ']
    for k in range(1, 13):
        want = top * k / 12
        best = min(ranked, key=lambda r: abs(r[0] - want))[1]
        if best not in steps:
            steps.append(best)
    return steps


def smoothstep(e0, e1, x):
    t = np.clip((x - e0) / (e1 - e0), 0, 1)
    return t * t * (3 - 2 * t)


def opening(doc: Svg, fonts: ink.FontBook) -> str:
    portrait = Image.open(SOURCE / 'latte-portrait.webp').convert('RGB')
    a = portrait.width / portrait.height
    ch = 0.9 * H
    cw = ch * a
    x0, y0 = 0.05 * W, 0.05 * H
    cols, rows = int(cw // CELL), int(ch // CELL)
    small = np.asarray(portrait.resize((cols, rows), Image.BOX), dtype=float) / 255
    luma = small @ np.array([0.299, 0.587, 0.114])
    # the site's ramp is smoothstep(0.30, 0.92); a README shows Latte at a third of
    # the size, so the ramp starts lower and mid-grey fur still gets its light glyphs
    inkv = smoothstep(0.16, 0.88, 1 - luma) ** 1.15
    steps = ranked_glyphs(fonts)
    n = len(steps)
    reveal = 2.6
    fs = CELL * 0.84
    # cells grouped by the drawing (12 a second) on which they ink in
    buckets: dict[int, list[tuple[float, float, str]]] = {}
    shu_cells, boil = [], []
    for r in range(rows):
        for c in range(cols):
            idx = int(math.floor(inkv[r, c] * (n - 1) + 0.5))
            if idx <= 0:
                continue
            thr = h01('cell', r, c) * 0.75 + (1 - inkv[r, c]) * 0.25
            frame = max(1, math.ceil(thr * reveal * 12))
            gx = x0 + c * CELL + (CELL - fs) / 2
            gy = y0 + r * CELL + CELL / 2 + fs * 0.36
            if h01('shu', r, c) > 0.995:
                shu_cells.append((gx, gy, steps[idx], frame))
            elif 2 <= idx <= n - 2 and h01('boil', r, c) > 0.985:
                boil.append((gx, gy, steps[idx], steps[idx + (1 if h01('d', r, c) > 0.5 else -1)], frame))
            else:
                buckets.setdefault(frame, []).append((gx, gy, steps[idx]))
    parts = [f'<image width="{W}" height="{H}" preserveAspectRatio="xMidYMid slice" '
             f'href="{data_uri(SOURCE / "washi.webp", width=W, quality=70, crop=(0, 350, 1600, 1250))}"/>']
    glyphs = []

    def bucket_text(cells, fill, frame, cls_hint='g'):
        cls = doc.uid(cls_hint)
        t = frame / 12
        doc.css.append(f'@keyframes {cls}{{0%,{pct(t, CYCLE)}{{opacity:0}}{pct(t + 0.001, CYCLE)},100%{{opacity:1}}}}'
                       f'.{cls}{{animation:{cls} {CYCLE:.3f}s step-end infinite}}')
        doc.reduced.append(f'.{cls}{{animation:none;opacity:1}}')
        s = ''.join(ch for _, _, ch in cells)
        doc.used[('mincho', 800)].update(s)
        xs = ' '.join(f'{x:.1f}' for x, _, _ in cells)
        ys = ' '.join(f'{y:.1f}' for _, y, _ in cells)
        return (f'<text class="{cls}" x="{xs}" y="{ys}" font-family="Shippori" font-weight="800" '
                f'font-size="{fs:.2f}" fill="{fill}">{s}</text>')

    for frame in sorted(buckets):
        glyphs.append(bucket_text(buckets[frame], '#1b1a19', frame))
    for gx, gy, c, frame in shu_cells:
        glyphs.append(bucket_text([(gx, gy, c)], '#b33321', frame, 'r'))
    # a few cells boil between neighbouring glyphs on twos, as drawn lines do
    for k, (gx, gy, ca, cb, frame) in enumerate(boil):
        cls = doc.uid('bo')
        p = 0.5 + 1.5 * h01('bp', k)
        on = h01('bo', k) * 0.7
        doc.css.append(f'@keyframes {cls}{{0%,{on * 100:.1f}%{{opacity:0}}{on * 100 + 4:.1f}%,100%{{opacity:1}}}}'
                       f'.{cls}{{animation:{cls} {p:.2f}s step-end infinite}}')
        doc.reduced.append(f'.{cls}{{animation:none;opacity:0}}')
        glyphs.append(bucket_text([(gx, gy, ca)], '#1b1a19', frame))
        doc.used[('mincho', 800)].update(cb)
        glyphs.append(f'<g class="{cls}"><rect x="{gx - 0.5:.1f}" y="{gy - fs * 0.92:.1f}" width="{fs + 1:.1f}" '
                      f'height="{fs * 1.12:.1f}" fill="#efebe2"/>'
                      f'<text x="{gx:.1f}" y="{gy:.1f}" font-family="Shippori" font-weight="800" font-size="{fs:.2f}" '
                      f'fill="#1b1a19">{cb}</text></g>')

    # the lens: the painting itself, seen through the characters (the site's
    # pointer; here it wanders over Latte on its own)
    lens_r = 150
    lx, ly = x0 + cw / 2, y0 + ch / 2
    motion = (f'<animateMotion dur="{beats(24):.3f}s" repeatCount="indefinite" calcMode="spline" '
              f'keyPoints="0;0.25;0.5;0.75;1" keyTimes="0;0.25;0.5;0.75;1" '
              f'keySplines=".45 0 .55 1;.45 0 .55 1;.45 0 .55 1;.45 0 .55 1" '
              f'path="M 60 -250 C 140 -200 120 -80 40 -40 C -60 10 -170 60 -130 170 C -100 260 20 280 60 180 '
              f'C 100 80 -40 -60 -20 -170 C -10 -230 20 -260 60 -250 Z"/>')
    lens_in, lens_out = doc.uid('li'), doc.uid('lo')
    grad = doc.uid('lg')
    doc.defs.append(f'<radialGradient id="{grad}"><stop offset="0.75" stop-color="#fff"/>'
                    f'<stop offset="1" stop-color="#fff" stop-opacity="0"/></radialGradient>')
    doc.defs.append(f'<mask id="{lens_in}" maskUnits="userSpaceOnUse" x="0" y="0" width="{W}" height="{H}">'
                    f'<g transform="translate({lx:.0f} {ly:.0f})"><g>{motion}<circle r="{lens_r}" fill="url(#{grad})"/></g></g></mask>')
    doc.defs.append(f'<mask id="{lens_out}" maskUnits="userSpaceOnUse" x="0" y="0" width="{W}" height="{H}">'
                    f'<rect width="{W}" height="{H}" fill="#fff"/><g transform="translate({lx:.0f} {ly:.0f})"><g>{motion}'
                    f'<circle r="{lens_r}" fill="#000"/></g></g></mask>')
    lens_cls = doc.uid('lens')
    visible_between(doc, lens_cls, reveal + 0.6, WIN['opening']['out'][0] + 0.2, nested=True)
    doc.reduced.append(f'.{lens_cls}{{animation:none;opacity:0}}')
    portrait_uri = data_uri(portrait, width=640, quality=78)
    parts.append(f'<g mask="url(#{lens_out})">{"".join(glyphs)}</g>')
    parts.append(f'<g class="{lens_cls}"><g mask="url(#{lens_in})"><image x="{x0:.1f}" y="{y0:.1f}" width="{cw:.1f}" '
                 f'height="{ch:.1f}" href="{portrait_uri}" style="mix-blend-mode:multiply"/></g>'
                 f'<g transform="translate({lx:.0f} {ly:.0f})"><g>{motion}<circle r="{lens_r - 1}" fill="none" '
                 f'stroke="#1b1a19" stroke-opacity="0.55" stroke-width="2"/></g></g></g>')
    # under reduced motion the lens rests; the glyphs stay whole
    doc.reduced.append(f'g[mask="url(#{lens_out})"]{{mask:none}}')

    # the words: right of the drawing, as on the site
    tx = max(0.55 * W, x0 + cw + 128)
    tw = min(0.38 * W, 640)
    parts.append(tategaki(doc, 'ラテ · Latte, head of QA', x0 + cw + 34, 0.09 * H, size=17, opacity=0.7)[0])
    lines = doc.wrap('Software engineer in Singapore. These are the apps I make, one for each hour of the day.',
                     tw, font='mincho', weight=500, size=34)
    block_h = 112 * 0.8 + 30 + len(lines) * 46 + 30 + 28 + 60
    top = H / 2 - block_h / 2 + 112 * 0.8
    words = [doc.text('Bacus Lee', tx, top, size=112)]
    ly = top + 64
    for ln in lines:
        words.append(doc.text(ln, tx, ly, weight=500, size=34))
        ly += 46
    ly += 16
    words.append(doc.text('iOS · AI · full stack', tx, ly, font='sans', weight=600, size=19, spacing=0.14, upper=True, opacity=0.68))
    ly += 66
    go = 'Watch, and the day begins'
    words.append(doc.text(go, tx, ly, weight=500, size=26))
    words.append(f'<rect x="{tx}" y="{ly + 9}" width="{doc.measure(go, font="mincho", weight=500, size=26):.1f}" height="1.6" fill="{INK}"/>')
    name_w = doc.measure('Bacus Lee', size=112)
    words.append(seal(doc, tx + name_w + 58, top - 52, 64, at=reveal + BEAT * 0.5, cycle=CYCLE, fade_at=CYCLE - 0.02, fade=0.01))
    words_cls = doc.uid('w')
    out = WIN['opening']['out']
    visible_between(doc, words_cls, beats(1), out[0] + 0.1 * (out[1] - out[0]), base_hidden=False, nested=True)
    doc.reduced.append(f'.{words_cls}{{animation:none;opacity:1}}')
    parts.append(f'<g class="{words_cls}">{"".join(words)}</g>')
    return ''.join(parts)


# ---- the evening's phrase ----

PHRASE = ['E', 'D♯', 'E', 'D♯', 'E', 'B', 'D', 'C', 'A']  # MIDI 76 75 76 75 76 71 74 72 69


def evening_keys(doc: Svg, x: float, y: float, start: float) -> tuple[str, float]:
    """The opening of Für Elise, inked key by key on the beat (EveningKeys.tsx):
    the waiting key is ringed in vermilion, played keys turn to ink, and the
    whole phrase earns Latte's seal."""
    kw, kh, gap = 46, 52, 6
    step = BEAT / 2
    parts = []
    for i, note in enumerate(PHRASE):
        kx = x + i * (kw + gap)
        t_next = start + (i - 1) * step if i else start - step
        t_ink = start + i * step
        nxt, inked = doc.uid('kn'), doc.uid('ki')
        end = CYCLE - 0.02
        doc.css.append(
            f'@keyframes {nxt}{{0%,{pct(t_next, CYCLE)}{{opacity:0}}{pct(t_next + 0.001, CYCLE)},{pct(t_ink, CYCLE)}{{opacity:1}}'
            f'{pct(t_ink + 0.001, CYCLE)},100%{{opacity:0}}}}.{nxt}{{opacity:0;animation:{nxt} {CYCLE:.3f}s step-end infinite}}'
            f'@keyframes {inked}{{0%,{pct(t_ink, CYCLE)}{{opacity:0}}{pct(t_ink + 0.001, CYCLE)},{pct(end, CYCLE)}{{opacity:1}}'
            f'{pct(end + 0.001, CYCLE)},100%{{opacity:0}}}}.{inked}{{animation:{inked} {CYCLE:.3f}s step-end infinite}}')
        doc.reduced.append(f'.{nxt}{{animation:none;opacity:0}}.{inked}{{animation:none;opacity:1}}')
        label_x = kx + kw / 2
        parts.append(
            f'<rect x="{kx}" y="{y}" width="{kw}" height="{kh}" rx="7" fill="#fbf8f2" fill-opacity="0.8" stroke="#1b1a19" stroke-opacity="0.5" stroke-width="1.4"/>'
            + doc.text(note, label_x, y + kh / 2 + 7, font='sans', weight=600, size=19, fill=SUMI, anchor='middle')
            + f'<g class="{nxt}"><rect x="{kx - 3}" y="{y - 3}" width="{kw + 6}" height="{kh + 6}" rx="9" fill="none" stroke="{SHU}" stroke-opacity="0.3" stroke-width="4"/>'
            f'<rect x="{kx}" y="{y}" width="{kw}" height="{kh}" rx="7" fill="none" stroke="{SHU}" stroke-width="1.6"/></g>'
            f'<g class="{inked}"><rect x="{kx}" y="{y}" width="{kw}" height="{kh}" rx="7" fill="{SUMI}"/>'
            + doc.text(note, label_x, y + kh / 2 + 7, font='sans', weight=600, size=19, fill=WASHI, anchor='middle') + '</g>')
    done = start + (len(PHRASE) - 1) * step + BEAT
    row_w = len(PHRASE) * (kw + gap) - gap
    parts.append(seal(doc, x + row_w + 44, y + kh / 2, 46, at=done, cycle=CYCLE, fade_at=CYCLE - 0.02, fade=0.01))
    meta, status = doc.uid('km'), doc.uid('ks')
    visible_between(doc, meta, 0, done, base_hidden=False, nested=True)
    visible_between(doc, status, done, CYCLE, nested=True)
    doc.reduced.append(f'.{meta}{{animation:none;opacity:0}}.{status}{{animation:none;opacity:1}}')
    parts.append(f'<g class="{meta}">' + doc.text('Fig. 3 · The opening of Für Elise, played on the beat.', x, y + kh + 40,
                                                  weight=500, size=20, opacity=0.78) + '</g>')
    parts.append(f'<g class="{status}">' + doc.text('Phrase complete.', x, y + kh + 40, weight=500, size=20, opacity=0.78) + '</g>')
    return ''.join(parts), done


# ---- transitions ----

def nijimi_mask(doc: Svg, tr: dict) -> tuple[str, str]:
    """The next painting soaks in like a wash: a ragged, growing blot, a bleed just
    beyond its edge and pigment pooling at the wet edge. Returns (mask id, rim)."""
    sx, sy = tr['seed']
    cx, cy = sx * W, sy * H
    reach = max(math.dist((cx, cy), c) for c in [(0, 0), (W, 0), (0, H), (W, H)]) * 1.25
    fid = doc.uid('nf')
    doc.defs.append(f'<filter id="{fid}" filterUnits="userSpaceOnUse" x="-200" y="-200" width="{W + 400}" height="{H + 400}">'
                    f'<feTurbulence type="fractalNoise" baseFrequency="0.0065" numOctaves="4" seed="{int(sx * 97)}"/>'
                    f'<feDisplacementMap in="SourceGraphic" scale="260" xChannelSelector="R" yChannelSelector="G"/></filter>')
    kt, vals = smil_values([(tr['t0'], tr['t1'], lambda e: reach * e)], lambda k: 0 if k == 0 else reach)
    kt_b, vals_b = smil_values([(tr['t0'], tr['t1'], lambda e: reach * e + 70 * (1 - e))], lambda k: 0 if k == 0 else reach)
    anim = lambda v, k: f'<animate attributeName="r" dur="{CYCLE:.3f}s" repeatCount="indefinite" keyTimes="{k}" values="{v}"/>'
    mid = doc.uid('nm')
    blur = doc.uid('nb')
    doc.defs.append(f'<filter id="{blur}" filterUnits="userSpaceOnUse" x="-200" y="-200" width="{W + 400}" height="{H + 400}">'
                    f'<feTurbulence type="fractalNoise" baseFrequency="0.0065" numOctaves="4" seed="{int(sx * 97)}"/>'
                    f'<feDisplacementMap in="SourceGraphic" scale="260" xChannelSelector="R" yChannelSelector="G" result="d"/>'
                    f'<feGaussianBlur in="d" stdDeviation="22"/></filter>')
    doc.defs.append(f'<mask id="{mid}" maskUnits="userSpaceOnUse" x="0" y="0" width="{W}" height="{H}">'
                    f'<rect width="{W}" height="{H}" fill="#000"/>'
                    f'<g filter="url(#{blur})"><circle cx="{cx:.0f}" cy="{cy:.0f}" r="0" fill="#fff" fill-opacity="0.22">{anim(vals_b, kt_b)}</circle></g>'
                    f'<g filter="url(#{fid})"><circle cx="{cx:.0f}" cy="{cy:.0f}" r="0" fill="#fff">{anim(vals, kt)}</circle></g></mask>')
    rimf = doc.uid('rf')
    doc.defs.append(f'<filter id="{rimf}" filterUnits="userSpaceOnUse" x="-200" y="-200" width="{W + 400}" height="{H + 400}">'
                    f'<feTurbulence type="fractalNoise" baseFrequency="0.0065" numOctaves="4" seed="{int(sx * 97)}"/>'
                    f'<feDisplacementMap in="SourceGraphic" scale="260" xChannelSelector="R" yChannelSelector="G" result="d"/>'
                    f'<feGaussianBlur in="d" stdDeviation="5"/></filter>')
    kt_r, vals_r = smil_values([(tr['t0'], tr['t1'], lambda e: max(0.0, reach * e - 9))], lambda k: 0 if k == 0 else reach)
    rim_cls = doc.uid('rim')
    visible_between(doc, rim_cls, tr['t0'], tr['t1'], nested=True)
    rim = (f'<g class="{rim_cls}" filter="url(#{rimf})"><circle cx="{cx:.0f}" cy="{cy:.0f}" r="0" fill="none" '
           f'stroke="#1b1a19" stroke-opacity="0.3" stroke-width="18">{anim(vals_r, kt_r)}</circle></g>')
    return mid, rim


def kasumi_parts(doc: Svg, bands) -> tuple[dict, str]:
    """The seam sweeps left to right behind painted gold bands at three depths
    (lib/ink/day.ts TIERS), a pale mist riding along it. Returns a mask per
    kasumi transition and the clouds and mist drawn over the stage."""
    windows = [t for t in TRANS if t['kind'] == 'kasumi']
    masks = {}
    soft = 0.10 * H
    gid = doc.uid('kg')
    doc.defs.append(f'<linearGradient id="{gid}" x1="0" x2="1"><stop offset="0" stop-color="#fff"/>'
                    f'<stop offset="1" stop-color="#fff" stop-opacity="0"/></linearGradient>')
    ar = W / H
    seam = lambda e: (e * (ar + 1.2) - 0.6) * H
    for tr in windows:
        mid = doc.uid('km')
        kt, vals = smil_values([(tr['t0'], tr['t1'], lambda e: f'{seam(e):.0f} 0')],
                               lambda k: f'{seam(1):.0f} 0', fmt='{}')
        # SMIL, not CSS: Chromium does not repaint CSS animation inside a <mask>
        move = (f'<animateTransform attributeName="transform" type="translate" dur="{CYCLE:.3f}s" '
                f'repeatCount="indefinite" keyTimes="{kt}" values="{vals}"/>')
        doc.defs.append(f'<mask id="{mid}" maskUnits="userSpaceOnUse" x="0" y="0" width="{W}" height="{H}">'
                        f'<g>{move}<rect x="{-W * 2}" y="0" width="{W * 2 - soft}" height="{H}" fill="#fff"/>'
                        f'<rect x="{-soft:.0f}" y="0" width="{2 * soft:.0f}" height="{H}" fill="url(#{gid})"/></g></mask>')
        masks[tr['to']] = mid
    over = []
    # the mist along the seam
    mg = doc.uid('mg')
    doc.defs.append(f'<linearGradient id="{mg}" x1="0" x2="1"><stop offset="0" stop-color="#f2ede0" stop-opacity="0"/>'
                    f'<stop offset="0.5" stop-color="#f2ede0" stop-opacity="0.35"/><stop offset="1" stop-color="#f2ede0" stop-opacity="0"/></linearGradient>')
    mist = doc.uid('mi')
    translate_keyframes(doc, mist, [(tr['t0'], tr['t1'], seam(0), seam(1)) for tr in windows], rest=-W)
    over.append(f'<g class="{mist}"><rect x="{-0.38 * H:.0f}" y="0" width="{0.76 * H:.0f}" height="{H}" fill="url(#{mg})"/></g>')
    tiers = [
        dict(y=0.17, d=0.25, o=0.3, sx=1.35, img=3, flip=True),
        dict(y=0.36, d=0.2, o=-0.3, sx=1.2, img=5, flip=False),
        dict(y=0.9, d=0.35, o=-0.24, sx=1.3, img=4, flip=True),
        dict(y=0.55, d=0.55, o=-0.12, sx=1, img=1, flip=True),
        dict(y=0.8, d=0.85, o=0.18, sx=1, img=0, flip=False),
        dict(y=0.08, d=0.9, o=-0.1, sx=1, img=2, flip=False),
        dict(y=0.45, d=1, o=0.1, sx=1, img=0, flip=True),
    ]
    u = min(H, W * 1.6)
    for t in tiers:
        cid, bw0, bh0 = bands[t['img']]
        bh = (0.095 + 0.07 * t['d']) * u
        bw = t['sx'] * bh * bw0 / bh0
        o = t['o'] * u
        m = abs(o) + 0.04 * u
        cx = lambda e: e * (W + bw + 2 * m) - bw / 2 - m + o
        cls = doc.uid('cl')
        translate_keyframes(doc, cls, [(tr['t0'], tr['t1'], cx(0), cx(1)) for tr in windows], rest=-2 * W, y=t['y'] * H)
        flip = 'scale(-1 1) ' if t['flip'] else ''
        over.append(f'<g class="{cls}"><g opacity="{0.5 + 0.45 * t["d"]:.2f}" transform="{flip}translate({-bw / 2:.1f} {-bh / 2:.1f}) '
                    f'scale({bw / bw0:.4f} {bh / bh0:.4f})"><use href="#{cid}"/></g></g>')
    hide = doc.uid('kz')
    doc.reduced.append(f'.{hide}{{display:none}}')
    return masks, f'<g class="{hide}">' + ''.join(over) + '</g>'


# ---- the stage ----

def stage(fonts: ink.FontBook) -> Svg:
    doc = Svg(W, H, 'A day with Latte',
              'Bacus Lee, software engineer in Singapore. One day with Latte the cat, in sumi-e ink: '
              'dawn is OkiPaca, an alarm you can only stop by getting up; the afternoon is HonPaca, an EPUB reader '
              'whose answers cite the page; the evening is AnyScore, sheet music that listens; night is for writing to me.',
              fonts)
    doc.css.append('text{font-kerning:normal}')
    bands = ink.cloud_symbols(doc, width=520)
    layers = []

    # opening
    oc = doc.uid('L')
    visible_between(doc, oc, 0, WIN['opening']['out'][1], base_hidden=False)
    doc.reduced.append(f'.{oc}{{animation:none;visibility:visible}}')
    layers.append(f'<g class="{oc}">{opening(doc, fonts)}</g>')

    masks, clouds = kasumi_parts(doc, bands)

    def unmask_after(mid: str, t1: float) -> str:
        """A mask applies only while its hour arrives. A wash mask is filtered noise,
        and leaving it on through a hold would repaint it every frame."""
        return (f'<animate attributeName="mask" dur="{CYCLE:.3f}s" repeatCount="indefinite" calcMode="discrete" '
                f'keyTimes="0;{t1 / CYCLE:.5f}" values="url(#{mid});none"/>')

    def layer(scene: str, body: str, words: str):
        win = WIN[scene]
        t_in = win['in']
        t_out = win.get('out', (CYCLE, CYCLE))[1]
        cls = doc.uid('L')
        visible_between(doc, cls, t_in[0], t_out)
        doc.reduced.append(f'.{cls}{{animation:none;visibility:hidden}}')
        tr = next(t for t in TRANS if t['to'] == scene)
        if tr['kind'] == 'nijimi':
            mid, rim = nijimi_mask(doc, tr)
            # text cuts out as the wash begins and cuts in once it has soaked through
            wcls = doc.uid('W')
            visible_between(doc, wcls, tr['t0'] + 0.82 * (tr['t1'] - tr['t0']), t_out, nested=True)
            return (f'<g class="{cls}"><g mask="url(#{mid})">{unmask_after(mid, tr["t1"])}'
                    f'{body}{rim}<g class="{wcls}">{words}</g></g></g>')
        out_tr = next((t for t in TRANS if t['from'] == scene), None)
        if out_tr and out_tr['kind'] == 'nijimi':
            wcls = doc.uid('W')
            visible_between(doc, wcls, 0, out_tr['t0'] + 0.1 * (out_tr['t1'] - out_tr['t0']), base_hidden=False, nested=True)
            words = f'<g class="{wcls}">{words}</g>'
        mid = masks[scene]
        return f'<g class="{cls}"><g mask="url(#{mid})">{unmask_after(mid, tr["t1"])}{body}{words}</g></g>'

    # dawn: OkiPaca
    k_at = arrived('dawn') + BEAT * 0.5
    words, _ = hour_text(doc, x=96, y=110, width=440, char='起', label='夜明け · Dawn · 06:10', title='OkiPaca',
                         line='An alarm you can only stop by getting up.',
                         tag='iPhone · on the App Store · ten wake-up missions', go='How it wakes you', kanji_at=k_at)
    words += print_card(doc, SOURCE / 'scene-scanopenfirst.webp', 600, 150, 262, 'Fig. 1 · The alarm won’t stop until you scan.')
    layers.append(layer('dawn', painting(SOURCE / 'dawn-2400.webp', (0.76, 0.5)), words))

    # afternoon: HonPaca
    k_at = arrived('afternoon') + BEAT * 0.5
    words, _ = hour_text(doc, x=870, y=118, width=400, char='本', label='昼下がり · Afternoon', title='HonPaca',
                         line='Read deeply. Keep the surprise.', tag='iPhone · EPUB reader · answers cite the page',
                         go='Open the book', kanji_at=k_at)
    words += print_card(doc, SOURCE / 'screen-reader.webp', 1318, 96, 214, 'Fig. 2 · Reading, as on paper.')
    layers.append(layer('afternoon', painting(SOURCE / 'afternoon-2400.webp', (0.28, 0.5)), words))

    # evening: AnyScore, and the phrase
    k_at = arrived('evening') + BEAT * 0.5
    words, ly = hour_text(doc, x=96, y=72, width=420, char='譜', label='夕暮れ · Evening', title='AnyScore',
                          line='Sheet music that listens.', tag='iPad and iPhone · waits for the right note',
                          go='Hear how it listens', kanji_at=k_at)
    keys, done = evening_keys(doc, 96, ly + 58, k_at + 2.4 + BEAT * 2)
    words += keys
    words += print_card(doc, SOURCE / 'studio-learn-landscape.webp', 660, ly + 30, 300, 'Learn mode, Für Elise.')
    layers.append(layer('evening', painting(SOURCE / 'evening-2400.webp', (0.74, 0.5)), words))
    hit = ink.impact(doc, done, CYCLE)

    # night: write to me
    k_at = arrived('night') + BEAT * 0.5
    words, ly = hour_text(doc, x=850, y=104, width=560, char='文', label='夜 · Night', title='Good night.',
                          line='Write to me.', tag='', go='', color=WASHI, kanji_at=k_at)
    mail = 'bacuslee@gmail.com'
    my = ly + 30
    words += doc.text(mail, 850, my, weight=500, size=42, fill=WASHI)
    words += f'<rect x="850" y="{my + 12}" width="{doc.measure(mail, font="mincho", weight=500, size=42):.1f}" height="1.8" fill="{WASHI}"/>'
    words += doc.text('Singapore · bacuslee.com · LinkedIn · GitHub', 850, my + 66, font='sans', weight=600, size=18,
                      spacing=0.14, upper=True, fill=WASHI, opacity=0.74)
    layers.append(layer('night', painting(SOURCE / 'night-2400.webp', (0.6, 0.5)), words))

    # a one-frame ink card on the cut back to the opening
    cut = doc.uid('cut')
    doc.css.append(f'@keyframes {cut}{{0%,{pct(CYCLE - 0.05, CYCLE)}{{opacity:0}}{pct(CYCLE - 0.049, CYCLE)},100%{{opacity:1}}}}'
                   f'.{cut}{{opacity:0;animation:{cut} {CYCLE:.3f}s step-end infinite}}')
    doc.reduced.append(f'.{cut}{{animation:none;opacity:0}}')

    doc.add(''.join(layers) + clouds + hit + f'<rect class="{cut}" width="{W}" height="{H}" fill="{SUMI}"/>')
    return doc


# ---- the hanging scrolls: one app each, to sit side by side under the day ----

SCROLLS = [
    dict(slug='okipaca', char='起', hour='夜明け · Dawn', title='OkiPaca', line='An alarm you can only stop by getting up.',
         link='iPhone · App Store ↗', painting='dawn-2400.webp', focus=(0.78, 0.6), span=0.36, cloth='#2c4b55'),
    dict(slug='honpaca', char='本', hour='昼下がり · Afternoon', title='HonPaca', line='Read deeply. Keep the surprise.',
         link='iPhone · honpaca.com ↗', painting='afternoon-2400.webp', focus=(0.29, 0.4), span=0.4, cloth='#4a5b46'),
    dict(slug='anyscore', char='譜', hour='夕暮れ · Evening', title='AnyScore', line='Sheet music that listens.',
         link='iPad · anyscore.app ↗', painting='evening-2400.webp', focus=(0.76, 0.48), span=0.42, cloth='#47425c'),
]
SCROLL_CYCLE = beats(18)


def hanging_scroll(fonts: ink.FontBook, s: dict, order: int) -> Svg:
    """A kakemono: cord, rod, mounting cloth with its two hanging strips, gold
    ichimonji bands, the hour's painting and its words on washi, the roller."""
    SW, SH = 560, 1000
    doc = Svg(SW, SH, f'{s["title"]}: {s["line"]}',
              f'A hanging scroll for {s["title"]}, the {s["hour"].split(" · ")[1].lower()} of the day: {s["line"]}', fonts)
    cloth = s['cloth']
    x0, x1 = 70, SW - 70
    honshi = (110, 196, SW - 220, 640)   # x, y, w, h of the paper
    hx, hy, hw, hh = honshi
    weave = doc.uid('wv')
    doc.defs.append(f'<pattern id="{weave}" width="6" height="6" patternUnits="userSpaceOnUse">'
                    f'<rect width="6" height="6" fill="{cloth}"/><path d="M0 6L6 0M-1 1L1 -1M5 7L7 5" stroke="#fff" '
                    f'stroke-opacity="0.07" stroke-width="1.2"/></pattern>')
    shadow = doc.uid('ds')
    doc.defs.append(f'<filter id="{shadow}" x="-20%" y="-10%" width="140%" height="125%"><feDropShadow dx="0" dy="10" '
                    f'stdDeviation="14" flood-color="#1a140c" flood-opacity="0.28"/></filter>')
    parts = []
    # cord from a nail
    parts.append(f'<path d="M{SW / 2} 14 L{x0 + 70} 64 M{SW / 2} 14 L{x1 - 70} 64" stroke="#5a4632" stroke-width="2.4" fill="none"/>'
                 f'<circle cx="{SW / 2}" cy="14" r="5" fill="#3a2c20"/>')
    # mounting, top rod, roller
    parts.append(f'<g filter="url(#{shadow})"><rect x="{x0}" y="60" width="{x1 - x0}" height="{SH - 120}" fill="url(#{weave})"/></g>')
    parts.append(f'<rect x="{x0 - 6}" y="56" width="{x1 - x0 + 12}" height="14" rx="3" fill="#3a2c20"/>')
    # futai: the two narrow strips that hang from the top
    for fx in (hx + hw * 0.3, hx + hw * 0.7):
        parts.append(f'<rect x="{fx - 9:.0f}" y="70" width="18" height="118" fill="{cloth}" stroke="#d8c08a" stroke-opacity="0.55"/>'
                     f'<rect x="{fx - 9:.0f}" y="72" width="18" height="4" fill="#d8c08a" opacity="0.6"/>'
                     f'<rect x="{fx - 9:.0f}" y="180" width="18" height="4" fill="#d8c08a" opacity="0.6"/>')
    # ichimonji: gold bands above and below the paper
    parts.append(f'<rect x="{hx - 14}" y="{hy - 18}" width="{hw + 28}" height="{hh + 36}" fill="#efe6d0"/>'
                 f'<rect x="{hx - 14}" y="{hy - 18}" width="{hw + 28}" height="14" fill="#c7aa63"/>'
                 f'<rect x="{hx - 14}" y="{hy + hh + 4}" width="{hw + 28}" height="14" fill="#c7aa63"/>')
    # the paper and the hour's painting
    parts.append(f'<image x="{hx}" y="{hy}" width="{hw}" height="{hh}" preserveAspectRatio="xMidYMid slice" '
                 f'href="{data_uri(SOURCE / "washi.webp", width=400, quality=70, crop=(300, 300, 900, 1400))}"/>')
    im = Image.open(SOURCE / s['painting']).convert('RGB')
    pw = round(im.width * s['span'])
    ph = round(pw * 300 / hw)
    cx, cy = s['focus'][0] * im.width, s['focus'][1] * im.height
    crop = (max(0, min(im.width - pw, round(cx - pw / 2))), max(0, min(im.height - ph, round(cy - ph / 2))))
    crop = crop + (crop[0] + pw, crop[1] + ph)
    fade = doc.uid('fd')
    doc.defs.append(f'<linearGradient id="{fade}" x1="0" y1="0" x2="0" y2="1"><stop offset="0.72" stop-color="#fff"/>'
                    f'<stop offset="1" stop-color="#fff" stop-opacity="0"/></linearGradient>'
                    f'<mask id="{fade}m"><rect x="{hx}" y="{hy}" width="{hw}" height="300" fill="url(#{fade})"/></mask>')
    parts.append(f'<image x="{hx}" y="{hy}" width="{hw}" height="300" mask="url(#{fade}m)" '
                 f'href="{data_uri(im, width=hw * 2, quality=76, crop=crop)}"/>')
    # the words
    k_at = beats(1 + 3 * order)
    parts.append(write_kanji(doc, s['char'], hx + 18, hy + 312, 82, start=k_at, cycle=SCROLL_CYCLE,
                             fade_at=SCROLL_CYCLE - beats(1.5), fade=beats(0.75), weight=7.2))
    # the hour in pure tategaki: on a scroll the English is not needed
    col, _ = tategaki(doc, s['hour'].split(' · ')[0], hx + 18 + 82 + 22, hy + 316, size=17, opacity=0.78)
    parts.append(col)
    ty = hy + 470
    parts.append(doc.text(s['title'], hx + 20, ty + 1.2, size=50, fill=SHU, opacity=0.3))
    parts.append(doc.text(s['title'], hx + 18, ty, size=50))
    ly = ty + 40
    for ln in doc.wrap(s['line'], hw - 40, font='mincho', weight=500, size=22):
        parts.append(doc.text(ln, hx + 18, ly, weight=500, size=22))
        ly += 30
    parts.append(doc.text(s['link'], hx + 18, hy + hh - 26, weight=500, size=19, opacity=0.8))
    parts.append(seal(doc, hx + hw - 34, hy + hh - 36, 34))
    # the roller and its knobs
    ry = SH - 70
    parts.append(f'<rect x="{x0 - 4}" y="{ry}" width="{x1 - x0 + 8}" height="20" rx="5" fill="#3a2c20"/>'
                 f'<rect x="{x0 - 26}" y="{ry - 2}" width="24" height="24" rx="7" fill="#2a1f16"/>'
                 f'<rect x="{x1 + 2}" y="{ry - 2}" width="24" height="24" rx="7" fill="#2a1f16"/>')
    doc.add(''.join(parts))
    return doc


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--fonts', required=True, type=pathlib.Path, help='folder with the master fonts')
    ap.add_argument('--only', nargs='*', help='build only these outputs (day, scrolls, fonts)')
    args = ap.parse_args()
    fonts = ink.FontBook(args.fonts)
    OUT.mkdir(exist_ok=True)
    want = set(args.only or ['day', 'scrolls', 'fonts'])
    if 'day' in want:
        n = stage(fonts).save(OUT / 'day.svg')
        print(f'ink/day.svg  {n / 1024:.0f} KB  ({CYCLE:.1f} s loop)')
    if 'scrolls' in want:
        for order, s in enumerate(SCROLLS):
            n = hanging_scroll(fonts, s, order).save(OUT / f'scroll-{s["slug"]}.svg')
            print(f'ink/scroll-{s["slug"]}.svg  {n / 1024:.0f} KB')
    if 'fonts' in want:
        # the daily drawings run in an Action without the masters, so they get small subsets
        import year
        latin = ''.join(chr(c) for c in range(0x20, 0x7f)) + '·–—’'
        for name, family, weight, chars in [('mincho-800', 'mincho', 800, latin + '墨流し' + year.CHARS_800),
                                            ('mincho-500', 'mincho', 500, latin + year.CHARS_500),
                                            ('sans-600', 'sans', 600, latin)]:
            out = ink.HERE / 'fonts' / f'{name}.woff2'
            out.write_bytes(fonts.woff2(family, weight, chars))
            print(f'tools/fonts/{name}.woff2  {out.stat().st_size / 1024:.0f} KB')


if __name__ == '__main__':
    main()

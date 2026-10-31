# How this profile was made

[bacuslee.com](https://bacuslee.com) is one day with Latte, painted in sumi-e ink
and read top to bottom like an unrolled handscroll. Before it was built, we
researched what animation and computer graphics could do on the web, then
designed within that. This profile follows the same process for a smaller
medium: first a study of what a GitHub README can actually render, then the
same day retold within those limits.

## 1. What a README can do (October 2026)

| Question | Finding | What we did |
| --- | --- | --- |
| HTML | GitHub's sanitizer keeps `picture`, `source`, `details`, `sub`, `kbd`, `table`, and `align`/`width` attributes. It strips `style`, `class` and `id` ([html-pipeline](https://github.com/gjtorikian/html-pipeline/blob/main/lib/html_pipeline/sanitization_filter.rb), [github/markup](https://github.com/github/markup/blob/master/README.md)). | Layout uses only `align`, `width`, tables and `<sub>`. All the art lives inside images. |
| Light and dark | `<picture>` with `prefers-color-scheme` is the documented way to switch, but it follows the OS rather than the GitHub theme ([docs](https://github.com/github/docs/blob/main/content/get-started/writing-on-github/getting-started-with-writing-and-formatting-on-github/quickstart-for-writing-on-github.md), [discussion](https://github.com/orgs/community/discussions/210983)). | Every image carries its own washi paper or mounting cloth, so it reads on a white page and on a dark one. |
| SVG through `<img>` | Repo SVGs are served as `image/svg+xml` with `default-src 'none'; style-src 'unsafe-inline'; sandbox`. In image mode the browser runs no script and makes no network requests, and links inside the image can't be clicked ([MDN](https://developer.mozilla.org/en-US/docs/Web/SVG/Guides/SVG_as_an_Image)). | Paintings and type are embedded as `data:` WebP images and WOFF2 subsets. Each image is wrapped in one link. We tested under the same headers in Chromium. |
| CSS animation and SMIL | Both run in README SVGs. This is how the contribution snake and the typing-SVG generators work ([Platane/snk](https://github.com/Platane/snk), [readme-typing-svg](https://github.com/DenverCoder1/readme-typing-svg)). | All motion is CSS keyframes and SMIL, and everything runs on one shared loop. |
| Video and GIF | A repo `.mp4` doesn't play inline, and autoplay and loop are stripped ([attaching files](https://github.com/github/docs/blob/main/content/get-started/writing-on-github/working-with-advanced-formatting/attaching-files.md)). GIFs are limited to 256 colours and get heavy fast. | Vector and CSS only. Each animated SVG is between 50 and 600 KB. |
| Live data | The hosted stats cards are unreliable, and github-readme-stats is no longer maintained. Generating images with an Action and the built-in `GITHUB_TOKEN` is the recommended route ([readme](https://github.com/anuraghazra/github-readme-stats)). A public repo's schedules pause after 60 days without activity ([docs](https://github.com/github/docs/blob/main/content/actions/reference/workflows-and-actions/events-that-trigger-workflows.md)). | The bath is drawn by our own Action every morning. Its daily commit keeps the schedule alive. |
| Readers | Hiring managers spend a few minutes on a profile, so pin 3–5 projects with demos and live links ([GitHub's guide](https://github.com/github/docs/blob/main/content/account-and-profile/tutorials/using-your-github-profile-to-enhance-your-resume.md)). A long README pushes the pins down the page. | The whole day plays in one 16:9 image instead of four stacked panels. The apps sit under it as three linked scrolls and a short table. |

Two findings came from testing rather than reading:

- **Chromium doesn't repaint CSS animation inside `<mask>`; SMIL does repaint.** The kasumi seam therefore moves with `animateTransform`, not keyframes.
- **A filtered mask left in place repaints its turbulence every frame.** That took a hold from 60 fps down to 20 fps under software rendering. Each transition mask now switches itself off (a discrete SMIL `animate` of `mask`) once its hour has arrived. Holds run at 60 fps, and only the two-second transitions cost more.

## 2. The day, retold

`ink/day.svg` is the site's home page as time instead of scroll. It follows the
same steps, timing and transitions as `components/day/timeline.ts`:

1. **Opening.** Latte is redrawn in characters (moji-e). Glyphs from the
   site's set are ranked by how much ink they put down, and each cell of the
   portrait gets the glyph that matches its darkness. Cells ink in on twos,
   darker ones first. A few glyphs boil between neighbours, and about 1 in
   200 is vermilion. The site's pointer lens becomes a lens that wanders
   over the cat on its own, showing the painting underneath. Latte's seal is
   stamped beside the name.
2. **Nijimi to dawn.** OkiPaca's painting soaks in like a wash: a ragged
   blot of displaced noise, a bleed just past its edge, and pigment pooling
   at the wet rim. The text cuts out as the wash starts and cuts in once it
   has soaked through.
3. **Kasumi to the afternoon and the evening.** The seam sweeps left to right
   behind the site's six painted gold bands, at its seven depths, with a pale
   mist riding along it. The text dissolves across the same seam.
4. **Evening.** The opening of Für Elise (E D♯ E D♯ E B D C A) is inked key
   by key on eighth notes. The waiting key is ringed in vermilion. The
   finished phrase earns the seal and one inverted impact frame.
5. **Night falls as ink**, then a one-frame cut back to the opening.

Each hour's character (起 本 譜 文) is written stroke by stroke from KanjiVG
centrelines. Lengths are measured from the path data, the brush is weighted
by stroke length, and the edges are roughened with fibrous noise, as in
`InkKanji.tsx`. Everything moves on the site's tempo: 90 BPM, the
jo-ha-kyū ease, and illustrated motion drawn on twos. Visitors who prefer
reduced motion see the opening, finished and still.

## 3. The bath

`ink/bath.svg` is the site's suminagashi, fed by the contribution calendar:

- The last 28 days fall into the water one beat at a time.
- A day with contributions is a drop of ink, wider for a busier day, followed by a drop of clear water, which is what makes the rings. A day off is only water.
- Each week pools around its own centre and presses on the others.
- The busiest day is the one vermilion drop.
- Two tines are drawn through the bath, and then a sheet of washi takes the print.

Every point is moved by the closed-form drop and tine transforms from Lu, Jaffer et al., "Mathematical Marbling" (IEEE CG&A 2012). The method runs the month densely first, then keeps points spaced evenly along each ring's final shape. Each ring is a single SMIL path animation, and the busiest frame holds 60 fps.

`.github/workflows/bath.yml` redraws it at 06:10 Singapore time, when OkiPaca's alarm goes off. It also runs whenever the drawing code changes, and by hand from the Actions tab. If you show private contributions on your profile, they count as drops too.

## 4. Rebuilding

```bash
pip install fonttools brotli pillow numpy
python3 tools/build.py --fonts path/to/fonts     # day, scrolls, bath fonts
python3 tools/bath.py --sample                   # try the bath without a token
GITHUB_TOKEN=... python3 tools/bath.py --login skankhunt44
```

`--fonts` points at the Google Fonts masters: `ShipporiMinchoB1-Medium.ttf`,
`ShipporiMinchoB1-ExtraBold.ttf` and `InterTight[wght].ttf`. `tools/source` holds the paintings, clouds and app
screens, copied from the site's `public/` folder. Copy them again after
repainting the site, then rebuild.

## Credits

- The paintings were generated for bacuslee.com (see the site's `docs/INK_PAINTINGS.md`). App screens are untouched captures from each app.
- Shippori Mincho B1 and Inter Tight are under the SIL Open Font License 1.1 (`tools/fonts/OFL-*.txt`). Each SVG embeds only a subset of them.
- Kanji stroke data comes from [KanjiVG](https://kanjivg.tagaini.net), © Ulrich Apel, CC BY-SA 3.0. `tools/kanjivg.json` and the images drawn from it are shared under the same licence.

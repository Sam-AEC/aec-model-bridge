# README visual set

Editable SVG sources are in `src/`; optimized PNGs are in `docs/images/readme/`.
`build.mjs` is the single source of truth: it writes the SVGs, renders the PNGs and holds the
text (title and `<desc>`) that doubles as alt text.

## Rebuild

Needs Playwright with Chromium and the **Inter** font (the build stops if Inter is missing).
ImageMagick 7 (`magick`) is optional and only shrinks the PNGs.

```bash
# bash
NODE_PATH=$(npm root -g) node docs/design/readme-visuals/build.mjs
```

```powershell
# PowerShell
$env:NODE_PATH = (npm root -g); node docs/design/readme-visuals/build.mjs
```

| Variable | Effect |
|---|---|
| `PNG_DIR` | Output folder for the PNGs (default `docs/images/readme`). |
| `WITH_PLACEHOLDER=1` | Also render `demo-cover.png`, the placeholder cover. Off by default. |

Text stays live `<text>` in the SVGs. The Pier logo is embedded verbatim from
`assets/logo-mark.svg` and is not redrawn. Pixel sizes are exact. When `magick` is found the
PNGs are palette-reduced (128 colours, no dither); the build prints how many were reduced.

## Known gap: palette drift

The colours in `build.mjs` are derived from `docs/design/tokens.md` but no longer match it
(dark background, surface and raised values, and the light-theme brand accent). The panel and
dialogs follow `tokens.md`, so these images are slightly off-palette in dark mode. Fixing it
changes every PNG, so it needs a rebuild on a machine that has Playwright and Inter.

## Assets

| Asset | PNG (docs/images/readme/) | Source (src/) | Size |
|---|---|---|---|
| README hero, light | `readme-hero-light.png` | `readme-hero-light.svg` | 1600 × 700 |
| README hero, dark | `readme-hero-dark.png` | `readme-hero-dark.svg` | 1600 × 700 |
| Workflow, light | `readme-workflow-light.png` | `readme-workflow-light.svg` | 1600 × 500 |
| Workflow, dark | `readme-workflow-dark.png` | `readme-workflow-dark.svg` | 1600 × 500 |
| Social preview | `social-preview.png` | `social-preview.svg` | 1280 × 640 |
| Demo cover (placeholder) | not shipped | `demo-cover.svg` | 1600 × 900 |

The demo cover is only a template with a dashed "screenshot placeholder" box. Do not publish a
PNG of it. Add the PNG only after you have a real capture from live Revit (mock mode returns
canned responses and is not a live demonstration).

## Alt text

Use the SVG title followed by its `<desc>`, exactly as written in `build.mjs`:

- **Hero:** "Find parameter issues. Review the fixes. A BIM model with a door flagged for an empty Mark parameter and a callout showing the reviewed correction. Example values."
- **Workflow:** "Inspect, Propose, Approve, Verify. Four steps: inspect finds an empty Mark, propose drafts a change, approve is a human decision, verify reads the value back. Example values are illustrative."
- **Social preview:** "AEC Model Bridge. AEC Model Bridge with the Pier logo, an architectural model illustration and the line AI-assisted BIM coordination."

## README embed (light and dark)

Use absolute URLs. Relative paths break on directory sites that mirror the README.

```html
<picture>
  <source media="(prefers-color-scheme: dark)" srcset="https://raw.githubusercontent.com/Sam-AEC/aec-model-bridge/main/docs/images/readme/readme-hero-dark.png">
  <img src="https://raw.githubusercontent.com/Sam-AEC/aec-model-bridge/main/docs/images/readme/readme-hero-light.png" alt="Find parameter issues. Review the fixes. A BIM model with a door flagged for an empty Mark parameter and a callout showing the reviewed correction. Example values." width="900">
</picture>
```

Use the same pattern for `readme-workflow-*.png`. Upload `social-preview.png` under
Settings > Social preview.

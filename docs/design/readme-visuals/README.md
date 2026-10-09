# README visual set

Editable SVG sources are in `src/`; optimized PNGs are in `docs/images/readme/`.
Rebuild with `NODE_PATH=$(npm root -g) node docs/design/readme-visuals/build.mjs`
(needs Playwright + Chromium and the Inter font). Text stays live `<text>` in the SVGs.
Palette is taken from `docs/design/tokens.md`. The Pier logo is embedded verbatim from
`assets/logo-mark.svg` and is not redrawn. Pixel sizes are exact; PNGs are palette-reduced
(128 colours, no dither) for size.

| Asset | PNG (docs/images/readme/) | Source (src/) | Size |
|---|---|---|---|
| README hero, light | `readme-hero-light.png` | `readme-hero-light.svg` | 1600 × 700 |
| README hero, dark | `readme-hero-dark.png` | `readme-hero-dark.svg` | 1600 × 700 |
| Workflow, light | `readme-workflow-light.png` | `readme-workflow-light.svg` | 1600 × 500 |
| Workflow, dark | `readme-workflow-dark.png` | `readme-workflow-dark.svg` | 1600 × 500 |
| Social preview | `social-preview.png` | `social-preview.svg` | 1280 × 640 |
| Demo cover | `demo-cover.png` | `demo-cover.svg` | 1600 × 900 |

## Alt text

- **Hero:** "Find parameter issues. Review the fixes. A BIM model with one door flagged for an empty Mark value and a callout showing the reviewed correction. Example values."
- **Workflow:** "Four steps: Inspect finds an empty Mark, Propose drafts a change, Approve is a human decision, Verify reads the value back. Example values are illustrative."
- **Social preview:** "AEC Model Bridge: AI-assisted BIM coordination, with the Pier logo and an isometric building model."
- **Demo cover:** "Fix missing parameters in Revit. Inspect. Review. Approve. Verify. A placeholder reserves space for a screenshot from the synthetic test model."

## README embed (light/dark)

```html
<picture>
  <source media="(prefers-color-scheme: dark)" srcset="docs/images/readme/readme-hero-dark.png">
  <img src="docs/images/readme/readme-hero-light.png" alt="Find parameter issues. Review the fixes. A BIM model with one door flagged for an empty Mark value and a callout showing the reviewed correction. Example values." width="900">
</picture>
```

Use the same pattern for `readme-workflow-*.png`. Upload `social-preview.png` under
Settings > Social preview. Swap `demo-cover.png` for a real capture from live Revit
(synthetic test model) before publishing; mock mode returns canned responses and is not
a live Revit demonstration.

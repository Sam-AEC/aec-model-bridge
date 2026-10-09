# README visual brief

Paste the prompt below into Claude Design. Supply `assets/logo-mark.svg`,
`assets/logo.svg` and `docs/design/tokens.md` as references. Add real screenshots
when the synthetic-model demo has been recorded.

## Prompt

Design a GitHub README visual set for **AEC Model Bridge**, an MCP server and
native Revit add-in that lets AI assistants inspect BIM models and propose
changes for human approval.

The audience is BIM coordinators. The first story is finding and fixing missing
or inconsistent parameters. Use a precise architectural graphic style, clean
typography, generous spacing, restrained teal accents and strong contrast. Keep
the current Pier logo unchanged. Use the current palette from the supplied
design tokens: dark tile `#111923`, teal `#1CB5CA`, white and slate. Where the
tokens describe an older logo, follow the current Pier mark in the supplied SVG.

Avoid orbit diagrams, floating logo collections, stock construction photos,
robot imagery and excessive glow. Make the relationship between a model issue,
a proposed correction and human approval easy to understand.

Produce these assets:

| Asset | Size | Content |
| --- | --- | --- |
| README hero | 1600 × 700 | Architectural model illustration, a missing parameter and a reviewed correction. Headline: “Find parameter issues. Review the fixes.” Supporting line: “AI-assisted BIM coordination with human approval.” |
| Workflow | 1600 × 500 | Four steps: “Inspect → Propose → Approve → Verify.” Missing values, a proposed change table, a human approval step, then checked results. |
| Social preview | 1280 × 640 | Project name, Pier logo, one architectural model illustration and “AI-assisted BIM coordination.” |
| Demo cover | 1600 × 900 | “Fix missing parameters in Revit.” Subtitle: “Inspect. Review. Approve. Verify.” Leave a large area for a real screenshot; label it “Screenshot placeholder” until supplied. |

Create light and dark variants of the hero and workflow. Supporting labels must
remain readable when displayed at 900 px wide. Keep text editable in the source.
Export editable source and optimized PNGs, with filenames and short alt text.
Use `readme-hero-light.png`, `readme-hero-dark.png`, `parameter-workflow-light.png`,
`parameter-workflow-dark.png`, `social-preview.png` and `parameter-demo-cover.png`.

The synthetic fixture is intended to seed 12 doors with missing Marks and three
rooms with missing Numbers. These are fixture expectations, not measured demo
results. Show before/after values as illustrative examples until real capture
is supplied. Do not fabricate a Revit screenshot or a successful test result.
Mock mode returns canned responses; it is not a live Revit demonstration.
The VS Code extension is under local review and is not published. Do not show
Marketplace availability, invented usage statistics or customer logos. Revit
is the primary integration; Navisworks and Power BI are in progress.

First propose two distinct compositions and recommend one. Then produce the
assets. Favor clarity at GitHub README size over decorative detail.

## Acceptance before adding artwork

- Review the assets at the actual README display width in light and dark themes.
- Replace screenshot placeholders with captures from the synthetic model.
- Keep mockups identified as illustrations; reserve result counts for live evidence.
- Store accepted images under `docs/images/` and use relative README paths.
- Use the social preview separately in GitHub repository settings after review.

The existing architecture and approval diagrams remain technical references.
This brief replaces the ecosystem artwork as the direction for promotional images.

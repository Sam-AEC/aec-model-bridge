# Brand mark

The brand is the mark only. It is text-free: no name, tagline or lettering is baked into any mark file. The name is set as live text beside it where needed.

The mark is "Ember mesh": three jackal heads inside an ouroboros ring, built from flat triangular facets with ember-orange eyes.

## Clear space

Keep free space around the mark equal to half the ring height on every side. Nothing (text, edges, other logos) enters that zone.

## Minimum sizes

| Size | Use this file |
| --- | --- |
| 16 px | `assets/brand/mark-16.svg` (solid shapes; the three heads merge into one masked head) |
| 24 to 48 px | `assets/brand/mark-32.svg` (coarse mesh, no glow, no edge lines) |
| 64 px and up | `assets/logo-mark.svg` (full mesh) |

## Mono use

`assets/brand/mark-mono.svg` is one colour (`fill="currentColor"`), for single-colour print, themes and disabled states. `assets/brand/mark-mono-badge.svg` is a near-black disc with a white mark and works on any background. `assets/brand/mark-dark-disc.svg` is the full mark on its own dark disc, for dark UIs and avatars.

## Do not

- Put text inside or on the mark.
- Recolour the eyes.
- Add glow below 64 px.
- Stretch, rotate, crop or re-draw the mark.
- Use the full mesh below 64 px; use the 32 px or 16 px version.

## File inventory

| File | Purpose |
| --- | --- |
| `assets/logo-mark.svg`, `assets/logo.svg` | Full-colour master (identical, text-free) |
| `assets/logo-mark-512.png` | 512 px raster, transparent |
| `assets/icon.ico` | 16, 24, 32, 48, 64, 128, 256 px; installer and shortcuts |
| `assets/installer/wizard-large.bmp` | 164x314, 24-bit, Inno Setup side panel |
| `assets/installer/wizard-small.bmp` | 55x58, 24-bit, Inno Setup header |
| `assets/brand/*.svg` | Mono, mono badge, dark disc, 32 px and 16 px variants |
| `assets/social-preview.png` | 1280x640 GitHub social preview |
| `extensions/vscode/media/icon.png` | 256x256 VS Code extension icon |

## Social preview

GitHub takes the link-card image from the repository settings, not from a file in the tree. Upload `assets/social-preview.png` under repository Settings, General, Social preview. Only a repository admin can set it.

## Provenance

The mark is original vector artwork. No AI-generated raster image was traced. Its lineage is cited, not copied:

- the ouroboros motif, as in the Chrysopoeia of Cleopatra (Marcian MS gr. Z. 299, 10th to 11th century);
- the low-poly faceted emblem style;
- the Greek myth of Kerberos, the many-headed guardian of the threshold (Hesiod, Theogony 310 to 312).

The previous "Pier" mark is retired. `scripts/make_brand_assets.py`, which drew it, no longer runs.

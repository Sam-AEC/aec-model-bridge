// Builds the README visual set: editable SVG sources + PNG exports.
//
//   bash:        NODE_PATH=$(npm root -g) node docs/design/readme-visuals/build.mjs
//   PowerShell:  $env:NODE_PATH = (npm root -g); node docs/design/readme-visuals/build.mjs
//
// Needs Playwright with Chromium and the Inter font installed (the build stops if Inter
// is missing). ImageMagick 7 (`magick`) is optional and only shrinks the PNGs.
// Env: PNG_DIR = output folder (default docs/images/readme),
//      WITH_PLACEHOLDER=1 also renders the demo-cover placeholder PNG.
// PALETTE NOTE: the values in THEMES are derived from docs/design/tokens.md but have
// drifted from it (dark bg/surface/raised, light brand accent). Aligning them needs a
// rebuild on a machine with Playwright and Inter. The Pier logo is embedded verbatim
// from assets/logo-mark.svg and is never redrawn.
import fs from 'node:fs';
import path from 'node:path';
import { createRequire } from 'node:module';
import { fileURLToPath } from 'node:url';
import { execFileSync } from 'node:child_process';

const require = createRequire(import.meta.url);
const { chromium } = require('playwright');

const here = path.dirname(fileURLToPath(import.meta.url));
const root = path.resolve(here, '../../..');
const srcDir = path.join(here, 'src');
const pngDir = process.env.PNG_DIR || path.join(root, 'docs/images/readme');
fs.mkdirSync(srcDir, { recursive: true });
fs.mkdirSync(pngDir, { recursive: true });

// ---------------------------------------------------------------- tokens
const THEMES = {
  light: {
    bg: '#F2F5F8', surface: '#FFFFFF', raised: '#E9EEF4', line: '#D3DAE3',
    ink: '#18202C', muted: '#5B6676', brand: '#1CB5CA', brandText: '#046B80',
    warn: '#A45F0B', warnBg: 'rgba(164,95,11,0.12)', ok: '#127A4B', okBg: 'rgba(18,122,75,0.12)',
    pend: '#6D3FB8', pendBg: 'rgba(109,63,184,0.12)', btnText: '#0B1118',
    top: '#FFFFFF', left: '#EAF0F5', right: '#D6DFE9', stroke: '#18202C',
    glass: 'rgba(28,181,202,0.22)', ground: '#E4EAF0', logoRing: 'none',
  },
  dark: {
    bg: '#0D131B', surface: '#151D28', raised: '#1C2530', line: '#2F3945',
    ink: '#E9EEF5', muted: '#9BA8B9', brand: '#1CB5CA', brandText: '#6FD8E6',
    warn: '#F2A63C', warnBg: 'rgba(242,166,60,0.16)', ok: '#3FCB8B', okBg: 'rgba(63,203,139,0.16)',
    pend: '#B79AF0', pendBg: 'rgba(183,154,240,0.16)', btnText: '#0B1118',
    top: '#2D3B4A', left: '#1E2935', right: '#141C26', stroke: '#C9D4E2',
    glass: 'rgba(28,181,202,0.30)', ground: '#111A24', logoRing: '#3A4756',
  },
};
const FONT = "Inter, 'Helvetica Neue', Arial, sans-serif";

// ---------------------------------------------------------------- helpers
const esc = (s) => String(s).replace(/&/g, '&amp;').replace(/</g, '&lt;');
const f1 = (n) => (+n).toFixed(1);

const text = (x, y, s, { size = 26, weight = 500, fill, anchor, ls, italic, id } = {}) =>
  `<text${id ? ` id="${id}"` : ''} x="${x}" y="${y}" font-size="${size}" font-weight="${weight}" fill="${fill}"` +
  `${anchor ? ` text-anchor="${anchor}"` : ''}${ls ? ` letter-spacing="${ls}"` : ''}${italic ? ' font-style="italic"' : ''}>${esc(s)}</text>`;

const rect = (x, y, w, h, r = 0, o = {}) =>
  `<rect x="${x}" y="${y}" width="${w}" height="${h}"${r ? ` rx="${r}"` : ''} fill="${o.fill ?? 'none'}"` +
  `${o.stroke ? ` stroke="${o.stroke}" stroke-width="${o.sw ?? 2}"` : ''}${o.dash ? ` stroke-dasharray="${o.dash}"` : ''}/>`;

const line = (x1, y1, x2, y2, stroke, w = 2, extra = '') =>
  `<line x1="${x1}" y1="${y1}" x2="${x2}" y2="${y2}" stroke="${stroke}" stroke-width="${w}" stroke-linecap="round" ${extra}/>`;

const check = (cx, cy, r, color, onColor) =>
  `<circle cx="${cx}" cy="${cy}" r="${r}" fill="${color}"/>` +
  `<path d="M${cx - r * 0.42} ${cy + r * 0.02} L${cx - r * 0.1} ${cy + r * 0.34} L${cx + r * 0.46} ${cy - r * 0.34}" fill="none" stroke="${onColor}" stroke-width="${r * 0.2}" stroke-linecap="round" stroke-linejoin="round"/>`;

const arrow = (x1, y, x2, color, w = 3) =>
  line(x1, y, x2 - 4, y, color, w) +
  `<path d="M${x2 - 14} ${y - 9} L${x2} ${y} L${x2 - 14} ${y + 9}" fill="none" stroke="${color}" stroke-width="${w}" stroke-linecap="round" stroke-linejoin="round"/>`;


// Pier logo: the inner markup of assets/logo-mark.svg, untouched.
const logoSrc = fs.readFileSync(path.join(root, 'assets/logo-mark.svg'), 'utf8');
const logoBox = Number((logoSrc.match(/viewBox="0 0 (\d+)/) || [])[1]) || 96;
const logoInner = logoSrc
  .replace(/^[\s\S]*?<svg[^>]*>/, '')
  .replace(/<\/svg>\s*$/, '')
  .trim();
const logo = (T, x, y, size) =>
  `<g id="pier-logo" transform="translate(${x} ${y}) scale(${size / logoBox})">${logoInner}</g>` +
  (T.logoRing !== 'none'
    ? `<rect x="${x}" y="${y}" width="${size}" height="${size}" rx="${(20 * size) / 96}" fill="none" stroke="${T.logoRing}" stroke-width="1.5"/>`
    : '');

const svgDoc = (w, h, T, title, desc, body) =>
  `<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 ${w} ${h}" width="${w}" height="${h}" role="img" aria-labelledby="t d" ` +
  `font-family="${FONT}">\n` +
  `<title id="t">${esc(title)}</title><desc id="d">${esc(desc)}</desc>\n` +
  `<rect id="background" width="${w}" height="${h}" fill="${T.bg}"/>\n${body}\n</svg>\n`;

// ---------------------------------------------------------------- BIM model illustration
// Isometric block model: three storeys, a roof plant volume, a ground plate with
// grid lines. door: 'issue' (amber, missing parameter) | 'fixed' (teal) | 'none'.
function model(T, { s, ox, oy, door = 'issue', grid = true }) {
  const C = Math.cos(Math.PI / 6);
  const X = 7, Y = 4, fh = 1.1, H = 3 * fh;
  const P = (x, y, z) => [ox + (x - y) * C * s, oy + (x + y) * 0.5 * s - z * s];
  const pts = (a) => a.map((p) => `${f1(p[0])},${f1(p[1])}`).join(' ');
  const sw = Math.max(1.5, s / 16);
  const thin = Math.max(1, s / 30);
  const poly = (a, fill, stroke = T.stroke, w = sw) =>
    `<polygon points="${pts(a)}" fill="${fill}" stroke="${stroke}" stroke-width="${w}" stroke-linejoin="round"/>`;
  const L = (u0, u1, v0, v1) => [P(u0, Y, v0), P(u1, Y, v0), P(u1, Y, v1), P(u0, Y, v1)];
  const Rr = (u0, u1, v0, v1) => [P(X, u0, v0), P(X, u1, v0), P(X, u1, v1), P(X, u0, v1)];
  const warn = T.warn;
  let o = `<g id="model-illustration">`;

  // ground plate + grid
  o += poly([P(-1, -1, 0), P(X + 1, -1, 0), P(X + 1, Y + 1, 0), P(-1, Y + 1, 0)], T.ground, T.line, thin);
  if (grid) {
    const labels = ['A', 'B', 'C'];
    [0, 3.5, 7].forEach((x, i) => {
      const a = P(x, -1, 0), b = P(x, Y + 1.7, 0), c = P(x, Y + 2.15, 0);
      o += line(f1(a[0]), f1(a[1]), f1(b[0]), f1(b[1]), T.line, thin * 1.4, 'stroke-dasharray="7 6"');
      o += `<circle cx="${f1(c[0])}" cy="${f1(c[1])}" r="${s * 0.42}" fill="${T.bg}" stroke="${T.muted}" stroke-width="${thin}"/>`;
      o += text(f1(c[0]), f1(c[1] + s * 0.17), labels[i], { size: Math.round(s * 0.5), weight: 600, fill: T.muted, anchor: 'middle' });
    });
  }

  // main block
  o += poly([P(0, 0, H), P(X, 0, H), P(X, Y, H), P(0, Y, H)], T.top);
  o += poly(L(0, X, 0, H), T.left);
  o += poly(Rr(0, Y, 0, H), T.right);

  // slab lines
  for (let k = 1; k < 3; k++) {
    const a = P(0, Y, k * fh), b = P(X, Y, k * fh), c = P(X, 0, k * fh);
    o += `<polyline points="${pts([a, b, c])}" fill="none" stroke="${T.stroke}" stroke-width="${sw}" stroke-linejoin="round"/>`;
  }

  // windows
  const win = (a) => poly(a, T.glass, T.stroke, thin);
  for (let k = 0; k < 3; k++) {
    for (let i = 0; i < 7; i++) {
      const u = 0.5 + i * 0.9;
      if (k === 0 && Math.abs(u - 3.2) < 0.01) continue; // entrance door
      o += win(L(u, u + 0.6, k * fh + 0.3, k * fh + 0.9));
    }
    [0.4, 1.4, 2.4, 3.3].forEach((u) => {
      if (k === 0 && u < 3.2) return; // doors on the ground floor of this face
      o += win(Rr(u, u + 0.6, k * fh + 0.3, k * fh + 0.9));
    });
  }

  // doors
  const doorFill = T.surface;
  o += poly(L(3.2, 3.8, 0, 0.92), doorFill, T.stroke, thin * 1.3); // entrance
  const doorAt = (u, kind) => {
    const q = Rr(u, u + 0.55, 0, 0.92);
    if (kind === 'issue') return poly(q, T.warnBg, warn, sw * 1.35);
    if (kind === 'fixed') return poly(q, 'rgba(28,181,202,0.35)', T.brand, sw * 1.35);
    if (kind === 'also') return `<polygon points="${pts(q)}" fill="${T.warnBg}" stroke="${warn}" stroke-width="${thin * 1.4}" stroke-dasharray="5 4" stroke-linejoin="round"/>`;
    return poly(q, doorFill, T.stroke, thin * 1.3);
  };
  const flagged = door === 'none' ? 'plain' : door;
  o += doorAt(0.5, flagged);
  o += doorAt(1.6, door === 'issue' ? 'also' : 'plain');
  o += doorAt(2.7, 'plain');

  // roof plant volume
  const x0 = 1.2, x1 = 4.4, y0 = 1, y1 = 3, z0 = H, z1 = H + 0.9;
  o += poly([P(x0, y0, z1), P(x1, y0, z1), P(x1, y1, z1), P(x0, y1, z1)], T.top);
  o += poly([P(x0, y1, z0), P(x1, y1, z0), P(x1, y1, z1), P(x0, y1, z1)], T.left);
  o += poly([P(x1, y0, z0), P(x1, y1, z0), P(x1, y1, z1), P(x1, y0, z1)], T.right);
  o += poly([P(x0 + 0.3, y1, z0 + 0.3), P(x1 - 0.3, y1, z0 + 0.3), P(x1 - 0.3, y1, z1 - 0.25), P(x0 + 0.3, y1, z1 - 0.25)], T.glass, T.stroke, thin);

  o += `</g>`;
  return { svg: o, door: P(X, 0.5 + 0.275, 0.46) };
}

// ---------------------------------------------------------------- cards
function card(T, x, y, w, h, { fill, stroke } = {}) {
  return rect(x, y, w, h, 14, { fill: fill ?? T.surface, stroke: stroke ?? T.line, sw: 2 });
}
// ================================================================= HERO
function hero(name) {
  const T = THEMES[name];
  const W = 1600, H = 700;
  let b = '';
  b += logo(T, 88, 92, 96);
  b += text(88, 330, 'Find parameter issues.', { size: 68, weight: 700, fill: T.ink, ls: -1, id: 'headline-1' });
  b += text(88, 412, 'Review the fixes.', { size: 68, weight: 700, fill: T.brandText, ls: -1, id: 'headline-2' });
  b += rect(90, 442, 96, 6, 3, { fill: T.brand });
  b += text(88, 514, 'AI-assisted BIM coordination', { size: 34, weight: 500, fill: T.muted, id: 'support-1' });
  b += text(88, 560, 'with human approval.', { size: 34, weight: 500, fill: T.muted, id: 'support-2' });
  b += text(88, 640, 'Illustration with example values.', { size: 22, weight: 500, fill: T.muted, id: 'footnote' });

  const m = model(T, { s: 38, ox: 1090, oy: 250, door: 'issue', grid: false });
  b += m.svg;
  const [dx, dy] = m.door;
  b += `<circle cx="${f1(dx)}" cy="${f1(dy)}" r="20" fill="none" stroke="${T.warn}" stroke-width="3"/>`;
  // one callout: issue -> reviewed fix
  const cx = 1010, cy = 530, cw = 500, ch = 124;
  b += `<polyline points="${f1(dx)},${f1(dy + 20)} ${f1(dx)},${cy}" fill="none" stroke="${T.warn}" stroke-width="3"/>`;
  b += rect(cx, cy, cw, ch, 16, { fill: T.surface, stroke: T.line, sw: 2 });
  b += text(cx + 32, cy + 50, 'Door \u00B7 Mark', { size: 26, weight: 600, fill: T.muted });
  b += text(cx + 32, cy + 96, 'empty', { size: 38, weight: 700, fill: T.warn });
  b += arrow(cx + 170, cy + 82, cx + 232, T.muted, 3);
  b += text(cx + 252, cy + 96, 'D-101', { size: 38, weight: 700, fill: T.brandText });
  b += check(cx + cw - 52, cy + 62, 22, T.ok, T.surface);
  return svgDoc(W, H, T, 'Find parameter issues. Review the fixes.',
    'A BIM model with a door flagged for an empty Mark parameter and a callout showing the reviewed correction. Example values.', b);
}

// ================================================================= WORKFLOW
function workflow(name) {
  const T = THEMES[name];
  const W = 1600, H = 500;
  let b = '';
  const cw = 312, gap = 64, x0 = 80, cy = 130, ch = 220;
  const steps = ['Inspect', 'Propose', 'Approve', 'Verify'];
  steps.forEach((s, i) => {
    const x = x0 + i * (cw + gap);
    b += text(x, 88, s, { size: 44, weight: 700, fill: i === 2 ? T.brandText : T.ink });
    b += card(T, x, cy, cw, ch, i === 2 ? { stroke: T.brand } : {});
    if (i < 3) b += arrow(x + cw + 12, cy + ch / 2, x + cw + gap - 12, T.muted, 3);
  });
  b += text(80, 432, 'Missing values become proposed changes. A person approves. Results are checked.', { size: 28, weight: 500, fill: T.muted });
  b += text(80, 472, 'Example values are illustrative.', { size: 22, weight: 500, fill: T.muted, id: 'footnote' });
  const row = (x, y, a, bv, ca, cb) => text(x + 28, y, a, { size: 28, weight: 600, fill: ca }) + text(x + cw - 28, y, bv, { size: 28, weight: 700, fill: cb, anchor: 'end' });
  let x = x0;
  b += row(x, cy + 80, 'Door 0416', 'D-102', T.ink, T.muted);
  b += rect(x + 16, cy + 118, cw - 32, 56, 8, { fill: T.warnBg, stroke: T.warn, sw: 2, dash: '6 5' });
  b += row(x, cy + 155, 'Door 0417', 'empty', T.ink, T.warn);
  x += cw + gap;
  b += text(x + 28, cy + 70, 'Door 0417', { size: 28, weight: 600, fill: T.muted });
  b += text(x + 28, cy + 140, 'empty', { size: 32, weight: 600, fill: T.warn });
  b += arrow(x + 138, cy + 128, x + 176, T.muted, 3);
  b += text(x + 192, cy + 140, 'D-103', { size: 32, weight: 700, fill: T.brandText });
  b += text(x + 28, cy + 190, 'Draft, not applied', { size: 24, weight: 500, fill: T.muted });
  x += cw + gap;
  b += rect(x + 28, cy + 56, cw - 56, 72, 12, { fill: T.brand });
  b += text(x + cw / 2, cy + 104, 'Approve', { size: 34, weight: 700, fill: T.btnText, anchor: 'middle' });
  b += text(x + cw / 2, cy + 176, 'You decide', { size: 28, weight: 500, fill: T.muted, anchor: 'middle' });
  x += cw + gap;
  b += check(x + 52, cy + 90, 26, T.ok, T.surface);
  b += text(x + 96, cy + 102, 'D-103', { size: 38, weight: 700, fill: T.ink });
  b += text(x + 28, cy + 176, 'Read back', { size: 26, weight: 500, fill: T.muted });
  return svgDoc(W, H, T, 'Inspect, Propose, Approve, Verify',
    'Four steps: inspect finds an empty Mark, propose drafts a change, approve is a human decision, verify reads the value back. Example values are illustrative.', b);
}

// ================================================================= SOCIAL
function social() {
  const T = THEMES.light;
  const W = 1280, H = 640;
  let b = '';
  b += logo(T, 88, 96, 128);
  b += text(88, 316, 'AEC Model Bridge', { size: 70, weight: 700, fill: T.ink, ls: -1, id: 'project-name' });
  b += rect(90, 346, 96, 6, 3, { fill: T.brand });
  b += text(88, 416, 'AI-assisted BIM coordination.', { size: 36, weight: 500, fill: T.muted, id: 'tagline' });
  b += text(88, 560, 'MCP server + native Revit add-in', { size: 26, weight: 500, fill: T.brandText });
  b += model(T, { s: 40, ox: 905, oy: 335, door: 'fixed' }).svg;
  return svgDoc(W, H, T, 'AEC Model Bridge', 'AEC Model Bridge with the Pier logo, an architectural model illustration and the line AI-assisted BIM coordination.', b);
}

// ================================================================= DEMO COVER
function cover() {
  const T = THEMES.light;
  const W = 1600, H = 900;
  let b = '';
  b += logo(T, 80, 80, 80);
  ['Fix missing', 'parameters', 'in Revit.'].forEach((l, i) =>
    (b += text(80, 380 + i * 92, l, { size: 80, weight: 700, fill: i === 2 ? T.brandText : T.ink, ls: -1.5, id: `title-${i + 1}` })));
  b += rect(82, 626, 96, 6, 3, { fill: T.brand });
  b += text(80, 700, 'Inspect. Review. Approve. Verify.', { size: 30, weight: 500, fill: T.muted, id: 'subtitle' });
  const px = 640, py = 110, pw = 880, ph = 550;
  b += rect(px, py, pw, ph, 12, { fill: T.surface, stroke: T.muted, sw: 3, dash: '14 10' });
  b += text(px + pw / 2, py + ph / 2 + 4, 'Screenshot placeholder', { size: 46, weight: 650, fill: T.ink, anchor: 'middle', id: 'placeholder-label' });
  b += text(px + pw / 2, py + ph / 2 + 50, 'Synthetic test model, live Revit', { size: 26, weight: 500, fill: T.muted, anchor: 'middle' });
  return svgDoc(W, H, T, 'Fix missing parameters in Revit.', 'Demo cover with title, subtitle and a large labelled screenshot placeholder.', b);
}

// ---------------------------------------------------------------- output
const outputs = [
  ['readme-hero-light', hero('light'), 1600, 700],
  ['readme-hero-dark', hero('dark'), 1600, 700],
  ['readme-workflow-light', workflow('light'), 1600, 500],
  ['readme-workflow-dark', workflow('dark'), 1600, 500],
  ['social-preview', social(), 1280, 640],
  ['demo-cover', cover(), 1600, 900],
];
for (const [n, svg] of outputs) fs.writeFileSync(path.join(srcDir, `${n}.svg`), svg);
// demo-cover is a placeholder (no real capture yet), so its PNG is not rendered unless asked.
const pngOutputs = outputs.filter(([n]) => n !== 'demo-cover' || process.env.WITH_PLACEHOLDER === '1');

const browser = await chromium.launch();
const page = await browser.newPage({ deviceScaleFactor: 1 });
async function render(svg, w, h, file) {
  await page.setViewportSize({ width: w, height: h });
  await page.setContent(`<!doctype html><body style="margin:0">${svg}</body>`);
  await page.evaluate(() => document.fonts.ready);
  const hasInter = await page.evaluate(() => document.fonts.check('16px Inter'));
  if (!hasInter) throw new Error('The Inter font is not installed; the layout uses fixed offsets, so output would differ. Install Inter and rebuild.');
  await page.screenshot({ path: file, clip: { x: 0, y: 0, width: w, height: h } });
}
for (const [n, svg, w, h] of pngOutputs) await render(svg, w, h, path.join(pngDir, `${n}.png`));
await browser.close();
// Palette-reduce the flat graphics with ImageMagick 7 (`magick`). Never `convert`: on Windows
// that name is System32\convert.exe, a disk tool. If magick is missing the PNGs stay full colour.
let reduced = 0;
for (const [n] of pngOutputs) {
  const f = path.join(pngDir, `${n}.png`);
  try {
    execFileSync('magick', [f, '-colors', '128', '-dither', 'None', '-define', 'png:compression-level=9', '-strip', `PNG8:${f}`], { stdio: 'pipe' });
    reduced++;
  } catch (e) {
    if (e.code === 'ENOENT') { console.warn('ImageMagick (magick) not found: PNGs left full-colour and larger.'); break; }
    console.warn(`Palette reduction failed for ${n}: ${String(e.message).split('\n')[0]}`);
  }
}
console.log(`built ${pngOutputs.map((o) => o[0]).join(', ')} (${reduced}/${pngOutputs.length} palette-reduced)`);

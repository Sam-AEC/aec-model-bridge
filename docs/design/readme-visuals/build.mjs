// Builds the README visual set: editable SVG sources + PNG exports.
//
//   NODE_PATH=$(npm root -g) node docs/design/readme-visuals/build.mjs
//
// Needs Playwright with Chromium and the Inter font installed. Colours come from
// docs/design/tokens.md (keep in sync with docs/design/tokens.md). The Pier logo is
// embedded verbatim from assets/logo-mark.svg and is never redrawn.
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
const extraDir = process.env.EXTRA_DIR || null; // proposal sketches, not shipped
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

const arrowDown = (x, y1, y2, color, w = 3) =>
  line(x, y1, x, y2 - 4, color, w) +
  `<path d="M${x - 9} ${y2 - 14} L${x} ${y2} L${x + 9} ${y2 - 14}" fill="none" stroke="${color}" stroke-width="${w}" stroke-linecap="round" stroke-linejoin="round"/>`;

// Pier logo: the inner markup of assets/logo-mark.svg, untouched.
const logoInner = fs
  .readFileSync(path.join(root, 'assets/logo-mark.svg'), 'utf8')
  .replace(/^[\s\S]*?<svg[^>]*>/, '')
  .replace(/<\/svg>\s*$/, '')
  .trim();
const logo = (T, x, y, size) =>
  `<g id="pier-logo" transform="translate(${x} ${y}) scale(${size / 96})">${logoInner}</g>` +
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
  const d = P(X, 0.5 + 0.275 + 0.0, 0.46);
  const dd = P(X, 0.275, 0.46); // flagged door centre (u = 0.5 span is on L face; see below)
  return { svg: o, door: P(X, 0.5 + 0.275, 0.46), dd, d };
}

// ---------------------------------------------------------------- cards
function card(T, x, y, w, h, { fill, stroke } = {}) {
  return rect(x, y, w, h, 14, { fill: fill ?? T.surface, stroke: stroke ?? T.line, sw: 2 });
}
function chip(T, x, y, label, color, bg, { size = 22, pad = 16, h = 36 } = {}) {
  const w = Math.round(label.length * size * 0.56 + pad * 2);
  return {
    w,
    svg: rect(x, y, w, h, h / 2, { fill: bg, stroke: color, sw: 1.5 }) + text(x + pad, y + h / 2 + size * 0.35, label, { size, weight: 600, fill: color }),
  };
}

// ================================================================= HERO
function hero(name) {
  const T = THEMES[name];
  const W = 1600, H = 700;
  let b = '';
  // sheet border + corner ticks
  b += rect(24, 24, W - 48, H - 48, 0, { stroke: T.line, sw: 1.5 });
  b += logo(T, 88, 84, 64);
  b += text(172, 127, 'AEC Model Bridge', { size: 30, weight: 600, fill: T.ink, id: 'wordmark' });
  b += text(88, 290, 'Find parameter issues.', { size: 62, weight: 700, fill: T.ink, ls: -1, id: 'headline-1' });
  b += text(88, 366, 'Review the fixes.', { size: 62, weight: 700, fill: T.brandText, ls: -1, id: 'headline-2' });
  b += rect(90, 398, 96, 6, 3, { fill: T.brand });
  b += text(88, 468, 'AI-assisted BIM coordination', { size: 32, weight: 500, fill: T.muted, id: 'support-1' });
  b += text(88, 512, 'with human approval.', { size: 32, weight: 500, fill: T.muted, id: 'support-2' });
  b += text(88, 640, 'Illustration with example values. Not a Revit screenshot.', { size: 22, weight: 500, fill: T.muted, id: 'footnote' });

  const m = model(T, { s: 30, ox: 960, oy: 345, door: 'issue' });
  b += m.svg;

  // issue card
  const cx = 1205, cw = 340;
  b += card(T, cx, 160, cw, 170);
  b += `<circle cx="${cx + 34}" cy="204" r="9" fill="${T.warn}"/>`;
  b += text(cx + 56, 212, 'Issue found', { size: 26, weight: 600, fill: T.warn });
  b += text(cx + 28, 262, 'Door · Mark', { size: 32, weight: 650, fill: T.ink });
  b += text(cx + 28, 306, 'Value', { size: 26, weight: 500, fill: T.muted });
  b += rect(cx + 118, 282, 190, 38, 6, { fill: T.warnBg, stroke: T.warn, sw: 2, dash: '6 5' });
  b += text(cx + 213, 310, 'empty', { size: 26, weight: 600, fill: T.warn, anchor: 'middle' });
  // leader from model door to issue card
  const [dx, dy] = m.door;
  b += `<polyline points="${f1(dx)},${f1(dy)} 1186,${f1(dy)} 1186,245 ${cx},245" fill="none" stroke="${T.warn}" stroke-width="2.5" stroke-linejoin="round"/>`;
  b += `<circle cx="${f1(dx)}" cy="${f1(dy)}" r="17" fill="none" stroke="${T.warn}" stroke-width="2.5"/>`;
  b += `<circle cx="${f1(dx)}" cy="${f1(dy)}" r="5" fill="${T.warn}"/>`;

  // arrow + fix card
  b += arrowDown(cx + cw / 2, 334, 388, T.muted);
  b += card(T, cx, 392, cw, 222, { stroke: T.brand });
  b += check(cx + 36, 438, 14, T.ok, T.surface);
  b += text(cx + 60, 447, 'Reviewed fix', { size: 26, weight: 600, fill: T.ok });
  b += line(cx + 28, 468, cx + cw - 28, 468, T.line, 1.5);
  b += text(cx + 28, 504, 'Door \u00B7 Mark', { size: 24, weight: 500, fill: T.muted });
  b += text(cx + 28, 552, 'empty', { size: 28, weight: 500, fill: T.muted });
  b += arrow(cx + 128, 542, cx + 170, T.muted, 2.5);
  b += text(cx + 184, 554, 'D-101', { size: 36, weight: 700, fill: T.brandText });
  b += text(cx + 28, 596, 'Approved by reviewer', { size: 24, weight: 600, fill: T.ok });

  return svgDoc(W, H, T, 'Find parameter issues. Review the fixes.',
    'A BIM model with a door flagged for a missing Mark parameter, an issue card, and a reviewed correction card. Example values.', b);
}

// ================================================================= WORKFLOW
function workflow(name) {
  const T = THEMES[name];
  const W = 1600, H = 500;
  let b = '';
  const cw = 312, gap = 64, x0 = 80, cy = 118, ch = 280;
  const steps = ['Inspect', 'Propose', 'Approve', 'Verify'];
  const caps = ['Find empty values', 'Draft a change table', 'A person decides', 'Re-read and compare'];
  steps.forEach((s, i) => {
    const x = x0 + i * (cw + gap);
    b += `<circle cx="${x + 20}" cy="64" r="20" fill="${T.brand}"/>`;
    b += text(x + 20, 72, String(i + 1), { size: 24, weight: 700, fill: T.btnText, anchor: 'middle' });
    b += text(x + 52, 77, s, { size: 38, weight: 700, fill: T.ink });
    b += card(T, x, cy, cw, ch, i === 2 ? { stroke: T.brand } : {});
    b += text(x, 440, caps[i], { size: 28, weight: 500, fill: T.muted });
    if (i < 3) b += arrow(x + cw + 12, cy + ch / 2, x + cw + gap - 12, T.muted, 3);
  });
  b += text(80, 478, 'Example values are illustrative.', { size: 22, weight: 500, fill: T.muted, id: 'footnote' });

  // 1 Inspect
  let x = x0;
  b += text(x + 24, cy + 46, 'Door · Mark', { size: 24, weight: 600, fill: T.muted });
  const rows1 = [['Door 0415', 'D-101', 0], ['Door 0416', 'D-102', 0], ['Door 0417', 'empty', 1], ['Door 0418', 'empty', 1]];
  rows1.forEach(([id, v, miss], r) => {
    const y = cy + 64 + r * 50;
    if (miss) b += rect(x + 14, y, cw - 28, 42, 6, { fill: T.warnBg, stroke: T.warn, sw: 1.5, dash: '5 4' });
    b += text(x + 26, y + 29, id, { size: 24, weight: 500, fill: T.ink });
    b += text(x + cw - 26, y + 29, v, { size: 24, weight: miss ? 600 : 500, fill: miss ? T.warn : T.muted, anchor: 'end' });
  });

  // 2 Propose
  x = x0 + (cw + gap);
  b += text(x + 24, cy + 46, 'Proposed changes', { size: 24, weight: 600, fill: T.muted });
  b += rect(x + 14, cy + 62, cw - 28, 40, 6, { fill: T.raised });
  b += text(x + 26, cy + 89, 'Door', { size: 22, weight: 600, fill: T.muted });
  b += text(x + 112, cy + 89, 'Before', { size: 22, weight: 600, fill: T.muted });
  b += text(x + cw - 26, cy + 89, 'After', { size: 22, weight: 600, fill: T.muted, anchor: 'end' });
  [['0417', 'D-103'], ['0418', 'D-104']].forEach(([id, v], r) => {
    const y = cy + 112 + r * 56;
    b += text(x + 26, y + 33, id, { size: 26, weight: 500, fill: T.ink });
    b += text(x + 112, y + 33, 'empty', { size: 24, weight: 500, fill: T.warn });
    b += text(x + cw - 26, y + 34, v, { size: 28, weight: 700, fill: T.brandText, anchor: 'end' });
    b += line(x + 14, y + 52, x + cw - 14, y + 52, T.line, 1.5);
  });
  b += chip(T, x + 24, cy + ch - 56, 'Draft · not applied', T.muted, T.raised).svg;

  // 3 Approve
  x = x0 + 2 * (cw + gap);
  b += `<circle cx="${x + 46}" cy="${cy + 52}" r="14" fill="none" stroke="${T.ink}" stroke-width="3"/>`;
  b += `<path d="M${x + 20} ${cy + 96} C${x + 20} ${cy + 70} ${x + 72} ${cy + 70} ${x + 72} ${cy + 96}" fill="none" stroke="${T.ink}" stroke-width="3" stroke-linecap="round"/>`;
  b += text(x + 92, cy + 60, 'Reviewer', { size: 26, weight: 600, fill: T.ink });
  b += text(x + 24, cy + 138, '2 changes to review', { size: 28, weight: 600, fill: T.ink });
  b += chip(T, x + 24, cy + 158, 'Awaiting decision', T.pend, T.pendBg).svg;
  b += rect(x + 24, cy + ch - 72, 150, 52, 10, { fill: T.brand });
  b += text(x + 99, cy + ch - 37, 'Approve', { size: 26, weight: 700, fill: T.btnText, anchor: 'middle' });
  b += rect(x + 188, cy + ch - 72, 100, 52, 10, { stroke: T.muted, sw: 2 });
  b += text(x + 238, cy + ch - 37, 'Reject', { size: 26, weight: 600, fill: T.ink, anchor: 'middle' });

  // 4 Verify
  x = x0 + 3 * (cw + gap);
  b += text(x + 24, cy + 46, 'Read back values', { size: 24, weight: 600, fill: T.muted });
  [['0417', 'D-103'], ['0418', 'D-104']].forEach(([id, v], r) => {
    const y = cy + 72 + r * 56;
    b += text(x + 26, y + 33, id, { size: 26, weight: 500, fill: T.ink });
    b += text(x + 118, y + 34, v, { size: 28, weight: 700, fill: T.ink });
    b += check(x + cw - 42, y + 24, 15, T.ok, T.surface);
    b += line(x + 14, y + 52, x + cw - 14, y + 52, T.line, 1.5);
  });
  b += chip(T, x + 24, cy + ch - 56, '2 of 2 match', T.ok, T.okBg).svg;

  return svgDoc(W, H, T, 'Inspect, Propose, Approve, Verify',
    'Four steps: inspect finds empty Mark values, propose drafts a change table, approve is a human decision, verify reads the values back. Example values are illustrative.', b);
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
  b += rect(24, 24, W - 48, H - 48, 0, { stroke: T.line, sw: 1.5 });
  b += logo(T, 80, 72, 56);
  b += text(150, 110, 'AEC Model Bridge', { size: 28, weight: 600, fill: T.ink });
  ['Fix missing', 'parameters', 'in Revit.'].forEach((l, i) =>
    (b += text(80, 322 + i * 86, l, { size: 76, weight: 700, fill: i === 2 ? T.brandText : T.ink, ls: -1.5, id: `title-${i + 1}` })));
  b += rect(82, 548, 96, 6, 3, { fill: T.brand });
  b += text(80, 620, 'Inspect. Review. Approve. Verify.', { size: 30, weight: 500, fill: T.muted, id: 'subtitle' });

  // screenshot placeholder, 16:10
  const px = 640, py = 150, pw = 880, ph = 550;
  b += rect(px, py, pw, ph, 12, { fill: T.surface, stroke: T.muted, sw: 3, dash: '14 10' });
  b += line(px + 12, py + 12, px + pw - 12, py + ph - 12, T.line, 1.5);
  b += line(px + pw - 12, py + 12, px + 12, py + ph - 12, T.line, 1.5);
  b += rect(px + 190, py + ph / 2 - 62, pw - 380, 124, 12, { fill: T.surface });
  b += text(px + pw / 2, py + ph / 2 - 4, 'Screenshot placeholder', { size: 44, weight: 650, fill: T.ink, anchor: 'middle', id: 'placeholder-label' });
  b += text(px + pw / 2, py + ph / 2 + 38, '16:10 · synthetic test model', { size: 26, weight: 500, fill: T.muted, anchor: 'middle' });
  b += text(px, py + ph + 48, 'Replace with a capture from live Revit using the repo’s synthetic test model.', { size: 24, weight: 500, fill: T.muted });
  b += text(px, py + ph + 82, 'Mock mode returns canned responses and is not a live Revit demo.', { size: 24, weight: 500, fill: T.muted });
  return svgDoc(W, H, T, 'Fix missing parameters in Revit.', 'Demo cover with title, subtitle and a large labelled screenshot placeholder.', b);
}

// ================================================================= PROPOSAL SKETCHES (not shipped)
function sketch(which) {
  const T = THEMES.light;
  const W = 800, H = 350;
  let b = rect(0, 0, W, H, 0, { fill: T.bg }) + rect(8, 8, W - 16, H - 16, 0, { stroke: T.line, sw: 1.5 });
  const blk = (x, y, w, h, label, o = {}) =>
    rect(x, y, w, h, 8, { fill: o.fill ?? T.surface, stroke: o.stroke ?? T.line, sw: 2, dash: o.dash }) +
    (label ? text(x + w / 2, y + h / 2 + 7, label, { size: 20, weight: 600, fill: o.color ?? T.muted, anchor: 'middle' }) : '');
  if (which === 'A') {
    b += text(40, 90, 'Find parameter issues.', { size: 30, weight: 700, fill: T.ink });
    b += text(40, 130, 'Review the fixes.', { size: 30, weight: 700, fill: T.brandText });
    b += rect(42, 150, 48, 4, 2, { fill: T.brand });
    b += text(40, 190, 'AI-assisted BIM coordination', { size: 16, weight: 500, fill: T.muted });
    b += text(40, 212, 'with human approval.', { size: 16, weight: 500, fill: T.muted });
    b += blk(380, 70, 190, 220, 'Model', {});
    b += blk(610, 56, 160, 80, 'Issue', { stroke: T.warn, color: T.warn, dash: '6 4' });
    b += blk(610, 190, 160, 100, 'Reviewed fix', { stroke: T.brand, color: T.brandText });
    b += `<polyline points="540,150 590,150 590,96 610,96" fill="none" stroke="${T.warn}" stroke-width="2.5"/>`;
    b += arrowDown(690, 138, 188, T.muted, 2.5);
  } else {
    b += text(40, 64, 'Find parameter issues. Review the fixes.', { size: 28, weight: 700, fill: T.ink });
    b += text(40, 92, 'AI-assisted BIM coordination with human approval.', { size: 16, weight: 500, fill: T.muted });
    b += blk(40, 130, 220, 180, 'Model');
    b += blk(290, 130, 220, 180, 'Issue', { stroke: T.warn, color: T.warn, dash: '6 4' });
    b += blk(540, 130, 220, 180, 'Reviewed fix', { stroke: T.brand, color: T.brandText });
    b += arrow(262, 220, 288, T.muted, 2.5) + arrow(512, 220, 538, T.muted, 2.5);
  }
  return svgDoc(W, H, T, 'Composition ' + which, 'Wireframe', b);
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

const browser = await chromium.launch();
const page = await browser.newPage({ deviceScaleFactor: 1 });
async function render(svg, w, h, file) {
  await page.setViewportSize({ width: w, height: h });
  await page.setContent(`<!doctype html><body style="margin:0">${svg}</body>`);
  await page.evaluate(() => document.fonts.ready);
  await page.screenshot({ path: file, clip: { x: 0, y: 0, width: w, height: h } });
}
for (const [n, svg, w, h] of outputs) await render(svg, w, h, path.join(pngDir, `${n}.png`));
if (extraDir) {
  fs.mkdirSync(extraDir, { recursive: true });
  for (const k of ['A', 'B']) await render(sketch(k), 800, 350, path.join(extraDir, `composition-${k}.png`));
}
await browser.close();
// Palette-reduce the flat graphics (needs ImageMagick `convert`; skipped if absent).
for (const [n] of outputs) {
  const f = path.join(pngDir, `${n}.png`);
  try { execFileSync('convert', [f, '-colors', '128', '-dither', 'None', '-define', 'png:compression-level=9', '-strip', `PNG8:${f}`]); } catch { /* keep the full-colour PNG */ }
}
console.log('built', outputs.map((o) => o[0]).join(', '));

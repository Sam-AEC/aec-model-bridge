"""Deterministic ribbon icon generator for the AEC Bridge Revit tab (CPython 3 + Pillow, offline).

Style 'cut slate' (shared with the Recipe Editor pyRevit tab so both tabs read as one product):
solid silhouettes on one 32 px construction grid, built from three materials only:
  base - the silhouette (slate on the light ribbon, near-white on the dark ribbon),
  main - ONE Autodesk-blue block (#0696D7) for the subject,
  hi   - at most one small Dutch-orange (#FF6C00) piece that marks the action.
Detail is CUT (knocked out to transparent), never drawn as thin lines; overlapping parts are separated by a
1 px knockout gap. Depth = top-light gradient + 1 px darker bottom edge + 1 px inner top highlight.
Rendered at 8x supersampling, premultiplied Lanczos downscale. 16 px icons use the same glyphs with
2-grid-unit (1 output pixel) gaps and cuts, so nothing falls below one pixel.

    python scripts/make_ribbon_icons.py [--preview artifacts/ribbon-preview.png] [--refs <folder with 3.png>]

Writes packages/revit-bridge-addin/Resources/RibbonIcons/<name>_<16|32>_<light|dark>.png. The add-in embeds
them (RevitBridge.csproj) and IconGenerator picks the variant for Revit's current theme (docs/RIBBON_ICONS.md).
"""
import itertools
import math
import os
import re
import sys

from PIL import Image, ImageChops, ImageDraw, ImageFont

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(ROOT, 'packages', 'revit-bridge-addin', 'Resources', 'RibbonIcons')
CERBERUS = os.path.join(ROOT, 'assets', 'cerberus', 'mark-16.svg')
SS = 8  # supersampling factor

# (gradient top, gradient bottom, bottom edge, inner top highlight RGBA or None) -- identical to the
# Recipe Editor generator (dynamoscript14 tools/pyrevit_spike/make_icons.py, PALETTE 'autodesk_dutch').
MATERIALS = {
    'light': {
        'base': ((0x58, 0x64, 0x77), (0x3B, 0x44, 0x53), (0x26, 0x2D, 0x37), (255, 255, 255, 46)),
        'tone': ((0x9A, 0xA5, 0xB4), (0x80, 0x8C, 0x9C), (0x63, 0x6E, 0x7E), (255, 255, 255, 60)),
        'main': ((0x2C, 0xAE, 0xEA), (0x06, 0x8F, 0xD0), (0x04, 0x66, 0x98), (255, 255, 255, 90)),
        'hi': ((0xFF, 0x8E, 0x33), (0xFF, 0x6C, 0x00), (0xC2, 0x52, 0x00), (255, 255, 255, 80)),
    },
    'dark': {
        'base': ((0xFA, 0xFB, 0xFC), (0xDA, 0xE0, 0xE8), (0xA6, 0xB0, 0xBE), None),
        'tone': ((0xB4, 0xBE, 0xCB), (0x97, 0xA3, 0xB2), (0x74, 0x80, 0x90), (255, 255, 255, 60)),
        'main': ((0x33, 0xB4, 0xEE), (0x06, 0x96, 0xD7), (0x04, 0x6E, 0xA3), (255, 255, 255, 90)),
        'hi': ((0xFF, 0x92, 0x3A), (0xFF, 0x6C, 0x00), (0xC2, 0x52, 0x00), (255, 255, 255, 80)),
    },
}

# (file name stem used by App.cs / IconGenerator, ribbon label)
BUTTONS = [
    ('connect', 'Connect'), ('disconnect', 'Disconnect'), ('status', 'Status'), ('panel', 'Open Panel'),
    ('healthcheck', 'Health Check'), ('pending', 'Pending Actions'), ('reports', 'Reports'),
    ('settings', 'Config'), ('help', 'Help'), ('about', 'About'),
]
SIZES = (16, 32)


# ---- geometry helpers (32 grid units) ----------------------------------------------------------------------------

def _arc(c, rad, a0, a1, step=4):
    n = max(2, int(abs(a1 - a0) / step) + 1)
    return [(c[0] + rad * math.cos(math.radians(a0 + (a1 - a0) * i / float(n))),
             c[1] + rad * math.sin(math.radians(a0 + (a1 - a0) * i / float(n)))) for i in range(n + 1)]


def _round_corners(pts, rad, seg=8):
    if rad <= 0:
        return list(pts)
    out = []
    n = len(pts)
    for i in range(n):
        p0, p1, p2 = pts[i - 1], pts[i], pts[(i + 1) % n]
        v1 = (p0[0] - p1[0], p0[1] - p1[1])
        v2 = (p2[0] - p1[0], p2[1] - p1[1])
        l1, l2 = math.hypot(*v1), math.hypot(*v2)
        r = min(rad, l1 / 2.0, l2 / 2.0)
        a = (p1[0] + v1[0] / l1 * r, p1[1] + v1[1] / l1 * r)
        b = (p1[0] + v2[0] / l2 * r, p1[1] + v2[1] / l2 * r)
        for s in range(seg + 1):
            t = s / float(seg)
            out.append(((1 - t) ** 2 * a[0] + 2 * t * (1 - t) * p1[0] + t * t * b[0],
                        (1 - t) ** 2 * a[1] + 2 * t * (1 - t) * p1[1] + t * t * b[1]))
    return out


def _rect(x0, y0, x1, y1):
    return [(x0, y0), (x1, y0), (x1, y1), (x0, y1)]


def _quad(p0, p1, p2, seg=10):
    return [((1 - t) ** 2 * p0[0] + 2 * t * (1 - t) * p1[0] + t * t * p2[0],
             (1 - t) ** 2 * p0[1] + 2 * t * (1 - t) * p1[1] + t * t * p2[1])
            for t in [i / float(seg) for i in range(seg + 1)]]


# ---- renderer (same technique as the Recipe Editor set) ------------------------------------------------------------

class Icon:
    """Mask-based painter. Shapes are masks; paint() fills a mask with a material, cut() knocks it out."""

    def __init__(self, size, dark):
        self.size = size
        self.k = SS * size / 32.0
        self.px = SS
        self.u = 32.0 / size          # grid units per output pixel: 1 at 32 px, 2 at 16 px
        self.small = size < 24
        self.mat = MATERIALS['dark' if dark else 'light']
        self.W = size * SS
        self.img = Image.new('RGBA', (self.W, self.W), (0, 0, 0, 0))

    def _xy(self, pts):
        return [(x * self.k - 0.5, y * self.k - 0.5) for x, y in pts]

    def _blank(self):
        return Image.new('L', (self.W, self.W), 0)

    def _thick(self, d, px, width_grid, closed):
        w = width_grid * self.k
        seq = px + [px[0]] if closed else px
        for a, b in itertools.pairwise(seq):
            d.line([a, b], fill=255, width=max(1, round(w)))
        r = w / 2.0
        for x, y in seq:
            d.ellipse([x - r, y - r, x + r, y + r], fill=255)

    def poly(self, pts, r=0.0, grow=0.0):
        m = self._blank()
        d = ImageDraw.Draw(m)
        px = self._xy(_round_corners(pts, r))
        d.polygon(px, fill=255)
        if grow > 0:
            self._thick(d, px, 2 * grow, True)
        return m

    def rect(self, x0, y0, x1, y1, r=0.0, grow=0.0):
        return self.poly(_rect(x0, y0, x1, y1), r, grow)

    def stroke(self, pts, w, grow=0.0, closed=False):
        m = self._blank()
        self._thick(ImageDraw.Draw(m), self._xy(pts), w + 2 * grow, closed)
        return m

    def disc(self, c, rad, grow=0.0):
        m = self._blank()
        x, y = self._xy([c])[0]
        r = (rad + grow) * self.k
        ImageDraw.Draw(m).ellipse([x - r, y - r, x + r, y + r], fill=255)
        return m

    @staticmethod
    def union(*ms):
        out = ms[0]
        for m in ms[1:]:
            out = ImageChops.lighter(out, m)
        return out

    @staticmethod
    def inter(a, b):
        return ImageChops.multiply(a, b)

    @staticmethod
    def minus(a, b):
        return ImageChops.subtract(a, b)

    def _shift(self, m, dy):
        out = self._blank()
        out.paste(m, (0, dy))
        return out

    def cut(self, mask):
        r, g, b, a = self.img.split()
        self.img = Image.merge('RGBA', (r, g, b, ImageChops.subtract(a, mask)))

    def paint(self, mask, material, depth=True, gap_mask=None):
        if gap_mask is not None:
            self.cut(gap_mask)
        top, bottom, edge, hl = self.mat[material]
        box = mask.getbbox()
        if not box:
            return
        y0, y1 = box[1], box[3]
        ramp = Image.linear_gradient('L').resize((self.W, max(1, y1 - y0)))
        grad = Image.new('L', (self.W, self.W), 0)
        grad.paste(255, (0, y1, self.W, self.W))
        grad.paste(ramp, (0, y0))
        layer = Image.composite(Image.new('RGBA', self.img.size, bottom + (255,)),
                                Image.new('RGBA', self.img.size, top + (255,)), grad)
        if depth:
            bottom_band = self.minus(mask, self._shift(mask, -self.px))
            layer.paste(Image.new('RGBA', self.img.size, edge + (255,)), (0, 0), bottom_band)
            if hl is not None:
                top_band = self.minus(mask, self._shift(mask, self.px))
                hl_layer = Image.new('RGBA', self.img.size, hl[:3] + (0,))
                hl_layer.putalpha(top_band.point(lambda v: v * hl[3] // 255))
                layer.alpha_composite(Image.composite(hl_layer, Image.new('RGBA', self.img.size), mask))
        layer.putalpha(ImageChops.multiply(layer.getchannel('A'), mask))
        self.img.alpha_composite(layer)

    def result(self):
        big = self.img.convert('RGBa')
        return big.resize((self.size, self.size), Image.LANCZOS).convert('RGBA')


# ---- glyphs: 32 grid, live area 2..30, whole-pixel edges, 1 px knockout gaps --------------------------------------

def _plug(ic, x):
    """Slate cable and plug body whose right face sits at x; returns the prong mask (right of x)."""
    ic.paint(ic.stroke([(2, 16), (x - 8, 16)], 4), 'base', depth=False)          # cable
    ic.paint(ic.rect(x - 9, 7, x, 25, 2.5), 'base')                              # body
    return ic.union(ic.rect(x, 10, x + 5, 13, 0.6), ic.rect(x, 19, x + 5, 22, 0.6))


def _socket(ic, x0):
    sock = ic.rect(x0, 5, 30, 27, 3)
    ic.paint(sock, 'main', gap_mask=ic.rect(x0, 5, 30, 27, 3, grow=ic.u))
    return sock


def d_connect(ic):
    """Connect: slate plug pushed home into the blue socket, orange 'live' lamp on the socket."""
    _plug(ic, 16)
    _socket(ic, 16 + ic.u)
    ic.cut(ic.disc((24.5, 16), 2.6 + ic.u))
    ic.paint(ic.disc((24.5, 16), 2.6), "hi", depth=False)


def d_disconnect(ic):
    """Disconnect: plug pulled out of the blue socket (empty holes), a small orange break mark in the gap."""
    prongs = _plug(ic, 12)
    ic.paint(prongs, 'base', depth=False)
    _socket(ic, 21)
    ic.cut(ic.union(ic.rect(21, 10, 24, 13), ic.rect(21, 19, 24, 22)))          # empty socket holes
    w = 2.4 if not ic.small else 2.8
    ic.paint(ic.stroke([(20.5, 3), (18, 8), (21, 11.5), (18.5, 16)], w), 'hi', depth=False)


def d_status(ic):
    """Status: slate monitor, blue screen with the pulse line cut out, orange live dot."""
    ic.paint(ic.rect(2, 3, 30, 23, 3), 'base')
    ic.paint(ic.rect(12, 26, 20, 29, 1), 'base')
    ic.paint(ic.rect(15, 22, 17, 26), 'base', depth=False)
    scr = ic.rect(5, 6, 27, 20, 1.5)
    ic.paint(scr, 'main', gap_mask=ic.rect(5, 6, 27, 20, 1.5, grow=ic.u))
    w = 2.2 if not ic.small else 2.6
    ic.cut(ic.inter(ic.stroke([(5, 13.5), (10, 13.5), (12.5, 9), (15.5, 18), (18, 13.5), (21, 13.5)], w), scr))
    ic.paint(ic.disc((23.5, 13.5), 2.5), 'hi', depth=False)


def d_panel(ic):
    """Open Panel: slate window, blue docked side panel on the left, orange title-bar button."""
    win = ic.rect(2, 3, 30, 29, 3)
    ic.paint(win, 'base')
    side = ic.inter(ic.rect(2, 3, 13, 29, 3), win)
    ic.paint(side, 'main', gap_mask=ic.rect(13, 3, 13 + ic.u, 29))
    ic.cut(ic.rect(13 + ic.u, 9, 30, 9 + ic.u))                                   # title bar line
    for y, x1 in ((14, 26), (19, 23), (24, 25)):
        ic.cut(ic.rect(17, y, x1, y + (1.5 if not ic.small else 2), 0.5))
    ic.paint(ic.rect(23, 4.5, 27.5, 7.5, 1), 'hi', depth=False)


def _shield(ic):
    pts = [(16, 2), (27.5, 5.5), (27.5, 15)] + _quad((27.5, 15), (27.5, 24.5), (16, 30))[1:] + \
        _quad((16, 30), (4.5, 24.5), (4.5, 15))[1:] + [(4.5, 5.5)]
    return pts


def d_healthcheck(ic):
    """Health Check: shield, slate rim around a blue model core, check cut through, orange pulse dot."""
    pts = _shield(ic)
    ic.paint(ic.poly(pts, 1.6), 'base')
    inner = [(16, 6.5), (24, 9), (24, 15.5)] + _quad((24, 15.5), (24, 22), (16, 26))[1:] + \
        _quad((16, 26), (8, 22), (8, 15.5))[1:] + [(8, 9)]
    ic.paint(ic.poly(inner, 1.2), 'main', gap_mask=ic.poly(inner, 1.2, grow=ic.u))
    ic.cut(ic.stroke([(11, 16), (14.5, 19.5), (21, 12.5)], 3.2 if not ic.small else 3.6))


def d_pending(ic):
    """Pending Actions: slate clipboard list waiting, blue approval badge with a check, orange clip."""
    board = ic.rect(3, 4, 22, 30, 2.5)
    ic.paint(board, 'base')
    ic.cut(ic.rect(8, 2, 17, 7, 1.2, grow=ic.u))
    ic.paint(ic.rect(8, 2, 17, 7, 1.2), 'hi', depth=False)
    for y in (11, 16, 21):
        ic.cut(ic.rect(7, y, 18, y + (2 if not ic.small else 2.5), 0.6))
    badge = ic.disc((23, 23), 7)
    ic.paint(badge, 'main', gap_mask=ic.disc((23, 23), 7, grow=ic.u))
    ic.cut(ic.stroke([(19.5, 23.2), (22, 25.7), (26.5, 20.5)], 2.4 if not ic.small else 2.8))


def d_reports(ic):
    """Reports: slate page with a folded corner, blue bar chart, the latest bar in orange."""
    body = [(5, 2), (19, 2), (27, 10), (27, 30), (5, 30)]
    ic.paint(ic.poly(body, 1.5), 'base')
    fold = [(19, 2), (19, 10), (27, 10)]
    ic.paint(ic.poly(fold, 0.8), 'tone', gap_mask=ic.poly(fold, 0.8, grow=ic.u))
    ic.cut(ic.rect(9, 6.5, 16, 6.5 + (1.5 if not ic.small else 2)))
    bars = ic.union(ic.rect(9, 19, 13, 26, 0.6), ic.rect(14, 15, 18, 26, 0.6))
    ic.cut(ic.union(ic.rect(9, 19, 13, 26, 0.6, grow=ic.u), ic.rect(14, 15, 18, 26, 0.6, grow=ic.u),
                    ic.rect(19, 12, 23, 26, 0.6, grow=ic.u)))
    ic.paint(bars, 'main')
    ic.paint(ic.rect(19, 12, 23, 26, 0.6), 'hi', depth=False)


def d_settings(ic):
    """Config: three sliders; the active one has a blue knob and blue fill (as in the Recipe Editor set)."""
    rows = ((6, 20), (16, 9), (26, 16))
    for i, (y, kx) in enumerate(rows):
        knob = ic.rect(kx, y - 4, kx + 6, y + 4, 1.6)
        track = ic.rect(3, y - 1, 29, y + 1, 1)
        ic.paint(ic.minus(track, ic.rect(kx - ic.u, y - 5, kx + 6 + ic.u, y + 5)),
                 'tone' if i != 1 else 'base', depth=False)
        if i == 1:
            ic.paint(ic.inter(track, ic.rect(0, 0, kx - ic.u, 32)), 'main', depth=False)
            ic.paint(knob, 'main')
        else:
            ic.paint(knob, 'base')


def d_help(ic):
    """Help: two speech bubbles (slate behind, blue in front) with a question mark cut out."""
    back = _round_corners(_rect(12, 3, 29, 17), 3.5)
    ic.paint(ic.union(ic.poly(back), ic.poly([(21, 16), (26.5, 21.5), (26.5, 16)], 0.5)), 'base')
    front = ic.union(ic.rect(3, 9, 23, 26, 4), ic.poly([(6, 25), (6, 30), (12.5, 25)], 0.4))
    gap = ic.union(ic.rect(3, 9, 23, 26, 4, grow=ic.u), ic.poly([(6, 25), (6, 30), (12.5, 25)], 0.4, grow=ic.u))
    ic.paint(front, 'main', gap_mask=gap)
    q = _arc((13, 14.6), 3.1, 195, 395) + [(13, 18.4), (13, 19.6)]
    ic.cut(ic.union(ic.stroke(q, 2.5 if not ic.small else 2.9), ic.disc((13, 22.9), 1.5 if not ic.small else 1.7)))


def _svg_polys(path):
    """M/L/Z polygons from an SVG file (the cerberus marks only use these commands), in 512 units."""
    with open(path, 'r') as fh:
        svg = fh.read()
    polys = []
    for d in re.findall(r' d="([^"]*)"', svg):
        for sub in re.split(r'[Zz]', d):
            nums = [float(v) for v in re.findall(r'-?\d+(?:\.\d+)?', sub)]
            if len(nums) >= 6:
                polys.append(list(zip(nums[0::2], nums[1::2])))
    return polys


def d_about(ic):
    """About: the cerberus mark in cut slate: slate disc, blue three-headed silhouette, orange eyes."""
    polys = _svg_polys(CERBERUS)       # [0] heads silhouette, [1] centre head, [2], [3] eyes
    k, o = 27.0 / 512, 16 - 256 * 27.0 / 512
    sc = lambda pts: [(o + x * k, o + 0.6 + y * k) for x, y in pts]
    ic.paint(ic.disc((16, 16), 14), 'base')
    heads = ic.union(*[ic.poly(sc(p)) for p in polys[:2]])
    ic.paint(heads, 'main', gap_mask=ic.union(*[ic.poly(sc(p), grow=ic.u) for p in polys[:2]]))
    eyes = ic.union(*[ic.poly(sc(p), grow=0.3 if not ic.small else 0.7) for p in polys[2:4]])
    ic.paint(eyes, 'hi', depth=False)


GLYPHS = {'connect': d_connect, 'disconnect': d_disconnect, 'status': d_status, 'panel': d_panel,
          'healthcheck': d_healthcheck, 'pending': d_pending, 'reports': d_reports, 'settings': d_settings,
          'help': d_help, 'about': d_about}


def render(name, dark, size):
    ic = Icon(size, dark)
    GLYPHS[name](ic)
    return ic.result()


def save(img, path):
    img.save(path, format='PNG', optimize=False)   # no metadata, deterministic


# ---- preview: mock AEC Bridge ribbon (Revit layout: large buttons + 16 px stacks), dark and light, 100/200 % ------

THEMES = {
    True: {'tabs': (0x2B, 0x33, 0x40), 'body': (0x3B, 0x44, 0x53), 'title': (0x2F, 0x38, 0x46),
           'text': (0xE6, 0xE9, 0xEE), 'sep': (0x52, 0x5C, 0x6C), 'active': (0x3B, 0x44, 0x53)},
    False: {'tabs': (0xE6, 0xE9, 0xED), 'body': (0xF7, 0xF8, 0xFA), 'title': (0xE3, 0xE6, 0xEA),
            'text': (0x22, 0x26, 0x2C), 'sep': (0xC8, 0xCD, 0xD4), 'active': (0xF7, 0xF8, 0xFA)},
}
# Layout copied from App.cs: Connection = Connect, Disconnect | Status (large); Workflows = Open Panel (large)
# + stack(Health Check, Pending Actions, Reports); Tools = stack(Config, Help, About).
LAYOUT = [('Connection', [('L', ['connect']), ('L', ['disconnect']), ('L', ['status'])]),
          ('Workflows', [('L', ['panel']), ('S', ['healthcheck', 'pending', 'reports'])]),
          ('Tools', [('S', ['settings', 'help', 'about'])])]
LABEL = dict(BUTTONS)


def _font(px, bold=False):
    for name in (('segoeuib.ttf' if bold else 'segoeui.ttf'), 'arial.ttf'):
        try:
            return ImageFont.truetype(os.path.join(os.environ.get('WINDIR', 'C:/Windows'), 'Fonts', name), px)
        except OSError:
            continue
    return ImageFont.load_default()


def _ribbon(dark, s):
    th = THEMES[dark]
    f = _font(12 * s)
    cols = []
    for title, groups in LAYOUT:
        ws = []
        for kind, names in groups:
            if kind == 'L':
                ws.append(max(32 * s, int(f.getlength(LABEL[names[0]]))) + 10 * s)
            else:
                ws.append(max(int(f.getlength(LABEL[n])) for n in names) + 30 * s)
        cols.append(ws)
    total = sum(sum(w) + 12 * s for w in cols) + 8 * s
    h_tab, h_body, h_title = 22 * s, 70 * s, 18 * s
    img = Image.new('RGBA', (total, h_tab + h_body + h_title), th['body'] + (255,))
    d = ImageDraw.Draw(img)
    d.rectangle([0, 0, total, h_tab], fill=th['tabs'] + (255,))
    x = 6 * s
    for tab in ('Manage', 'Add-Ins', 'AEC Bridge', 'RecipeEditor'):
        tw = int(f.getlength(tab)) + 14 * s
        if tab == 'AEC Bridge':
            d.rectangle([x, 2 * s, x + tw, h_tab], fill=th['active'] + (255,))
        d.text((x + 7 * s, 3 * s), tab, fill=th['text'] + (255,), font=f)
        x += tw
    x = 4 * s
    for (title, groups), ws in zip(LAYOUT, cols):
        x0 = x
        for (kind, names), w in zip(groups, ws):
            if kind == 'L':
                img.alpha_composite(render(names[0], dark, 32 * s), (x + (w - 32 * s) // 2, h_tab + 6 * s))
                tw = int(f.getlength(LABEL[names[0]]))
                d.text((x + (w - tw) // 2, h_tab + 42 * s), LABEL[names[0]], fill=th['text'] + (255,), font=f)
            else:
                for i, n in enumerate(names):
                    y = h_tab + 6 * s + i * 22 * s
                    img.alpha_composite(render(n, dark, 16 * s), (x + 4 * s, y))
                    d.text((x + 24 * s, y - 1 * s), LABEL[n], fill=th['text'] + (255,), font=f)
            x += w
        x += 12 * s
        d.rectangle([x0, h_tab + h_body, x - 4 * s, h_tab + h_body + h_title], fill=th['title'] + (255,))
        tw = int(f.getlength(title))
        d.text(((x0 + x - 4 * s - tw) // 2, h_tab + h_body + 1 * s), title, fill=th['text'] + (255,), font=f)
        d.line([x - 3 * s, h_tab + 4 * s, x - 3 * s, h_tab + h_body + h_title - 4 * s], fill=th['sep'] + (255,),
               width=s)
    return img


def _ref(path, box, scale):
    if not path or not os.path.isfile(path):
        return None
    crop = Image.open(path).convert('RGBA').crop(box)
    if scale != 1:
        crop = crop.resize((crop.size[0] * scale, crop.size[1] * scale), Image.NEAREST)
    return crop


def _zoom(dark):
    """Every icon at 32 px and 16 px, magnified 4x with nearest neighbour, for pixel inspection."""
    th = THEMES[dark]
    cell = 4 * 32 + 12
    img = Image.new('RGBA', (cell * len(BUTTONS), 4 * 32 + 4 * 16 + 24), th['body'] + (255,))
    for i, (n, _) in enumerate(BUTTONS):
        img.alpha_composite(render(n, dark, 32).resize((128, 128), Image.NEAREST), (i * cell + 6, 6))
        img.alpha_composite(render(n, dark, 16).resize((64, 64), Image.NEAREST), (i * cell + 38, 6 + 128 + 10))
    return img


def preview(path, refs):
    old = os.path.join(refs, '3.png') if refs else ''
    recipe = os.path.join(ROOT, '..', 'dynamoscript14', 'roadmap-automsereing', 'tools', 'pyrevit_spike',
                          'icon_preview.png')
    rows = []
    for s in (1, 2):
        rows.append([(f'new AEC Bridge, dark, {100 * s} %', _ribbon(True, s)),
                     ('current AEC Bridge (owner screenshot)', _ref(old, (0, 28, 425, 122), s))])
    rows.append([('approved Recipe Editor set (dark, 100 %)', _ref(recipe, (16, 36, 520, 140), 1))])
    for s in (1, 2):
        rows.append([(f'new AEC Bridge, light, {100 * s} %', _ribbon(False, s))])
    rows.append([('zoom 4x: 32 px and 16 px, dark', _zoom(True))])
    rows.append([('zoom 4x: 32 px and 16 px, light', _zoom(False))])
    rows = [[c for c in r if c[1] is not None] for r in rows]
    rows = [r for r in rows if r]
    pad = 16
    width = max(sum(im.size[0] + pad for _, im in r) for r in rows) + pad
    height = sum(max(im.size[1] for _, im in r) + 22 + pad for r in rows) + pad
    sheet = Image.new('RGBA', (width, height), (0xFF, 0xFF, 0xFF, 255))
    d = ImageDraw.Draw(sheet)
    label_f = _font(13, bold=True)
    y = pad
    for r in rows:
        x = pad
        for title, im in r:
            d.text((x, y), title, fill=(0x22, 0x26, 0x2C, 255), font=label_f)
            sheet.alpha_composite(im, (x, y + 20))
            x += im.size[0] + pad
        y += max(im.size[1] for _, im in r) + 22 + pad
    d_ = os.path.dirname(os.path.abspath(path))
    if not os.path.isdir(d_):
        os.makedirs(d_)
    sheet.save(path)
    print('preview written: ' + path)


def main(argv):
    refs = argv[argv.index('--refs') + 1] if '--refs' in argv else os.environ.get('AEC_ICON_REFS', '')
    if '--preview' in argv:
        preview(argv[argv.index('--preview') + 1], refs)
    if '--preview-only' in argv:
        return
    if not os.path.isdir(OUT):
        os.makedirs(OUT)
    for name, _ in BUTTONS:
        for size in SIZES:
            for dark in (False, True):
                save(render(name, dark, size),
                     os.path.join(OUT, f"{name}_{size}_{'dark' if dark else 'light'}.png"))
    print(f'icons written: {len(BUTTONS)} buttons x (16, 32) x (light, dark) -> {OUT}')


if __name__ == '__main__':
    main(sys.argv[1:])

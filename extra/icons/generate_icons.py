"""Generate all raster icon variants for noncey (Chrome ext, favicons, Play Store)."""
from PIL import Image, ImageDraw
import math, os

DARK  = (26, 26, 46)    # #1a1a2e — brand / cursor / asterisks
WHITE = (255, 255, 255)
BORDER = (210, 210, 225) # card border

def draw_asterisk(draw, cx, cy, r, color, sw):
    """6-arm asterisk via 3 crossing lines (0°, 60°, 120°)."""
    for deg in [90, 30, 150]:
        rad = math.radians(deg)
        x1 = cx + r * math.cos(rad)
        y1 = cy - r * math.sin(rad)
        x2 = cx - r * math.cos(rad)
        y2 = cy + r * math.sin(rad)
        draw.line([(x1, y1), (x2, y2)], fill=(*color, 255), width=max(1, sw))

def draw_cross(draw, cx, cy, r, color, sw):
    """Simple 4-arm cross for very small sizes."""
    draw.line([(cx - r, cy), (cx + r, cy)], fill=(*color, 255), width=max(1, sw))
    draw.line([(cx, cy - r), (cx, cy + r)], fill=(*color, 255), width=max(1, sw))

def make_icon(canvas, art=None):
    """
    Draw the icon. art = actual icon pixel size (allows padding: e.g. 96 art in 128 canvas).
    Design space is 0-100 units.
    """
    if art is None:
        art = canvas

    img  = Image.new('RGBA', (canvas, canvas), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)

    ox = (canvas - art) // 2   # offset to centre art in canvas
    oy = (canvas - art) // 2

    def px(v): return ox + v * art / 100   # 100-unit → pixel x
    def py(v): return oy + v * art / 100   # 100-unit → pixel y
    def dp(v): return max(1, round(v * art / 100))

    # ── Card ────────────────────────────────────────────────────────────────
    rx = dp(10)
    card = [px(8), py(22), px(92), py(78)]

    # Shadow (only at ≥32 px)
    if art >= 32:
        sh = dp(2.5)
        sh_layer = Image.new('RGBA', (canvas, canvas), (0, 0, 0, 0))
        ImageDraw.Draw(sh_layer).rounded_rectangle(
            [card[0]+sh, card[1]+sh, card[2]+sh, card[3]+sh],
            radius=rx, fill=(0, 0, 0, 28)
        )
        img  = Image.alpha_composite(img, sh_layer)
        draw = ImageDraw.Draw(img)

    draw.rounded_rectangle(card, radius=rx,
                            fill=(*WHITE, 255),
                            outline=(*BORDER, 255),
                            width=max(1, dp(1.5)))

    mid_y = py(50)   # vertical centre of card

    # ── Asterisks + cursor ──────────────────────────────────────────────────
    if art <= 20:
        # 16 px: 4-arm crosses, 2 of them
        for ax in [25, 55]:
            draw_cross(draw, px(ax), mid_y, dp(9), DARK, dp(7))
        draw.rectangle([px(70), py(30), px(76), py(70)], fill=(*DARK, 255))

    elif art <= 36:
        # 32 px: 6-arm asterisks, 2 of them
        for ax in [28, 55]:
            draw_asterisk(draw, px(ax), mid_y, dp(9), DARK, dp(5))
        cw = dp(4)
        cx1 = px(66)
        draw.rounded_rectangle([cx1, py(30), cx1+cw, py(70)],
                                radius=dp(2), fill=(*DARK, 255))
    else:
        # 48 px+: 3 six-arm asterisks
        for ax in [27, 47, 67]:
            draw_asterisk(draw, px(ax), mid_y, dp(8), DARK, dp(3.5))
        cw  = dp(3.5)
        cx1 = px(77)
        draw.rounded_rectangle([cx1, py(33), cx1+cw, py(67)],
                                radius=max(1, dp(1.5)), fill=(*DARK, 255))

    return img


def opaque(img, bg=WHITE):
    """Flatten onto solid background (for apple-touch-icon)."""
    result = Image.new('RGBA', img.size, (*bg, 255))
    result.paste(img, mask=img.split()[3])
    return result


def save(img, path):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    img.save(path, 'PNG')
    print(f'  {path}')


B = r'C:\Claude'

# ── Chrome Extension ────────────────────────────────────────────────────────
print('Chrome extension icons...')
os.makedirs(B + r'\noncey.client.chromeextension\icons', exist_ok=True)
save(make_icon(16),          B + r'\noncey.client.chromeextension\icons\icon16.png')
save(make_icon(32),          B + r'\noncey.client.chromeextension\icons\icon32.png')
save(make_icon(48),          B + r'\noncey.client.chromeextension\icons\icon48.png')
save(make_icon(128, art=96), B + r'\noncey.client.chromeextension\icons\icon128.png')

# ── Daemon favicons ─────────────────────────────────────────────────────────
print('Daemon favicons...')
os.makedirs(B + r'\noncey.daemon\static', exist_ok=True)
save(make_icon(16),  B + r'\noncey.daemon\static\favicon-16x16.png')
save(make_icon(32),  B + r'\noncey.daemon\static\favicon-32x32.png')
save(opaque(make_icon(180)), B + r'\noncey.daemon\static\apple-touch-icon.png')

# ICO: Pillow resizes source image to each requested size
ico_src = make_icon(48).convert('RGBA')
ico_path = B + r'\noncey.daemon\static\favicon.ico'
ico_src.save(ico_path, format='ICO', sizes=[(16, 16), (32, 32), (48, 48)])
print(f'  {ico_path}')

# ── Master / Play Store ─────────────────────────────────────────────────────
print('Master icons...')
os.makedirs(B + r'\noncey\extra\icons', exist_ok=True)
save(make_icon(512), B + r'\noncey\extra\icons\icon-512.png')
save(make_icon(48),  B + r'\noncey\extra\icons\icon-48.png')

print('Done.')

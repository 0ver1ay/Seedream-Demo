from PIL import Image, ImageDraw
from math import sqrt


def lerp(a, b, t):
    return int(a + (b - a) * t)


def linear_gradient(size, top, bottom):
    w, h = size
    img = Image.new("RGB", size)
    px = img.load()
    for y in range(h):
        t = y / (h - 1)
        r = lerp(top[0], bottom[0], t)
        g = lerp(top[1], bottom[1], t)
        b = lerp(top[2], bottom[2], t)
        for x in range(w):
            px[x, y] = (r, g, b)
    return img


def radial_gradient_mask(size, radius):
    w, h = size
    cx, cy = w // 2, h // 2
    img = Image.new("L", size)
    px = img.load()
    maxd = float(radius)
    for y in range(h):
        for x in range(w):
            d = sqrt((x - cx) ** 2 + (y - cy) ** 2)
            t = max(0.0, min(1.0, 1.0 - d / maxd))
            px[x, y] = int(255 * t)
    return img


def main(out_path="icon-placeholder.png", size=512):
    # Colors (match seedream_desktop/theme.py — warm charcoal + amber)
    bg_top = (10, 11, 13)      # #0a0b0d
    bg_bottom = (22, 24, 29)   # #16181d
    accent_a = (232, 165, 75)  # #e8a54b
    accent_b = (111, 191, 168) # #6fbfa8

    # Background
    base = linear_gradient((size, size), bg_top, bg_bottom)
    draw = ImageDraw.Draw(base, "RGBA")

    # Soft radial glow
    glow = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    gmask = radial_gradient_mask((size, size), int(size * 0.45))
    grad = Image.new("RGBA", (size, size), accent_a + (0,))
    grad2 = Image.new("RGBA", (size, size), accent_b + (0,))
    glow.paste((accent_a[0], accent_a[1], accent_a[2], 160), (0, 0), gmask)
    glow2 = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    gmask2 = radial_gradient_mask((size, size), int(size * 0.35))
    glow2.paste((accent_b[0], accent_b[1], accent_b[2], 140), (0, 0), gmask2)
    base = Image.alpha_composite(base.convert("RGBA"), glow)
    base = Image.alpha_composite(base, glow2)

    # Central emblem (interlocking arcs)
    d = ImageDraw.Draw(base)
    pad = int(size * 0.18)
    box = (pad, pad, size - pad, size - pad)
    width = max(6, size // 36)
    # Outer ring
    d.ellipse(box, outline=(230, 232, 235, 220), width=width)
    # Two accent arcs
    d.arc(box, start=35, end=200, fill=accent_a + (255,), width=width)
    d.arc(box, start=215, end=340, fill=accent_b + (255,), width=width)

    # Inner swoosh
    inner_pad = int(size * 0.33)
    inner = (inner_pad, inner_pad, size - inner_pad, size - inner_pad)
    d.arc(inner, start=210, end=330, fill=(230, 232, 235, 220), width=max(5, size // 42))

    # Subtle border
    bpad = 2
    d.rectangle((bpad, bpad, size - bpad, size - bpad), outline=(58, 66, 80, 180), width=2)

    base.convert("RGB").save(out_path, format="PNG")


if __name__ == "__main__":
    main()



#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""生成应用图标：macOS 圆角方形 + 手机轮廓 + 下装箭头，输出 .icns 和 .png。"""
import struct
import sys
from io import BytesIO

from PIL import Image, ImageDraw


def rounded_mask(size, radius_ratio=0.2237):
    m = Image.new("L", (size, size), 0)
    d = ImageDraw.Draw(m)
    r = int(size * radius_ratio)
    d.rounded_rectangle([0, 0, size - 1, size - 1], radius=r, fill=255)
    return m


def gradient(size, top=(102, 143, 255), bottom=(124, 92, 255)):
    g = Image.new("RGB", (1, size))
    px = g.load()
    for y in range(size):
        t = y / max(1, size - 1)
        px[0, y] = tuple(int(top[i] + (bottom[i] - top[i]) * t) for i in range(3))
    return g.resize((size, size))


def draw_icon(size):
    S = size
    img = Image.new("RGBA", (S, S), (0, 0, 0, 0))
    bg = gradient(S).convert("RGBA")
    img.paste(bg, (0, 0), rounded_mask(S))
    d = ImageDraw.Draw(img)

    cx = S // 2
    # 手机：深色机身 + 白色描边
    pw, ph = int(S * 0.44), int(S * 0.54)
    px, py = (S - pw) // 2, int(S * 0.355)
    r = int(pw * 0.19)
    bw = max(2, int(S * 0.022))
    d.rounded_rectangle([px, py, px + pw, py + ph], radius=r,
                        fill=(26, 31, 46, 255), outline=(255, 255, 255, 255),
                        width=bw)
    # 底部横条
    iw = int(pw * 0.32)
    iy = py + ph - int(S * 0.045)
    d.rounded_rectangle([cx - iw // 2, iy - max(2, int(S * 0.009)),
                         cx + iw // 2, iy + max(2, int(S * 0.009))],
                        radius=S, fill=(255, 255, 255, 220))

    # 向下的安装箭头，箭头尖落进屏幕里
    shaft_w = int(S * 0.082)
    top_y = int(S * 0.115)
    neck_y = int(S * 0.455)
    d.rounded_rectangle([cx - shaft_w // 2, top_y, cx + shaft_w // 2, neck_y],
                        radius=shaft_w // 2, fill=(255, 255, 255, 255))
    hw = int(S * 0.155)
    d.polygon([(cx - hw, neck_y - int(S * 0.025)), (cx + hw, neck_y - int(S * 0.025)),
               (cx, neck_y + int(S * 0.155))], fill=(255, 255, 255, 255))
    return img


ICNS_TYPES = [
    (b"icp4", 16), (b"icp5", 32), (b"icp6", 64),
    (b"ic07", 128), (b"ic08", 256), (b"ic09", 512), (b"ic10", 1024),
    (b"ic11", 32), (b"ic12", 64), (b"ic13", 256), (b"ic14", 512),
]


def build_icns(path):
    chunks = []
    cache = {}
    for code, size in ICNS_TYPES:
        if size not in cache:
            buf = BytesIO()
            draw_icon(size).save(buf, format="PNG")
            cache[size] = buf.getvalue()
        png = cache[size]
        chunks.append(code + struct.pack(">I", len(png) + 8) + png)
    body = b"".join(chunks)
    data = b"icns" + struct.pack(">I", len(body) + 8) + body
    with open(path, "wb") as f:
        f.write(data)
    return len(data)


if __name__ == "__main__":
    out = sys.argv[1] if len(sys.argv) > 1 else "app.icns"
    n = build_icns(out)
    draw_icon(512).save(out.replace(".icns", "_preview.png"))
    print("icns bytes:", n)

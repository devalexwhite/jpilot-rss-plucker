#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-or-later
# Copyright (C) 2026 Alex White

"""Redraw Fourshade pixel marks, banners, and badges.

The SVG files are the assets to copy. Run this when the wordmark or the
banner copy changes. Banner text uses Departure Mono if it is installed;
pixel wordmarks are rectangles and do not need the font.

    python3 brand/tools/build_assets.py
"""

from pathlib import Path
import subprocess
import tempfile

ROOT = Path(__file__).resolve().parents[2]

# Generic 5×7 capitals drawn for this kit. Not a Palm system font.
FONT = {
    "A": ["01110", "10001", "10001", "11111", "10001", "10001", "10001"],
    "B": ["11110", "10001", "10001", "11110", "10001", "10001", "11110"],
    "C": ["01111", "10000", "10000", "10000", "10000", "10000", "01111"],
    "D": ["11110", "10001", "10001", "10001", "10001", "10001", "11110"],
    "E": ["11111", "10000", "10000", "11110", "10000", "10000", "11111"],
    "F": ["11111", "10000", "10000", "11110", "10000", "10000", "10000"],
    "G": ["01110", "10001", "10000", "10111", "10001", "10001", "01110"],
    "H": ["10001", "10001", "10001", "11111", "10001", "10001", "10001"],
    "I": ["11111", "00100", "00100", "00100", "00100", "00100", "11111"],
    "J": ["00111", "00010", "00010", "00010", "10010", "10010", "01100"],
    "K": ["10001", "10010", "10100", "11000", "10100", "10010", "10001"],
    "L": ["10000", "10000", "10000", "10000", "10000", "10000", "11111"],
    "M": ["10001", "11011", "10101", "10101", "10001", "10001", "10001"],
    "N": ["10001", "11001", "10101", "10011", "10001", "10001", "10001"],
    "O": ["01110", "10001", "10001", "10001", "10001", "10001", "01110"],
    "P": ["11110", "10001", "10001", "11110", "10000", "10000", "10000"],
    "Q": ["01110", "10001", "10001", "10001", "10101", "10010", "01101"],
    "R": ["11110", "10001", "10001", "11110", "10100", "10010", "10001"],
    "S": ["01110", "10001", "10000", "01110", "00001", "10001", "01110"],
    "T": ["11111", "00100", "00100", "00100", "00100", "00100", "00100"],
    "U": ["10001", "10001", "10001", "10001", "10001", "10001", "01110"],
    "V": ["10001", "10001", "10001", "10001", "10001", "01010", "00100"],
    "W": ["10001", "10001", "10001", "10101", "10101", "10101", "01010"],
    "X": ["10001", "10001", "01010", "00100", "01010", "10001", "10001"],
    "Y": ["10001", "10001", "01010", "00100", "00100", "00100", "00100"],
    "Z": ["11111", "00001", "00010", "00100", "01000", "10000", "11111"],
    "0": ["01110", "10001", "10011", "10101", "11001", "10001", "01110"],
    "1": ["00100", "01100", "00100", "00100", "00100", "00100", "01110"],
    "2": ["01110", "10001", "00001", "00010", "00100", "01000", "11111"],
    "3": ["11110", "00001", "00001", "01110", "00001", "00001", "11110"],
    "4": ["00010", "00110", "01010", "10010", "11111", "00010", "00010"],
    "5": ["11111", "10000", "11110", "00001", "00001", "10001", "01110"],
    "6": ["00110", "01000", "10000", "11110", "10001", "10001", "01110"],
    "7": ["11111", "00001", "00010", "00100", "01000", "01000", "01000"],
    "8": ["01110", "10001", "10001", "01110", "10001", "10001", "01110"],
    "9": ["01110", "10001", "10001", "01111", "00001", "00010", "01100"],
    " ": ["00000", "00000", "00000", "00000", "00000", "00000", "00000"],
    ".": ["00000", "00000", "00000", "00000", "00000", "01100", "01100"],
    ",": ["00000", "00000", "00000", "00000", "00110", "00100", "01000"],
    "'": ["00100", "00100", "01000", "00000", "00000", "00000", "00000"],
    "-": ["00000", "00000", "00000", "11111", "00000", "00000", "00000"],
    ":": ["00000", "01100", "01100", "00000", "01100", "01100", "00000"],
}

PAPER = "#E8E6DE"
INK = "#161814"
GRAPHITE = "#4E524A"
PHOSPHOR = "#D7E7A1"
BACKLIGHT = "#C5D48A"
OLIVE = "#5C6B3A"
PINE = "#3E4A24"
MOSS = "#2C3420"
NIGHT = "#14180F"

MARK = {
    "light": dict(body=INK, screen=PAPER, select=INK, select_text=PAPER,
                  row=INK, row_dim=GRAPHITE, lamp=BACKLIGHT),
    "dark": dict(body=MOSS, screen=NIGHT, select=PHOSPHOR, select_text=NIGHT,
                 row=PHOSPHOR, row_dim=BACKLIGHT, lamp=BACKLIGHT),
    "lcd": dict(body=NIGHT, screen=BACKLIGHT, select=NIGHT, select_text=BACKLIGHT,
                row=NIGHT, row_dim=MOSS, lamp=PHOSPHOR),
    # Moss bezel so the mark stays visible on a Night panel.
    "panel": dict(body=MOSS, screen=BACKLIGHT, select=NIGHT, select_text=BACKLIGHT,
                  row=NIGHT, row_dim=MOSS, lamp=PHOSPHOR),
}
WORD = {"light": INK, "dark": PHOSPHOR, "lcd": NIGHT}
PNG_BG = {"light": PAPER, "dark": NIGHT, "lcd": PAPER}
WORD_PNG_BG = {"light": PAPER, "dark": NIGHT, "lcd": BACKLIGHT}


def esc(text):
    return (text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;"))


def rect(x, y, w, h, fill, rx=None):
    extra = f' rx="{rx}"' if rx else ""
    return f'<rect x="{x}" y="{y}" width="{w}" height="{h}"{extra} fill="{fill}"/>'


def pixel_text(text, x, y, scale, fill):
    parts = []
    cx = x
    for ch in text:
        glyph = FONT[ch]
        width = len(glyph[0])
        for row, bits in enumerate(glyph):
            col = 0
            while col < width:
                if bits[col] == "1":
                    start = col
                    while col < width and bits[col] == "1":
                        col += 1
                    parts.append(rect(cx + start * scale, y + row * scale,
                                      (col - start) * scale, scale, fill))
                else:
                    col += 1
        cx += (width + 1) * scale
    return "".join(parts)


def text_width(text, scale):
    if not text:
        return 0
    return sum((len(FONT[ch][0]) + 1) * scale for ch in text) - scale


def mark_shapes(variant, x=0, y=0, scale=1):
    c = MARK[variant]
    s = scale
    body = rect(x, y, 36 * s, 48 * s, c["body"], rx=4 * s)
    screen = rect(x + 4 * s, y + 4 * s, 28 * s, 28 * s, c["screen"])
    select = rect(x + 7 * s, y + 8 * s, 22 * s, 5 * s, c["select"])
    select_text = rect(x + 9 * s, y + 10 * s, 12 * s, 2 * s, c["select_text"])
    rows = (
        rect(x + 9 * s, y + 16 * s, 16 * s, 2 * s, c["row"])
        + rect(x + 9 * s, y + 20 * s, 11 * s, 2 * s, c["row"])
        + rect(x + 9 * s, y + 24 * s, 18 * s, 2 * s, c["row_dim"])
    )
    lamp = rect(x + 16 * s, y + 38 * s, 4 * s, 4 * s, c["lamp"])
    return body + screen + select + select_text + rows + lamp


def document(width, height, body, background=None, title="Fourshade", desc=""):
    bg = rect(0, 0, width, height, background) if background else ""
    return (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" '
        f'viewBox="0 0 {width} {height}" role="img">\n'
        f"<title>{esc(title)}</title>\n"
        f"<desc>{esc(desc)}</desc>\n"
        f"{bg}{body}\n</svg>\n"
    )


def write_svg(path, svg):
    path = ROOT / path
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(svg, encoding="utf-8")
    return path


def rasterize(svg, png_path, width):
    png_path = ROOT / png_path
    png_path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile("w", suffix=".svg", delete=False) as handle:
        handle.write(svg)
        tmp = handle.name
    subprocess.run(
        ["rsvg-convert", "-w", str(width), "-o", str(png_path), tmp],
        check=True,
    )
    Path(tmp).unlink()


def pair(rel, width, height, body, png_bg, title, desc, png_width):
    svg = document(width, height, body, None, title, desc)
    write_svg(rel, svg)
    baked = document(width, height, body, png_bg, title, desc)
    rasterize(baked, str(Path(rel).with_suffix(".png")), png_width)


def text_el(id_, x, y, size, fill, content, anchor="start"):
    return (
        f'<text id="{id_}" x="{x}" y="{y}" fill="{fill}" font-size="{size}" '
        f'font-family="Departure Mono, monospace" text-anchor="{anchor}">{esc(content)}</text>'
    )


def badge(filename, label, message):
    scale = 2
    label_w = text_width(label, scale) + 16
    message_w = text_width(message, scale) + 16
    height = 28
    width = label_w + message_w
    y = (height - 7 * scale) // 2
    body = (
        '<g shape-rendering="crispEdges">'
        + rect(0, 0, label_w, height, INK)
        + rect(label_w, 0, message_w, height, MOSS)
        + pixel_text(label, 8, y, scale, PHOSPHOR)
        + pixel_text(message, label_w + 8, y, scale, PHOSPHOR)
        + "</g>"
    )
    pair(
        f"brand/assets/badges/{filename}.svg",
        width, height, body, PAPER,
        f"{label} {message}",
        "Fourshade badge. Flat square, Phosphor on Ink and Moss.",
        width * 4,
    )


def hero(path, kicker, title, pitch, png_width=1280):
    # EDIT: text nodes whose ids start with edit-
    body = (
        rect(0, 0, 1280, 360, PAPER)
        + rect(0, 0, 500, 360, NIGHT)
        + '<g shape-rendering="crispEdges">'
        + mark_shapes("panel", 56, 132, 2)
        + "</g>"
        + text_el("edit-collection", 156, 186, 33, PHOSPHOR, "FOURSHADE")
        + text_el("edit-tagline-1", 156, 224, 22, BACKLIGHT, "Palm OS hardware,")
        + text_el("edit-tagline-2", 156, 252, 22, BACKLIGHT, "still at work.")
        + text_el("edit-kicker", 548, 132, 22, PINE, kicker)
        + text_el("edit-title", 548, 196, 44, INK, title)
        + text_el("edit-pitch-1", 548, 252, 22, GRAPHITE, pitch[0])
        + text_el("edit-pitch-2", 548, 282, 22, GRAPHITE, pitch[1])
    )
    svg = document(1280, 360, body, None, title, "Fourshade README banner, 1280 by 360.")
    # The banner already paints its background, so the SVG and the PNG match.
    write_svg(path, svg)
    rasterize(svg, str(Path(path).with_suffix(".png")), png_width)


def screen_card(x, y, label):
    """A drawn list. The caption in the chin says this is not a photograph."""
    body = rect(x, y, 440, 520, NIGHT, rx=18)
    body += rect(x + 28, y + 28, 384, 360, BACKLIGHT)
    rows = [(36, 300), (36, 220), (36, 260), (36, 180), (36, 240)]
    yy = y + 52
    for i, (rx, rw) in enumerate(rows):
        if i == 0:
            body += rect(x + rx, yy, 340, 36, NIGHT)
            body += '<g shape-rendering="crispEdges">'
            body += pixel_text(label, x + rx + 16, yy + 8, 3, BACKLIGHT)
            body += "</g>"
        else:
            body += rect(x + rx + 8, yy + 10, rw, 16, NIGHT)
        yy += 52
    body += text_el("edit-diagram-caption", x + 220, y + 470, 16, PHOSPHOR,
                    "Diagram, not a device photo.", "middle")
    return body


def social(path, kicker, title, pitch_lines, diagram_label):
    body = (
        rect(0, 0, 1280, 640, PAPER)
        + rect(0, 0, 1280, 12, NIGHT)
        + '<g shape-rendering="crispEdges">'
        + mark_shapes("lcd", 64, 64, 3)
        + pixel_text("FOURSHADE", 196, 96, 6, INK)
        + pixel_text("PALM OS HARDWARE, STILL AT WORK.", 196, 160, 2, PINE)
        + "</g>"
        + text_el("edit-kicker", 64, 280, 22, PINE, kicker)
        + text_el("edit-title", 64, 360, 55, INK, title)
        + text_el("edit-pitch-1", 64, 430, 22, GRAPHITE, pitch_lines[0])
        + text_el("edit-pitch-2", 64, 462, 22, GRAPHITE, pitch_lines[1])
        + screen_card(792, 48, diagram_label)
    )
    svg = document(1280, 640, body, None, title, "Fourshade social preview, 1280 by 640. The screen is a diagram.")
    write_svg(path, svg)
    rasterize(svg, str(Path(path).with_suffix(".png")), 1280)


def placeholder(path, lines):
    body = (
        rect(0, 0, 960, 540, PAPER)
        + '<rect x="24" y="24" width="912" height="492" fill="none" stroke="#161814" '
        'stroke-width="4" stroke-dasharray="12 10"/>'
        + text_el("edit-placeholder-label", 480, 200, 55, INK, "PLACEHOLDER", "middle")
    )
    y = 270
    for i, line in enumerate(lines):
        body += text_el(f"edit-placeholder-{i}", 480, y, 22, GRAPHITE, line, "middle")
        y += 36
    svg = document(960, 540, body, None, "Placeholder", "Not a capture.")
    write_svg(path, svg)
    rasterize(svg, str(Path(path).with_suffix(".png")), 960)


def build():
    desc_mark = "Square screen, selected row, three quieter rows, one lamp pixel. Not a specific Palm model."
    for name in ("light", "dark", "lcd"):
        body = '<g shape-rendering="crispEdges">' + mark_shapes(name) + "</g>"
        pair(f"brand/assets/mark-{name}.svg", 36, 48, body, PNG_BG[name],
             f"Fourshade mark, {name}", desc_mark, 288)
        word = '<g shape-rendering="crispEdges">' + pixel_text("FOURSHADE", 0, 0, 8, WORD[name]) + "</g>"
        pair(f"brand/assets/wordmark-{name}.svg", text_width("FOURSHADE", 8), 56, word,
             WORD_PNG_BG[name], f"Fourshade wordmark, {name}",
             "FOURSHADE set in a 5 by 7 pixel grid.", 960)
        lockup_word = pixel_text("FOURSHADE", 72 + 20, 30, 5, WORD["light" if name == "lcd" else name])
        if name == "dark":
            lock_fill_word = WORD["dark"]
            lockup_word = pixel_text("FOURSHADE", 92, 30, 5, lock_fill_word)
        body = (
            '<g shape-rendering="crispEdges">'
            + mark_shapes(name, 0, 0, 2)
            + lockup_word
            + "</g>"
        )
        pair(f"brand/assets/lockup-{name}.svg", 92 + text_width("FOURSHADE", 5), 96, body,
             PNG_BG[name], f"Fourshade lockup, {name}",
             "Mark and FOURSHADE wordmark.", 1200)

    badge("palm-os-compatible", "PALM OS", "COMPATIBLE")
    badge("hotsync-ready", "HOTSYNC", "READY")
    badge("fourshade", "FOURSHADE", "COLLECTION")

    # Alphabet specimen.
    letters = "ABCDEFGHIJKLM NOPQRSTUVWXYZ 0123456789"
    body = rect(0, 0, text_width("ABCDEFGHIJKLM", 4) + 16, 120, PAPER)
    body += '<g shape-rendering="crispEdges">'
    body += pixel_text("ABCDEFGHIJKLM", 8, 8, 4, INK)
    body += pixel_text("NOPQRSTUVWXYZ", 8, 44, 4, INK)
    body += pixel_text("0123456789", 8, 80, 4, INK)
    body += "</g>"
    width = text_width("ABCDEFGHIJKLM", 4) + 16
    specimen = document(width, 120, body, None, "Fourshade pixel alphabet",
                        "5 by 7 capitals used by the wordmarks and badges.")
    write_svg("brand/assets/pixel-alphabet.svg", specimen)
    rasterize(specimen, "brand/assets/pixel-alphabet.png", width * 2)

    hero("brand/assets/hero-banner.svg", "PROJECT", "Project name",
         ["What the handheld has", "after you unplug."])
    hero("docs/hero.svg", "J-PILOT CONDUIT", "Feeds to Plucker",
         ["Today's RSS, Atom, and Gemsub,", "installed as a Plucker document."])

    social("brand/assets/social-preview.svg", "PROJECT", "Project name",
           ["One sentence on what the", "handheld can do after a sync."], "CONTENTS")
    social(".github/social-preview.svg", "J-PILOT CONDUIT", "Feeds to Plucker",
           ["Today's RSS, Atom, and Gemsub,", "packed for Plucker at HotSync."], "FEEDS TODAY")

    placeholder("brand/assets/placeholder-frame.svg",
                ["Say what capture belongs here.", "This frame is not a screenshot."])
    placeholder("docs/placeholder-jpilot.svg",
                ["The Feeds to Plucker panel in J-Pilot.", "Not a window capture."])
    placeholder("docs/placeholder-device.svg",
                ["J-Pilot RSS Today open in Plucker.", "A photograph from the Tungsten T3 test goes here."])


if __name__ == "__main__":
    build()

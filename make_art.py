"""
Draw the picture for each case.

    python make_art.py

Writes one SVG per case into web/img/. The pictures are drawn in code, in the
game's colours, so there are no image files to find or licence. To change a
picture, edit its function below and run this again.
"""

import random
from pathlib import Path

OUT = Path(__file__).parent / "web" / "img"
W, H = 600, 375

INK, NIGHT, FAR, MID, NEAR, BLACK = "#0B0E13", "#141B28", "#1F2836", "#18202C", "#10151D", "#07090D"
AMBER, CREAM, RED, PALE = "#E3A857", "#EDE6D6", "#C8503F", "#9AA3B2"


def rect(x, y, w, h, fill, rx=0, op=1):
    return f'<rect x="{x}" y="{y}" width="{w}" height="{h}" rx="{rx}" fill="{fill}" opacity="{op}"/>'


def poly(points, fill, op=1):
    return f'<polygon points="{" ".join(f"{x},{y}" for x, y in points)}" fill="{fill}" opacity="{op}"/>'


def circle(cx, cy, r, fill, op=1):
    return f'<circle cx="{cx}" cy="{cy}" r="{r}" fill="{fill}" opacity="{op}"/>'


def ellipse(cx, cy, rx, ry, fill, op=1):
    return f'<ellipse cx="{cx}" cy="{cy}" rx="{rx}" ry="{ry}" fill="{fill}" opacity="{op}"/>'


def line(x1, y1, x2, y2, stroke, width=1, op=1):
    return f'<line x1="{x1}" y1="{y1}" x2="{x2}" y2="{y2}" stroke="{stroke}" stroke-width="{width}" opacity="{op}" stroke-linecap="round"/>'


def path(d, fill="none", stroke="none", width=1, op=1):
    return f'<path d="{d}" fill="{fill}" stroke="{stroke}" stroke-width="{width}" opacity="{op}"/>'


def glow(cx, cy, r, colour=AMBER, op=0.35):
    """A soft light. Uses a gradient defined once in the page header."""
    name = {AMBER: "gAmber", CREAM: "gCream", RED: "gRed"}[colour]
    return f'<circle cx="{cx}" cy="{cy}" r="{r}" fill="url(#{name})" opacity="{op}"/>'


def stars(seed, n=40, ymax=200):
    rng = random.Random(seed)
    return "".join(circle(rng.randint(5, W - 5), rng.randint(5, ymax), rng.choice([0.7, 0.9, 1.3]), CREAM, rng.choice([0.25, 0.4, 0.7])) for _ in range(n))


def snow(seed, n=70):
    rng = random.Random(seed)
    return "".join(circle(rng.randint(0, W), rng.randint(0, H), rng.choice([1, 1.4, 2]), CREAM, rng.choice([0.25, 0.45, 0.7])) for _ in range(n))


def rain(seed, n=60):
    rng = random.Random(seed)
    out = ""
    for _ in range(n):
        x, y = rng.randint(-20, W), rng.randint(0, H)
        out += line(x, y, x + 9, y + 22, PALE, 1, 0.22)
    return out


def windows(x, y, cols, rows, w, h, gx, gy, seed, lit=0.6):
    """A grid of windows, some lit."""
    rng = random.Random(seed)
    out = ""
    for r in range(rows):
        for c in range(cols):
            on = rng.random() < lit
            out += rect(x + c * (w + gx), y + r * (h + gy), w, h, AMBER if on else FAR, 1, 0.95 if on else 0.9)
    return out


def moon(cx, cy, r=26, colour=CREAM):
    return glow(cx, cy, r * 3.2, CREAM if colour == CREAM else AMBER, 0.35) + circle(cx, cy, r, colour, 0.95)


def waves(y, seed, rows=4):
    rng = random.Random(seed)
    out = ""
    for i in range(rows):
        yy = y + i * 14
        d = f"M0 {yy}" + "".join(f" q{20 + rng.randint(0, 12)} -{4 + rng.randint(0, 3)} {40 + rng.randint(0, 20)} 0" for _ in range(14))
        out += path(d, stroke=PALE, width=1.2, op=0.18 + 0.05 * i)
    return out


def pine(x, y, s=1.0, fill=BLACK):
    return (poly([(x, y - 70 * s), (x - 20 * s, y - 30 * s), (x + 20 * s, y - 30 * s)], fill)
            + poly([(x, y - 50 * s), (x - 26 * s, y - 8 * s), (x + 26 * s, y - 8 * s)], fill)
            + rect(x - 3 * s, y - 10 * s, 6 * s, 12 * s, fill))


# ---- one function per case ------------------------------------------------
def harbour_light():
    s = rain(1) + glow(410, 150, 150, AMBER, 0.25)
    s += poly([(0, 375), (0, 250), (120, 232), (250, 222), (470, 226), (540, 250), (560, 375)], MID)       # cliff
    s += rect(260, 120, 230, 106, BLACK) + poly([(250, 122), (375, 78), (500, 122)], BLACK)               # hotel
    s += rect(300, 70, 16, 34, BLACK) + rect(430, 76, 16, 30, BLACK)                                        # chimneys
    s += windows(278, 136, 6, 3, 20, 18, 14, 10, 4, 0.55) + rect(366, 196, 22, 30, AMBER, 1)
    s += rect(0, 300, 600, 75, INK, 0, 0.9) + waves(306, 2, 5)
    return s


def the_pine_ridge():
    s = stars(3, 45, 170) + moon(470, 74)
    s += poly([(0, 260), (120, 110), (230, 250)], FAR) + poly([(160, 270), (330, 80), (520, 270)], MID)
    s += poly([(330, 80), (300, 118), (322, 112), (340, 126), (362, 116)], CREAM, 0.5)                      # snow cap
    s += poly([(0, 375), (0, 285), (600, 265), (600, 375)], "#222C3B")                                      # snow field
    s += poly([(250, 290), (330, 190), (410, 290)], BLACK) + rect(268, 262, 124, 30, BLACK)                 # A-frame
    s += poly([(312, 262), (330, 232), (348, 262)], AMBER) + rect(288, 268, 16, 14, AMBER, 1) + rect(356, 268, 16, 14, AMBER, 1)
    s += glow(330, 262, 80, AMBER, 0.3)
    s += pine(120, 310, 1.3) + pine(180, 300, 0.9) + pine(470, 304, 1.2) + pine(530, 318, 1.5) + pine(60, 330, 1.6)
    return s + snow(5, 60)


def the_night_sleeper():
    s = stars(6, 30, 140) + poly([(0, 250), (150, 120), (300, 250)], FAR) + poly([(250, 255), (430, 95), (600, 255)], MID)
    s += poly([(0, 375), (0, 262), (600, 262), (600, 375)], "#222C3B")
    s += line(0, 300, 600, 300, BLACK, 4) + line(0, 306, 600, 306, FAR, 2)
    # engine
    s += rect(60, 250, 96, 40, BLACK, 4) + rect(132, 228, 44, 62, BLACK, 3) + rect(72, 232, 12, 20, BLACK) + rect(140, 238, 16, 14, AMBER, 1)
    s += poly([(40, 290), (60, 262), (60, 290)], BLACK)
    for cx in (80, 112, 148):
        s += circle(cx, 292, 11, BLACK) + circle(cx, 292, 4, FAR)
    s += circle(78, 214, 12, PALE, 0.25) + circle(96, 196, 16, PALE, 0.2) + circle(124, 176, 21, PALE, 0.14)
    # carriages
    for x in (184, 330, 476):
        s += rect(x, 240, 138, 50, BLACK, 4) + windows(x + 10, 252, 6, 1, 13, 15, 8, 0, x, 0.7)
        s += circle(x + 26, 292, 8, BLACK) + circle(x + 112, 292, 8, BLACK)
    s += glow(330, 262, 150, AMBER, 0.18)
    s += poly([(0, 375), (0, 318), (90, 300), (200, 322), (600, 330), (600, 375)], "#2B3648")              # drift
    return s + snow(7, 90)


def the_skerry_light():
    s = stars(8, 30, 150)
    s += poly([(300, 96), (0, 20), (0, 110)], AMBER, 0.20) + poly([(300, 96), (600, 40), (600, 130)], AMBER, 0.20)   # beams
    s += poly([(150, 320), (210, 262), (270, 250), (350, 252), (420, 276), (470, 320)], BLACK)             # rock
    s += poly([(280, 252), (290, 112), (310, 112), (320, 252)], "#C9C2B2")                                  # tower
    s += poly([(288, 140), (312, 140), (313, 162), (287, 162)], RED) + poly([(284, 196), (316, 196), (317, 218), (283, 218)], RED)
    s += rect(284, 96, 32, 16, BLACK) + rect(290, 84, 20, 14, AMBER, 1) + poly([(286, 84), (300, 68), (314, 84)], BLACK)
    s += glow(300, 92, 60, AMBER, 0.6) + rect(330, 232, 44, 22, BLACK) + rect(344, 238, 9, 9, AMBER, 1)
    s += rect(0, 310, 600, 65, INK, 0, 0.92) + waves(312, 9, 5)
    return s


def the_final_curtain():
    s = poly([(300, -10), (200, 300), (400, 300)], CREAM, 0.13) + ellipse(300, 302, 110, 20, CREAM, 0.16)
    s += rect(0, 310, 600, 65, BLACK)
    # chair
    s += rect(286, 250, 30, 5, BLACK) + rect(286, 214, 4, 90, BLACK) + rect(312, 254, 4, 50, BLACK) + rect(286, 214, 26, 5, BLACK) + rect(286, 228, 26, 4, BLACK)
    # curtains
    for side in (0, 1):
        pts = [(0, 0), (150, 0), (120, 120), (140, 250), (100, 375), (0, 375)]
        if side:
            pts = [(W - x, y) for x, y in pts]
        s += poly(pts, "#5A2420")
        for fx in (30, 62, 96):
            x = W - fx if side else fx
            s += line(x, 0, x - (6 if not side else -6), 375, BLACK, 6, 0.35)
    s += rect(0, 0, 600, 34, "#431A18") + "".join(path(f"M{x} 34 q25 26 50 0", fill="#431A18") for x in range(0, 600, 50))
    return s + glow(300, 150, 170, AMBER, 0.12)


def the_aurora_drift():
    s = stars(10, 40, 150)
    for i, y in enumerate((60, 86, 112)):
        s += path(f"M-20 {y} C120 {y - 40} 240 {y + 40} 380 {y - 10} S560 {y - 30} 620 {y + 10}", stroke="#6FB7A8", width=16 - i * 3, op=0.16 + i * 0.05)
    s += rect(0, 285, 600, 90, "#1A2331")
    s += poly([(170, 290), (190, 250), (430, 250), (470, 290)], BLACK) + rect(250, 214, 110, 38, BLACK) + rect(280, 192, 50, 24, BLACK)
    s += rect(300, 120, 4, 74, BLACK) + line(302, 130, 250, 214, BLACK, 1.5) + line(302, 130, 360, 214, BLACK, 1.5) + rect(328, 180, 14, 20, BLACK)
    s += windows(260, 224, 5, 1, 12, 10, 8, 0, 3, 0.7) + "".join(circle(x, 268, 3.5, AMBER, 0.9) for x in (220, 250, 380, 410))
    for pts in ([(20, 330), (90, 310), (180, 322), (150, 350), (40, 352)], [(380, 340), (470, 318), (590, 330), (560, 362), (420, 364)],
                [(230, 352), (300, 340), (350, 356), (290, 372)], [(60, 296), (130, 290), (150, 302), (80, 306)], [(470, 292), (560, 286), (590, 300), (500, 304)]):
        s += poly(pts, CREAM, 0.22)
    return s + glow(310, 232, 110, AMBER, 0.18)


def the_flooded_vale():
    s = rain(11, 70) + poly([(0, 250), (140, 196), (320, 226), (470, 190), (600, 232), (600, 262), (0, 262)], FAR)
    house = rect(170, 150, 260, 100, BLACK) + rect(262, 128, 76, 24, BLACK) + poly([(254, 130), (300, 100), (346, 130)], BLACK)
    house += "".join(rect(x, 122, 14, 30, BLACK) for x in (190, 232, 356, 398))
    s += house + windows(186, 166, 8, 2, 16, 22, 14, 14, 12, 0.5) + rect(291, 212, 18, 38, AMBER, 1)
    # bare tree
    s += rect(498, 150, 7, 108, BLACK) + line(501, 190, 470, 150, BLACK, 4) + line(501, 172, 536, 132, BLACK, 4) + line(480, 164, 462, 150, BLACK, 2) + line(524, 146, 546, 150, BLACK, 2)
    s += rect(0, 252, 600, 123, "#151D29")
    s += rect(170, 254, 260, 60, BLACK, 0, 0.35) + "".join(rect(190 + i * 30, 262, 14, 26, AMBER, 1, 0.14) for i in range(8))
    s += "".join(line(20 + (i * 97) % 520, 270 + i * 12, 90 + (i * 97) % 520, 270 + i * 12, PALE, 1.4, 0.22) for i in range(9))
    return s + glow(300, 210, 150, AMBER, 0.14)


def the_high_dome():
    s = stars(13, 110, 300) + path("M40 60 C200 10 380 30 580 110", stroke=CREAM, width=26, op=0.05)
    s += poly([(0, 375), (0, 300), (130, 250), (240, 262), (380, 230), (500, 262), (600, 250), (600, 375)], MID)
    s += rect(230, 226, 150, 60, BLACK) + path("M222 228 A83 83 0 0 1 388 228 Z", fill="#3A4558")
    s += poly([(296, 228), (300, 147), (322, 149), (326, 228)], BLACK) + line(311, 226, 330, 120, AMBER, 3, 0.9)   # slit and telescope
    s += rect(246, 250, 14, 16, AMBER, 1) + rect(350, 250, 14, 16, AMBER, 1) + rect(400, 256, 60, 30, BLACK) + rect(416, 264, 12, 10, AMBER, 1)
    s += poly([(0, 375), (0, 320), (160, 290), (320, 300), (470, 286), (600, 300), (600, 375)], "#2B3648")
    return s + glow(311, 200, 120, AMBER, 0.14) + snow(14, 35)


def the_angels_share():
    s = rain(15, 55) + poly([(0, 270), (90, 220), (230, 200), (420, 214), (560, 250), (600, 270)], FAR)
    s += rect(150, 190, 150, 80, BLACK) + poly([(140, 192), (225, 150), (310, 192)], BLACK)                # main shed
    s += rect(330, 176, 70, 94, BLACK) + poly([(322, 178), (365, 128), (408, 178)], BLACK)                 # kiln
    s += poly([(350, 130), (365, 100), (380, 130)], BLACK) + rect(360, 86, 10, 16, BLACK) + poly([(352, 88), (365, 76), (378, 88)], BLACK)   # pagoda
    s += windows(166, 208, 4, 2, 18, 16, 14, 10, 16, 0.6) + rect(354, 220, 22, 26, AMBER, 1)
    s += circle(365, 66, 12, PALE, 0.2) + circle(380, 46, 17, PALE, 0.15)
    s += rect(0, 268, 600, 107, NEAR)
    for cx, cy in ((80, 300), (118, 300), (99, 274), (470, 304), (508, 304), (546, 304), (489, 278), (527, 278)):   # casks
        s += rect(cx - 17, cy - 13, 34, 26, BLACK, 7) + line(cx - 9, cy - 13, cx - 9, cy + 13, AMBER, 1.5, 0.5) + line(cx + 9, cy - 13, cx + 9, cy + 13, AMBER, 1.5, 0.5)
    s += rect(0, 330, 600, 45, INK, 0, 0.9) + waves(336, 17, 3)
    return s + glow(260, 220, 150, AMBER, 0.16)


def the_last_vintage():
    s = stars(18, 25, 120) + moon(450, 96, 44, AMBER)
    s += path("M0 250 C150 170 330 190 600 240 L600 375 L0 375 Z", fill=MID)
    s += rect(96, 160, 110, 56, BLACK) + poly([(88, 162), (151, 126), (214, 162)], BLACK) + rect(170, 124, 12, 26, BLACK)
    s += windows(110, 174, 4, 1, 14, 16, 10, 0, 19, 0.75)
    for r in range(6):                                                                                      # vine rows
        y0 = 236 + r * 20
        for i in range(18):
            x = 30 + i * 32 + r * 9
            y = y0 - 18 * (1 - abs(x - 300) / 420) + (x - 300) * 0.02
            s += rect(x, y - 12, 2, 14, BLACK) + circle(x + 1, y - 13, 5 + r * 0.4, BLACK)
    s += rect(0, 345, 600, 30, "#151D29") + "".join(line(40 + i * 70, 356 + (i % 2) * 7, 90 + i * 70, 356 + (i % 2) * 7, PALE, 1.3, 0.25) for i in range(8))
    return s


def the_night_gallery():
    s = stars(20, 25, 110) + rect(0, 300, 600, 75, NEAR)
    s += poly([(110, 120), (300, 56), (490, 120)], BLACK) + rect(110, 120, 380, 16, BLACK) + rect(124, 136, 352, 150, "#0D1118")
    s += rect(278, 180, 44, 106, AMBER, 1, 0.9) + glow(300, 232, 130, AMBER, 0.22)
    for i in range(6):
        x = 134 + i * 64
        s += rect(x, 136, 18, 150, BLACK) + rect(x - 4, 136, 26, 7, BLACK) + rect(x - 4, 279, 26, 7, BLACK)
    for i, inset in enumerate((0, 14, 28)):
        s += rect(96 + inset * 0 - i * 12, 286 + i * 9, 408 + i * 24, 9, BLACK)
    for y in range(190, 280, 12):                                                                           # shutter over the door
        s += line(280, y, 320, y, BLACK, 2.5, 0.55)
    # bust on a plinth
    s += rect(500, 250, 46, 90, BLACK) + rect(494, 244, 58, 8, BLACK) + circle(523, 206, 17, BLACK) + path("M498 244 Q500 222 523 222 Q546 222 548 244 Z", fill=BLACK)
    return s


def the_sealed_chamber():
    s = moon(456, 86, 36, AMBER) + rect(0, 0, 600, 375, AMBER, 0, 0.05)
    s += poly([(60, 250), (170, 130), (280, 250)], FAR) + poly([(170, 130), (200, 250), (280, 250)], MID) + poly([(250, 250), (330, 168), (410, 250)], FAR)
    s += path("M0 250 C120 226 260 262 400 240 S560 232 600 246 L600 375 L0 375 Z", fill=MID)
    s += path("M0 300 C160 268 320 316 600 284 L600 375 L0 375 Z", fill=NEAR)
    for x, lit in ((150, False), (250, True), (360, False)):                                                # tents
        s += poly([(x, 310), (x + 44, 262), (x + 88, 310)], BLACK) + line(x + 44, 262, x + 44, 252, BLACK, 2)
        if lit:
            s += poly([(x + 34, 310), (x + 44, 284), (x + 54, 310)], AMBER) + glow(x + 44, 298, 60, AMBER, 0.3)
    rng = random.Random(21)
    for _ in range(26):                                                                                     # blown sand
        x, y = rng.randint(-40, 560), rng.randint(40, 340)
        s += line(x, y, x + rng.randint(40, 120), y - 3, AMBER, rng.choice([1, 1.5, 2.5]), 0.16)
    return s


def the_marigold():
    s = stars(22, 20, 110) + rect(0, 268, 600, 107, "#151D29")
    s += poly([(90, 270), (104, 238), (500, 238), (520, 270)], BLACK) + rect(130, 204, 320, 36, BLACK) + rect(160, 176, 240, 30, BLACK)
    s += rect(200, 110, 22, 68, BLACK) + rect(260, 110, 22, 68, BLACK) + rect(197, 110, 28, 8, RED, 0, 0.8) + rect(257, 110, 28, 8, RED, 0, 0.8)
    s += rect(360, 156, 40, 22, BLACK) + rect(368, 162, 10, 10, AMBER, 1)
    s += windows(144, 214, 13, 1, 12, 14, 11, 0, 23, 0.7) + windows(172, 184, 9, 1, 12, 12, 13, 0, 24, 0.6)
    s += circle(462, 250, 34, BLACK) + circle(462, 250, 26, FAR) + circle(462, 250, 5, BLACK)
    s += "".join(line(462, 250, 462 + 26 * c, 250 + 26 * sn, BLACK, 3) for c, sn in ((1, 0), (-1, 0), (0, 1), (0, -1), (0.7, 0.7), (-0.7, 0.7), (0.7, -0.7), (-0.7, -0.7)))
    s += circle(212, 92, 12, PALE, 0.22) + circle(232, 72, 17, PALE, 0.16) + circle(272, 90, 12, PALE, 0.2)
    s += glow(300, 220, 190, AMBER, 0.16) + "".join(rect(150 + i * 46, 276, 20, 30, AMBER, 1, 0.10) for i in range(7))
    for y, op in ((150, 0.10), (200, 0.14), (292, 0.18), (330, 0.2)):                                       # fog
        s += ellipse(300 + (y % 70) - 30, y, 380, 16, PALE, op)
    return s


def the_winter_ring():
    s = stars(25, 35, 150) + moon(110, 80) + poly([(0, 375), (0, 286), (600, 276), (600, 375)], "#222C3B")
    top = [(170, 220), (300, 110), (430, 220)]
    s += poly(top, BLACK) + rect(170, 220, 260, 70, BLACK)
    for i in range(6):                                                                                      # stripes
        x1, x2 = 170 + i * 43.3, 170 + (i + 1) * 43.3
        if i % 2 == 0:
            s += poly([(300, 110), (x1, 220), (x2, 220)], RED, 0.7) + rect(x1, 220, 43.3, 70, RED, 0, 0.55)
    s += rect(288, 244, 24, 46, AMBER, 1) + glow(300, 268, 90, AMBER, 0.3)
    s += line(300, 110, 300, 84, BLACK, 2.5) + poly([(300, 84), (326, 91), (300, 98)], AMBER)
    for x in (60, 470):                                                                                     # wagons
        s += rect(x, 250, 78, 36, BLACK, 4) + path(f"M{x} 252 Q{x + 39} 228 {x + 78} 252 Z", fill=BLACK) + rect(x + 14, 260, 14, 12, AMBER, 1)
        s += circle(x + 16, 290, 9, BLACK) + circle(x + 62, 290, 9, BLACK)
    return s + snow(26, 80)


def the_late_edition():
    s = rect(150, 60, 300, 250, BLACK) + rect(140, 52, 320, 12, BLACK) + rect(268, 20, 64, 34, BLACK)
    s += circle(300, 38, 13, CREAM, 0.9) + line(300, 38, 300, 29, BLACK, 2) + line(300, 38, 306, 40, BLACK, 2)
    s += windows(170, 82, 7, 4, 24, 34, 14, 14, 27, 0.7)
    s += rect(190, 274, 220, 16, AMBER, 1, 0.9) + "".join(rect(200 + i * 14, 279, 9, 6, BLACK) for i in range(15))   # the sign
    s += rect(0, 312, 600, 63, "#222C3B") + rect(284, 290, 32, 24, FAR)
    for x in (70, 520):                                                                                     # street lamps
        s += rect(x, 190, 5, 124, BLACK) + rect(x - 8, 178, 21, 14, AMBER, 2) + glow(x + 2, 186, 62, AMBER, 0.42)
    s += poly([(0, 375), (0, 322), (120, 306), (230, 326), (400, 318), (520, 304), (600, 322), (600, 375)], "#2B3648")
    return s + glow(300, 180, 220, AMBER, 0.12) + snow(28, 110)


def default():
    s = glow(300, 180, 180, AMBER, 0.18) + rect(190, 110, 220, 170, BLACK, 4) + poly([(190, 110), (190, 92), (280, 92), (296, 110)], BLACK)
    s += rect(204, 128, 192, 138, "#E8DFC9", 2, 0.9)
    s += f'<text x="300" y="232" text-anchor="middle" font-family="Georgia, serif" font-size="96" fill="{INK}">?</text>'
    return s


SCENES = {
    "harbour_light": harbour_light, "the_pine_ridge": the_pine_ridge, "the_night_sleeper": the_night_sleeper,
    "the_skerry_light": the_skerry_light, "the_final_curtain": the_final_curtain, "the_aurora_drift": the_aurora_drift,
    "the_flooded_vale": the_flooded_vale, "the_high_dome": the_high_dome, "the_angels_share": the_angels_share,
    "the_last_vintage": the_last_vintage, "the_night_gallery": the_night_gallery, "the_sealed_chamber": the_sealed_chamber,
    "the_marigold": the_marigold, "the_winter_ring": the_winter_ring, "the_late_edition": the_late_edition,
    "default": default,
}

HEADER = f'''<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {W} {H}" width="{W}" height="{H}">
<defs>
<linearGradient id="sky" x1="0" y1="0" x2="0" y2="1"><stop offset="0" stop-color="{NIGHT}"/><stop offset="1" stop-color="{INK}"/></linearGradient>
<radialGradient id="gAmber"><stop offset="0" stop-color="{AMBER}" stop-opacity="1"/><stop offset="1" stop-color="{AMBER}" stop-opacity="0"/></radialGradient>
<radialGradient id="gCream"><stop offset="0" stop-color="{CREAM}" stop-opacity="1"/><stop offset="1" stop-color="{CREAM}" stop-opacity="0"/></radialGradient>
<radialGradient id="gRed"><stop offset="0" stop-color="{RED}" stop-opacity="1"/><stop offset="1" stop-color="{RED}" stop-opacity="0"/></radialGradient>
<clipPath id="frame"><rect width="{W}" height="{H}"/></clipPath>
</defs>
<g clip-path="url(#frame)"><rect width="{W}" height="{H}" fill="url(#sky)"/>
'''


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    for name, scene in SCENES.items():
        (OUT / f"{name}.svg").write_text(HEADER + scene() + "</g></svg>\n", encoding="utf-8")
    print(f"Wrote {len(SCENES)} pictures to {OUT}")


if __name__ == "__main__":
    main()

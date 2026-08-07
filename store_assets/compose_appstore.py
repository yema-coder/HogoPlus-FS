#!/usr/bin/env python3
"""Compose App Store Connect-ready marketing screenshots (1290x2796, 6.7" portrait).

Clean white background, premium iPhone mockup with Dynamic Island status bar,
marketing title on top, one-line description at the bottom.
Brand: blue (#1D4ED8) / white / dark gray (#1F2937). Typography: Baloo 2 (app brand font).
"""
from PIL import Image, ImageDraw, ImageFilter, ImageFont

FONTS = "/app/frontend/assets/fonts"
RAW = "/app/store_assets/raw"
OUT = "/app/store_assets/appstore"

CANVAS = (1290, 2796)
WHITE = (255, 255, 255)
BLUE = (29, 78, 216)        # #1D4ED8
DARK = (31, 41, 55)         # #1F2937
GRAY = (75, 85, 99)         # #4B5563
BEZEL = (17, 19, 24)        # near-black dark gray

SHOTS = [
    ("01_login", "b1_otp.jpeg", "Secure Employee Login",
     "OTP based secure access for authorized staff"),
    ("02_dashboard", "b2_home.jpeg", "Smart Factory Dashboard",
     "Access attendance, incidents and tasks in one place"),
    ("03_attendance", "d1_history_july.jpeg", "Accurate Attendance Tracking",
     "Selfie, GPS, Bluetooth beacon and face verification"),
    ("04_incidents", "b6_incident.jpeg", "Report Incidents in Seconds",
     "Capture photos, voice notes and AI powered reports"),
    ("05_employees", "c3_employees.jpeg", "Employee Information",
     "View profiles, attendance history and roles"),
    ("06_beacons", "b5_blediag.jpeg", "Real Time Beacon Monitoring",
     "Monitor all factory zones with live diagnostics"),
    ("07_management", "b4_approvals.jpeg", "Powerful Management Tools",
     "Monitor attendance, approvals and workforce performance"),
    ("08_ai_assistant", "s5_sahayak.jpeg", "AI Powered Employee Assistance",
     "Get instant help with attendance and workplace queries"),
]


def font(name, size):
    return ImageFont.truetype(f"{FONTS}/{name}.ttf", size)


def fit_font(draw, text, name, size, max_w):
    while size > 20:
        f = font(name, size)
        if draw.textlength(text, font=f) <= max_w:
            return f
        size -= 2
    return font(name, size)


def rounded_mask(size, radius):
    m = Image.new("L", size, 0)
    ImageDraw.Draw(m).rounded_rectangle([0, 0, size[0] - 1, size[1] - 1], radius, fill=255)
    return m


def compose(out_name, shot_file, title, desc):
    canvas = Image.new("RGB", CANVAS, WHITE)
    d = ImageDraw.Draw(canvas)
    W, H = CANVAS

    # ---- top typography ----
    eyebrow = "HOGO PLUS  ·  FACTORY SOLUTIONS"
    f_eye = font("Baloo2-SemiBold", 34)
    # letter-spaced eyebrow
    spaced = " ".join(eyebrow)
    f_eye_use = fit_font(d, spaced, "Baloo2-SemiBold", 34, W - 220)
    ew = d.textlength(spaced, font=f_eye_use)
    d.text(((W - ew) / 2, 128), spaced, font=f_eye_use, fill=BLUE)

    f_title = fit_font(d, title, "Baloo2-Bold", 92, W - 140)
    tw = d.textlength(title, font=f_title)
    d.text(((W - tw) / 2, 196), title, font=f_title, fill=DARK)

    # ---- device geometry ----
    screen_w = 930
    shot = Image.open(f"{RAW}/{shot_file}").convert("RGB")
    sw, sh = shot.size                      # 390x844-ish
    shot_h = round(screen_w * sh / sw)      # ≈2012
    status_h = 100
    screen_h = status_h + shot_h
    bezel = 22
    dev_w, dev_h = screen_w + 2 * bezel, screen_h + 2 * bezel
    dev_x = (W - dev_w) // 2
    dev_y = 400

    # ---- soft shadow ----
    shadow = Image.new("RGBA", CANVAS, (0, 0, 0, 0))
    ImageDraw.Draw(shadow).rounded_rectangle(
        [dev_x + 14, dev_y + 30, dev_x + dev_w + 14, dev_y + dev_h + 30], 110, fill=(15, 23, 42, 70))
    shadow = shadow.filter(ImageFilter.GaussianBlur(38))
    canvas.paste(shadow, (0, 0), shadow)
    d = ImageDraw.Draw(canvas)

    # ---- bezel ----
    d.rounded_rectangle([dev_x, dev_y, dev_x + dev_w, dev_y + dev_h], 110, fill=BEZEL)

    # ---- screen content: status bar + shot, clipped rounded ----
    bg = shot.getpixel((6, 6))              # match the app background color
    screen = Image.new("RGB", (screen_w, screen_h), bg)
    sd = ImageDraw.Draw(screen)
    # status bar: time + glyphs
    f_time = font("Baloo2-SemiBold", 40)
    sd.text((70, 28), "9:41", font=f_time, fill=DARK)
    # signal bars
    bx, by = screen_w - 240, 62
    for i, bh in enumerate((12, 20, 28, 36)):
        sd.rounded_rectangle([bx + i * 16, by - bh, bx + i * 16 + 10, by], 3, fill=DARK)
    # wifi arcs (simple)
    wx, wy = screen_w - 160, 60
    for r, wdt in ((30, 5), (20, 5), (9, 7)):
        sd.arc([wx - r, wy - r, wx + r, wy + r], 220, 320, fill=DARK, width=wdt)
    # battery
    btx, bty = screen_w - 108, 34
    sd.rounded_rectangle([btx, bty, btx + 56, bty + 28], 8, outline=DARK, width=4)
    sd.rounded_rectangle([btx + 60, bty + 8, btx + 66, bty + 20], 2, fill=DARK)
    sd.rounded_rectangle([btx + 5, bty + 5, btx + 45, bty + 23], 4, fill=DARK)
    # app screenshot (high-quality upscale)
    shot_big = shot.resize((screen_w, shot_h), Image.LANCZOS)
    screen.paste(shot_big, (0, status_h))
    # dynamic island
    isl_w, isl_h = 280, 66
    sd = ImageDraw.Draw(screen)
    sd.rounded_rectangle([(screen_w - isl_w) // 2, 22, (screen_w + isl_w) // 2, 22 + isl_h],
                         isl_h // 2, fill=(10, 10, 12))
    # lens dot inside island
    lx = (screen_w + isl_w) // 2 - 52
    sd.ellipse([lx, 40, lx + 30, 70], fill=(28, 30, 38))
    sd.ellipse([lx + 8, 48, lx + 22, 62], fill=(52, 58, 92))

    mask = rounded_mask((screen_w, screen_h), 88)
    canvas.paste(screen, (dev_x + bezel, dev_y + bezel), mask)
    d = ImageDraw.Draw(canvas)

    # ---- bottom description ----
    f_desc = fit_font(d, desc, "Baloo2-Medium", 46, W - 160)
    dw = d.textlength(desc, font=f_desc)
    dy = dev_y + dev_h + 66
    d.text(((W - dw) / 2, dy), desc, font=f_desc, fill=GRAY)
    # blue underline accent
    d.rounded_rectangle([(W - 120) / 2, dy + 92, (W + 120) / 2, dy + 100], 4, fill=BLUE)

    canvas.save(f"{OUT}/{out_name}.png", "PNG")
    print(f"{out_name}.png  {CANVAS[0]}x{CANVAS[1]}")


import os
os.makedirs(OUT, exist_ok=True)
for row in SHOTS:
    compose(*row)
print("ALL DONE")

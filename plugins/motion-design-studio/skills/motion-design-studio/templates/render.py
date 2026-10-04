#!/usr/bin/env python3
"""Deterministic frame-by-frame renderer for a seek(t) composition.

Opens index.html?render=1 in Chromium, calls window.seek(t) for every
frame, waits two animation frames, screenshots, and pipes the frames
into FFmpeg. Composition size, fps, duration and cuts come from
window.__MOTION__.

    python render.py probe 1.2 5.0 9.5 14.2      # stills + contact sheet
    python render.py draft                        # out/draft.mp4
    python render.py master                       # out/master.mp4
    python render.py master --blur 4              # 4 sub-frames, 180° shutter
    python render.py master --size 1080x1920 -o out/master-vertical.mp4
    python render.py loop                         # seam check

Requires: pip install playwright pillow numpy; playwright install chromium;
ffmpeg on PATH. Set CHROMIUM_PATH to use an existing Chromium build.
"""
import argparse
import io
import os
import shutil
import subprocess
import sys
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw
from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parent
PAGE = ROOT / "index.html"


class Movie:
    """A Chromium page showing the composition at a given viewport size."""

    def __init__(self, pw, size=None):
        # CHROMIUM_PATH points at a specific Chromium build when the one
        # matching the installed Playwright version is not available.
        self.browser = pw.chromium.launch(executable_path=os.environ.get("CHROMIUM_PATH") or None)
        # Read the contract at master size first, then resize if needed.
        self.page = self.browser.new_page(viewport={"width": 1920, "height": 1080}, device_scale_factor=1)
        self.page.goto(PAGE.as_uri() + "?render=1")
        self.page.evaluate("document.fonts.ready")
        self.meta = self.page.evaluate("window.__MOTION__")
        w, h = size or (self.meta["width"], self.meta["height"])
        self.page.set_viewport_size({"width": w, "height": h})
        self.size = (w, h)

    def frame(self, t):
        self.page.evaluate(
            """async (t) => {
                await document.fonts.ready;
                window.seek(t);
                await new Promise(r => requestAnimationFrame(() => requestAnimationFrame(r)));
            }""",
            t,
        )
        return self.page.screenshot(type="png")

    def array(self, t):
        return np.asarray(Image.open(io.BytesIO(self.frame(t))).convert("RGB"), dtype=np.float32)

    def close(self):
        self.browser.close()


def parse_size(s):
    w, h = s.lower().split("x")
    return int(w), int(h)


def segment_end(t, cuts, duration):
    """End of the shot containing t, so blur never crosses a hard cut."""
    later = [c for c in cuts if c > t]
    return min(later) if later else duration


def encode(movie, out, fps, crf, preset, blur):
    if not shutil.which("ffmpeg"):
        sys.exit("ffmpeg not found on PATH")
    meta = movie.meta
    duration, cuts = meta["duration"], meta.get("cuts", [])
    n = round(duration * fps)
    out.parent.mkdir(parents=True, exist_ok=True)
    ff = subprocess.Popen(
        ["ffmpeg", "-y", "-loglevel", "error",
         "-f", "image2pipe", "-framerate", str(fps), "-i", "-",
         "-c:v", "libx264", "-preset", preset, "-crf", str(crf),
         "-pix_fmt", "yuv420p", "-movflags", "+faststart", str(out)],
        stdin=subprocess.PIPE,
    )
    shutter = 0.5  # 180°
    for i in range(n):
        t = i / fps
        if blur > 1:
            end = segment_end(t, cuts, duration)
            span = min(shutter / fps, end - t - 1e-6)
            acc = sum(movie.array(t + span * k / blur) for k in range(blur)) / blur
            buf = io.BytesIO()
            Image.fromarray(np.clip(acc + 0.5, 0, 255).astype(np.uint8)).save(buf, "PNG")
            ff.stdin.write(buf.getvalue())
        else:
            ff.stdin.write(movie.frame(t))
        if i % max(1, fps) == 0:
            print(f"\r{i + 1}/{n} frames", end="", flush=True)
    ff.stdin.close()
    if ff.wait() != 0:
        sys.exit("ffmpeg failed")
    print(f"\r{n}/{n} frames -> {out}")


def contact_sheet(paths, times, out, cols=2):
    thumbs = [Image.open(p).convert("RGB") for p in paths]
    tw = 640
    th = round(thumbs[0].height * tw / thumbs[0].width)
    rows = -(-len(thumbs) // cols)
    pad, label = 16, 28
    sheet = Image.new("RGB", (cols * (tw + pad) + pad, rows * (th + label + pad) + pad), (24, 24, 24))
    draw = ImageDraw.Draw(sheet)
    for i, (img, t) in enumerate(zip(thumbs, times)):
        x = pad + (i % cols) * (tw + pad)
        y = pad + (i // cols) * (th + label + pad)
        sheet.paste(img.resize((tw, th), Image.LANCZOS), (x, y + label))
        draw.text((x, y + 6), f"{i + 1:02d}  t = {t:.2f} s", fill=(220, 220, 220))
    sheet.save(out)


def cmd_probe(movie, args):
    d = movie.meta["duration"]
    times = args.times or [d * f for f in (0.08, 0.33, 0.63, 0.95)]
    probe = ROOT / "probe"
    probe.mkdir(exist_ok=True)
    paths = []
    for i, t in enumerate(times, 1):
        p = probe / f"{i:02d}-t{t:05.2f}.png"
        p.write_bytes(movie.frame(t))
        paths.append(p)
        print(p.relative_to(ROOT))
    contact_sheet(paths, times, probe / "contact-sheet.png")
    print("probe/contact-sheet.png")


def cmd_loop(movie, args):
    m = movie.meta
    d, dt = m["duration"], 1 / m["fps"]
    first, last = movie.array(0), movie.array(d)
    v_start = movie.array(dt) - first
    v_end = last - movie.array(d - dt)
    pos = float(np.abs(first - last).mean())
    vel = float(np.abs(v_start - v_end).mean())
    print(f"position seam: {pos:.2f} / 255 mean abs diff")
    print(f"velocity seam: {vel:.2f} / 255 mean abs diff of frame deltas")
    ok = pos < 1.0 and vel < 1.0
    print("loop OK" if ok else "loop seam visible: match position AND velocity at t=0 and t=duration")
    return 0 if ok else 1


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("probe", help="capture still frames and a contact sheet")
    p.add_argument("times", nargs="*", type=float)
    p.add_argument("--size", type=parse_size)
    for name in ("draft", "master"):
        p = sub.add_parser(name)
        p.add_argument("--size", type=parse_size)
        p.add_argument("--fps", type=int)
        p.add_argument("--crf", type=int)
        p.add_argument("--blur", type=int, default=1, help="sub-frames per frame (master only)")
        p.add_argument("-o", "--out", type=Path)
    p = sub.add_parser("loop", help="check the seam between first and last frame")
    p.add_argument("--size", type=parse_size)
    args = ap.parse_args()

    with sync_playwright() as pw:
        size = args.size
        if args.cmd == "draft" and not size:
            size = (960, 540)
        movie = Movie(pw, size)
        try:
            if args.cmd == "probe":
                cmd_probe(movie, args)
            elif args.cmd == "loop":
                return cmd_loop(movie, args)
            elif args.cmd == "draft":
                encode(movie, args.out or ROOT / "out/draft.mp4", args.fps or 30,
                       args.crf or 23, "veryfast", 1)
            else:
                encode(movie, args.out or ROOT / "out/master.mp4", args.fps or movie.meta["fps"],
                       args.crf or 18, "slow", max(1, args.blur))
        finally:
            movie.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())

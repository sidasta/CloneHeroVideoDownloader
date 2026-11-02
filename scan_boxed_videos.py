#!/usr/bin/env python3
"""
Find already-converted video.webm files whose picture is boxed in on all four
sides: pillarboxed by the downloader's 16:9 padding AND letterboxed by black
bars that were already burned into the YouTube upload (e.g. a 2.35:1 film
inside a 4:3 video). Videos downloaded since burned-in bar cropping was added
shouldn't show this; re-download the flagged ones to fix them.

Usage:
    python scan_boxed_videos.py <songs_folder> [--min-bar 0.05] [--workers 4]
"""
import argparse
import re
import subprocess
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

HERE = Path(__file__).resolve().parent
FFMPEG = str(HERE / "bin" / "ffmpeg.exe") if (HERE / "bin" / "ffmpeg.exe").exists() else "ffmpeg"
FFPROBE = str(HERE / "bin" / "ffprobe.exe") if (HERE / "bin" / "ffprobe.exe").exists() else "ffprobe"
NO_WINDOW = {"creationflags": subprocess.CREATE_NO_WINDOW} if sys.platform == "win32" else {}
SAMPLES = 8


def picture_box(video: Path):
    """(frame_w, frame_h, x1, y1, x2, y2) of everything any sample saw as
    picture, or None if the video can't be read."""
    probe = subprocess.run([FFPROBE, "-v", "error", "-select_streams", "v:0",
                            "-show_entries", "stream=width,height:format=duration",
                            "-of", "default=noprint_wrappers=1", str(video)],
                           capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=30, **NO_WINDOW)
    info = dict(line.split("=", 1) for line in probe.stdout.splitlines() if "=" in line)
    try:
        w, h, duration = int(info["width"]), int(info["height"]), float(info["duration"])
    except (KeyError, ValueError):
        return None

    start, end = min(5.0, duration * 0.1), max(0.0, duration - min(5.0, duration * 0.1) - 2)
    boxes = []
    for n in range(SAMPLES):
        t = start + (end - start) * n / (SAMPLES - 1)
        result = subprocess.run([FFMPEG, "-hide_banner", "-ss", f"{t:.2f}", "-i", str(video),
                                 "-t", "2", "-an", "-vf", "cropdetect=limit=24:round=2:reset=0",
                                 "-f", "null", "-"],
                                capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=120, **NO_WINDOW)
        found = re.findall(r"crop=(-?\d+):(-?\d+):(-?\d+):(-?\d+)", result.stderr)
        if found:
            cw, ch, cx, cy = map(int, found[-1])
            if cw > w * 0.1 and ch > h * 0.1:  # ignore all-black clips
                boxes.append((cx, cy, cx + cw, cy + ch))
    if len(boxes) < 2:
        return None
    return (w, h, min(b[0] for b in boxes), min(b[1] for b in boxes),
            max(b[2] for b in boxes), max(b[3] for b in boxes))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("root", type=Path)
    ap.add_argument("--min-bar", type=float, default=0.05,
                    help="flag when the bars on BOTH axes take up at least this fraction of the frame")
    ap.add_argument("--workers", type=int, default=4)
    args = ap.parse_args()

    # Skip a video the downloader may still be writing
    videos = sorted(p for p in args.root.glob("*/video.webm")
                    if time.time() - p.stat().st_mtime > 120)
    print(f"Scanning {len(videos)} videos in {args.root} ...\n")

    flagged, unreadable = [], []

    def scan(video):
        try:
            return video, picture_box(video)
        except Exception:
            return video, None

    with ThreadPoolExecutor(args.workers) as pool:
        for i, (video, box) in enumerate(pool.map(scan, videos), 1):
            if box is None:
                unreadable.append(video.parent.name)
                continue
            w, h, x1, y1, x2, y2 = box
            pic_w, pic_h = x2 - x1, y2 - y1
            if (w - pic_w) >= w * args.min_bar and (h - pic_h) >= h * args.min_bar:
                flagged.append((video.parent.name, w, h, pic_w, pic_h))
                print(f"[{i}/{len(videos)}] BOXED  {video.parent.name}  "
                      f"(picture {pic_w}x{pic_h} in {w}x{h})")

    flagged.sort(key=lambda f: (f[3] * f[4]) / (f[1] * f[2]))
    print(f"\n{len(flagged)} of {len(videos)} videos are boxed in on all four sides"
          f" (smallest picture first):")
    for name, w, h, pic_w, pic_h in flagged:
        print(f"  - {name}  picture {pic_w}x{pic_h} = {pic_w * pic_h / (w * h):.0%} of the screen")
    if unreadable:
        print(f"\nCouldn't analyse {len(unreadable)} video(s):")
        for name in unreadable:
            print(f"  - {name}")


if __name__ == "__main__":
    main()

#!/usr/bin/env python3
"""Cache control + measurable stats for a taste style.

  taste_cache.py status <taste/STYLE>   fresh | stale (and which videos changed)
  taste_cache.py stats  <taste/STYLE>   aggregate profile/index/*/index.json
                                        -> profile/style.stats.json
  taste_cache.py commit <taste/STYLE>   write profile/manifest.json (marks it fresh)

Layout:  taste/STYLE/videos/*            reference videos (gitignored)
         taste/STYLE/profile/index/…     per-video index (index_clip.py, no proxy)
         taste/STYLE/profile/style.md    the readable profile (edit it freely)
         taste/STYLE/profile/style.json  numbers the skills read
"""
from __future__ import annotations

import argparse
import hashlib
import statistics
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from omc_common import load_json, save_json  # noqa: E402

VIDEO_EXT = {".mp4", ".mov", ".mkv", ".webm", ".m4v"}
CHUNK = 4 * 1024 * 1024


def fingerprint(p: Path) -> str:
    h, size = hashlib.sha256(), p.stat().st_size
    with p.open("rb") as f:
        h.update(f.read(CHUNK))
        if size > 2 * CHUNK:
            f.seek(-CHUNK, 2)
            h.update(f.read(CHUNK))
    return f"{size}:{h.hexdigest()[:16]}"


def current(style: Path) -> dict:
    vids = sorted(p for p in (style / "videos").glob("*") if p.suffix.lower() in VIDEO_EXT)
    return {p.name: fingerprint(p) for p in vids}


def do_status(style: Path) -> int:
    now = current(style)
    mpath = style / "profile" / "manifest.json"
    old = load_json(mpath)["videos"] if mpath.exists() else {}
    added = [k for k in now if k not in old]
    changed = [k for k in now if k in old and old[k] != now[k]]
    removed = [k for k in old if k not in now]
    have_profile = (style / "profile" / "style.json").exists()
    if not now:
        print(f"empty: {style}/videos 沒有影片")
        return 3
    if have_profile and not (added or changed or removed):
        print(f"fresh: {len(now)} 支影片，profile 可直接使用")
        return 0
    print(f"stale: 新增 {added or '-'}；變更 {changed or '-'}；移除 {removed or '-'}"
          + ("" if have_profile else "；尚無 style.json"))
    return 1


def do_stats(style: Path):
    rows = [load_json(p) for p in sorted((style / "profile" / "index").glob("*/index.json"))]
    if not rows:
        raise SystemExit("沒有 index：先對 videos/ 跑 index_clip.py")

    def col(path):
        vals = []
        for r in rows:
            v = r
            for k in path:
                v = (v or {}).get(k)
            if isinstance(v, (int, float)):
                vals.append(v)
        return vals

    def mid(path, nd=2):
        v = col(path)
        return round(statistics.median(v), nd) if v else None

    stats = {
        "videos": len(rows),
        "duration_median_s": mid(["meta", "duration"], 0),
        "pacing": {"shot_len_median_s": mid(["shots", "median_len"]),
                   "shot_len_p25_s": mid(["shots", "p25_len"]),
                   "shot_len_p75_s": mid(["shots", "p75_len"]),
                   "cuts_per_min": mid(["shots", "cuts_per_min"], 1),
                   "cuts_first_30s": mid(["shots", "cuts_first_30s"], 0)},
        "audio": {"lufs": mid(["audio", "lufs"], 1),
                  "speech_ratio": mid(["audio", "speech_ratio"])},
        "speech": {"chars_per_min": mid(["transcript", "chars_per_min"], 0)},
        "color": {"brightness_yavg": mid(["color", "brightness_yavg"], 1),
                  "saturation_avg": mid(["color", "saturation_avg"], 1),
                  "black_ylow": mid(["color", "black_ylow"], 1),
                  "white_yhigh": mid(["color", "white_yhigh"], 1)},
        "per_video": [{"name": Path(r["src"]).name, "duration": r["meta"]["duration"],
                       "shot_len_median_s": (r.get("shots") or {}).get("median_len"),
                       "cuts_per_min": (r.get("shots") or {}).get("cuts_per_min"),
                       "lufs": (r.get("audio") or {}).get("lufs")} for r in rows],
        "note": "Measured from the references. Caption look, motion and structure are "
                "judged from the contact sheets and written to style.md / style.json.",
    }
    out = style / "profile" / "style.stats.json"
    save_json(out, stats)
    p = stats["pacing"]
    print(f"stats → {out}: {len(rows)} videos, median shot {p['shot_len_median_s']}s, "
          f"{p['cuts_per_min']} cuts/min, {stats['audio']['lufs']} LUFS")


def do_commit(style: Path):
    save_json(style / "profile" / "manifest.json", {"videos": current(style)})
    print("manifest written — profile marked fresh")


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawTextHelpFormatter)
    ap.add_argument("cmd", choices=["status", "stats", "commit"])
    ap.add_argument("style_dir")
    a = ap.parse_args()
    style = Path(a.style_dir)
    if a.cmd == "status":
        sys.exit(do_status(style))
    {"stats": do_stats, "commit": do_commit}[a.cmd](style)


if __name__ == "__main__":
    main()

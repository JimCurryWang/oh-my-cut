#!/usr/bin/env python3
"""Shared helpers for Oh-my-cut scripts. Standard library only."""
from __future__ import annotations

import json
import re
import subprocess
import sys
from fractions import Fraction
from pathlib import Path


# ---------- json ----------
def load_json(p):
    return json.loads(Path(p).read_text(encoding="utf-8"))


def save_json(p, obj):
    p = Path(p)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(obj, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


# ---------- processes ----------
def run(cmd, check=True):
    cmd = [str(c) for c in cmd]
    r = subprocess.run(cmd, text=True, capture_output=True, errors="replace")
    if check and r.returncode != 0:
        sys.stderr.write(r.stderr[-3000:] + "\n")
        raise SystemExit("command failed: " + " ".join(cmd[:8]) + " ...")
    return r


# ---------- time ----------
def fps_of(cut) -> Fraction:
    n, d = cut.get("fps", [30, 1])
    return Fraction(int(n), int(d))


def frames(sec, fps: Fraction) -> int:
    """Seconds -> nearest frame number on the timeline grid."""
    return int(round(Fraction(str(sec)) * fps))


def secs(fr, fps: Fraction) -> float:
    return round(float(Fraction(fr) / fps), 4)


def tc(sec: float) -> str:
    m, s = divmod(max(0.0, float(sec)), 60)
    return f"{int(m):02d}:{s:05.2f}"


# ---------- media ----------
def probe(path) -> dict:
    """ffprobe summary. Width/height are post-rotation (what you actually see)."""
    r = run(["ffprobe", "-v", "error", "-print_format", "json",
             "-show_format", "-show_streams", path])
    j = json.loads(r.stdout or "{}")
    fmt = j.get("format", {})
    info = {"path": str(path), "duration": float(fmt.get("duration") or 0.0),
            "has_video": False, "has_audio": False, "timecode": None}
    tcode = (fmt.get("tags") or {}).get("timecode")
    for s in j.get("streams", []):
        tags = s.get("tags") or {}
        tcode = tcode or tags.get("timecode")
        if s.get("codec_type") == "video" and not info["has_video"]:
            if (s.get("disposition") or {}).get("attached_pic"):
                continue
            rate = s.get("r_frame_rate") or s.get("avg_frame_rate") or "30/1"
            n, d = (rate.split("/") + ["1"])[:2]
            fps = Fraction(int(n), int(d) or 1) if int(n) else Fraction(30)
            w, h = int(s.get("width", 0)), int(s.get("height", 0))
            rot = 0
            for sd in s.get("side_data_list") or []:
                if "rotation" in sd:
                    rot = int(float(sd["rotation"]))
            if "rotate" in tags:
                rot = int(float(tags["rotate"]))
            if abs(rot) % 180 == 90:
                w, h = h, w
            info.update(has_video=True, width=w, height=h,
                        fps=[fps.numerator, fps.denominator],
                        vfr=(s.get("avg_frame_rate") not in (None, "0/0", rate)),
                        codec=s.get("codec_name"),
                        hdr=s.get("color_transfer") in ("arib-std-b67", "smpte2084"))
        elif s.get("codec_type") == "audio" and not info["has_audio"]:
            info.update(has_audio=True, audio_rate=int(s.get("sample_rate") or 48000),
                        audio_channels=int(s.get("channels") or 2))
    info["timecode"] = tcode
    return info


def resolve(ep: Path, src: str, proxy: bool = True) -> Path:
    """Path of a cut.json `src` (relative to the episode dir). Prefers the proxy."""
    p = Path(src)
    full = p if p.is_absolute() else (ep / p)
    if proxy:
        px = ep / "work" / "proxies" / (p.stem + ".mp4")
        if px.exists():
            return px
    return full


# ---------- cut.json ----------
def layout(cut):
    """[(item, start_frame, dur_frames)] for the spine, plus total frames."""
    fps = fps_of(cut)
    t, out = 0, []
    for c in cut.get("spine", []):
        if "gap" in c:
            d = frames(c["gap"], fps)
        else:
            d = frames(c["out"], fps) - frames(c["in"], fps)
        if d <= 0:
            raise SystemExit(f"clip {c.get('id')!r}: duration must be positive")
        out.append((c, t, d))
        t += d
    return out, t


def validate(cut, ep: Path | None = None):
    """Return a list of problems (empty list = ok)."""
    problems, seen = [], set()
    for kind in ("spine", "overlays", "audio"):
        for c in cut.get(kind, []):
            cid = c.get("id")
            if not cid:
                problems.append(f"{kind}: item without id")
            elif cid in seen:
                problems.append(f"duplicate id {cid}")
            seen.add(cid)
            if "gap" in c:
                continue
            if "src" not in c or "in" not in c or "out" not in c:
                problems.append(f"{cid}: needs src/in/out")
                continue
            if c["out"] <= c["in"]:
                problems.append(f"{cid}: out <= in")
            if kind != "spine" and "at" not in c:
                problems.append(f"{cid}: needs 'at' (timeline seconds)")
            if ep is not None and not resolve(ep, c["src"], proxy=False).exists() \
                    and not resolve(ep, c["src"]).exists():
                problems.append(f"{cid}: file not found: {c['src']}")
    return problems


ID_IN_NAME = re.compile(r"\[([^\[\]]+)\]\s*$")

#!/usr/bin/env python3
"""Shared helpers for Oh-my-cut scripts. Standard library only."""
from __future__ import annotations

import functools
import json
import os
import re
import shutil
import subprocess
import sys
from fractions import Fraction
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


# ---------- json ----------
def load_json(p):
    return json.loads(Path(p).read_text(encoding="utf-8"))


def save_json(p, obj):
    p = Path(p)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(obj, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


# ---------- processes ----------
FFMPEG_FULL_DIRS = ("/opt/homebrew/opt/ffmpeg-full/bin", "/usr/local/opt/ffmpeg-full/bin")


@functools.lru_cache(maxsize=None)
def tool(name: str) -> str:
    """Path of ffmpeg / ffprobe. Order: $OMC_FFMPEG / $OMC_FFPROBE, .omc/env.json
    (written by preflight.sh), Homebrew's keg-only ffmpeg-full (has drawtext), PATH."""
    cand = [os.environ.get("OMC_" + name.upper())]
    env = ROOT / ".omc" / "env.json"
    if env.exists():
        try:
            cand.append(json.loads(env.read_text(encoding="utf-8")).get(name))
        except ValueError:
            pass
    cand += [f"{d}/{name}" for d in FFMPEG_FULL_DIRS]
    for c in cand:
        if c and Path(c).is_file() and os.access(c, os.X_OK):
            return c
    return shutil.which(name) or name


def run(cmd, check=True):
    cmd = [str(c) for c in cmd]
    if cmd and cmd[0] in ("ffmpeg", "ffprobe"):
        cmd[0] = tool(cmd[0])
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
    """ffprobe summary. Width/height are post-rotation (what you actually see).
    Cached per (path, size, mtime); returns a copy so callers may modify it."""
    st = Path(path).stat()
    return dict(_probe(str(path), st.st_size, st.st_mtime_ns))


@functools.lru_cache(maxsize=None)
def _probe(path: str, _size: int, _mtime: int) -> dict:
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
            vd = s.get("duration")
            info.update(has_video=True, width=w, height=h,
                        video_duration=float(vd) if vd not in (None, "N/A") else None,
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


def find_episode(path) -> Path | None:
    """The episode dir (the nearest ancestor holding episode.json) of a cut.json."""
    for d in Path(path).resolve().parents:
        if (d / "episode.json").exists():
            return d
    return None


def validate(cut, ep: Path | None = None, media: bool = True):
    """Return a list of problems (empty list = ok).

    With `ep`, source files must exist, and (media=True) every clip must lie inside
    its source: in >= 0 and out <= source duration (+1 frame of slack). A clip that
    runs past the end of its file would render short and shift everything after it."""
    problems, seen = [], set()
    fps = fps_of(cut)
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
            if c["in"] < 0:
                problems.append(f"{cid}: in < 0")
            parts = Path(os.path.normpath(str(c["src"]))).parts
            if "references" in parts or "taste" in parts:
                problems.append(f"{cid}: 參考影片只能分析，不可以進剪輯：{c['src']}")
            if ep is None:
                continue
            orig, px = resolve(ep, c["src"], proxy=False), resolve(ep, c["src"])
            if not orig.exists() and not px.exists():
                problems.append(f"{cid}: file not found: {c['src']}")
                continue
            if media:
                dur = probe(orig if orig.exists() else px)["duration"]
                if dur and c["out"] > dur + float(1 / fps):
                    problems.append(f"{cid}: out {c['out']:.3f} 超過素材長度 {dur:.3f}"
                                    f"（{Path(c['src']).name}）→ out 最多 {dur:.3f}")
    return problems


ID_IN_NAME = re.compile(r"\[([^\[\]]+)\]\s*$")

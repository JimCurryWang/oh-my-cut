#!/usr/bin/env python3
"""Turn one video into something Claude can read.

  index_clip.py <media> --out <index_root> [--proxy-dir DIR] [options]
  index_clip.py --build-map <index_root> -o footage_map.md

Per clip it writes <index_root>/<stem>/:
  index.json      meta, shot cuts + stats, silences, loudness, colour stats
  sheet_NN.jpg    contact sheets (timestamp burned in when ffmpeg has drawtext)
  transcript.json word-level transcript (Traditional Chinese when opencc is present)
  transcript.txt  compact "[start-end] text" lines -- read this, not the json
The indexer agent adds summary.md (line 1 = one-line summary). Cached: re-running
on an unchanged file is a no-op unless --force.
"""
from __future__ import annotations

import argparse
import math
import re
import shutil
import statistics
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from omc_common import load_json, probe, run, save_json, tc, tool  # noqa: E402

DEFAULT_MODEL = "mlx-community/whisper-large-v3-turbo"
DEFAULT_PROMPT = "以下是繁體中文的旅遊與生活 vlog 口白。"


def fingerprint(p: Path) -> str:
    st = p.stat()
    return f"{st.st_size}:{int(st.st_mtime)}"


def has_filter(name: str) -> bool:
    return f" {name} " in run(["ffmpeg", "-hide_banner", "-filters"]).stdout


def has_encoder(name: str) -> bool:
    return name in run(["ffmpeg", "-hide_banner", "-encoders"]).stdout


def make_proxy(src: Path, dst: Path, fps: int, meta: dict):
    dst.parent.mkdir(parents=True, exist_ok=True)
    venc = (["-c:v", "h264_videotoolbox", "-b:v", "4M"] if has_encoder("h264_videotoolbox")
            else ["-c:v", "libx264", "-preset", "veryfast", "-crf", "23"])
    cmd = ["ffmpeg", "-y", "-v", "error", "-i", src,
           "-vf", f"scale=-2:720,fps={fps},setsar=1", "-pix_fmt", "yuv420p", *venc]
    cmd += (["-c:a", "aac", "-b:a", "128k", "-ar", "48000", "-ac", "2"]
            if meta.get("has_audio") else ["-an"])
    run(cmd + ["-movflags", "+faststart", dst])


def audio_pass(src: Path, duration: float) -> dict:
    r = run(["ffmpeg", "-hide_banner", "-nostats", "-i", src, "-vn",
             "-af", "silencedetect=noise=-35dB:d=0.35,ebur128", "-f", "null", "-"], check=False)
    log = r.stderr
    starts = [float(x) for x in re.findall(r"silence_start: (-?[\d.]+)", log)]
    ends = [float(x) for x in re.findall(r"silence_end: (-?[\d.]+)", log)]
    if len(starts) > len(ends):
        ends.append(duration)
    sil = [[round(max(0, s), 2), round(e, 2)] for s, e in zip(starts, ends)]
    lufs = re.findall(r"I:\s+(-?[\d.]+) LUFS", log)
    silent = sum(e - s for s, e in sil)
    return {"lufs": float(lufs[-1]) if lufs else None, "silences": sil,
            "speech_ratio": round(1 - silent / duration, 3) if duration else None}


def shot_pass(src: Path, duration: float, threshold: float) -> dict:
    r = run(["ffmpeg", "-hide_banner", "-nostats", "-i", src, "-an",
             "-vf", f"fps=10,scale=320:-2,select='gt(scene,{threshold})',showinfo",
             "-f", "null", "-"], check=False)
    cuts = sorted({round(float(x), 2) for x in re.findall(r"pts_time:([\d.]+)", r.stderr)})
    edges = [0.0] + cuts + [duration]
    lens = [round(b - a, 2) for a, b in zip(edges, edges[1:]) if b - a > 0.05]
    q = statistics.quantiles(lens, n=4) if len(lens) >= 4 else None
    first30 = len([c for c in cuts if c <= 30])
    return {"cuts": cuts, "count": len(lens),
            "median_len": round(statistics.median(lens), 2) if lens else None,
            "p25_len": round(q[0], 2) if q else None, "p75_len": round(q[2], 2) if q else None,
            "cuts_per_min": round(len(cuts) / duration * 60, 1) if duration else None,
            "cuts_first_30s": first30}


def color_pass(src: Path) -> dict:
    r = run(["ffmpeg", "-hide_banner", "-nostats", "-i", src, "-an",
             "-vf", "fps=1,scale=320:-2,signalstats,metadata=print:file=-",
             "-f", "null", "-"], check=False)

    def avg(key):
        v = [float(x) for x in re.findall(rf"signalstats\.{key}=([\d.]+)", r.stdout)]
        return round(sum(v) / len(v), 1) if v else None
    return {"brightness_yavg": avg("YAVG"), "saturation_avg": avg("SATAVG"),
            "black_ylow": avg("YLOW"), "white_yhigh": avg("YHIGH")}


def sheets(src: Path, out: Path, duration: float) -> dict:
    for old in out.glob("sheet_*.jpg"):
        old.unlink()
    interval = max(2, math.ceil(duration / 40))
    base = f"fps=1/{interval},scale=320:-2"
    stamp = ("drawtext=text='%{pts\\:hms}':x=6:y=6:fontsize=18:fontcolor=white:"
             "box=1:boxcolor=black@0.6")
    tried = [f"{base},{stamp},tile=5x4", f"{base},tile=5x4"] if has_filter("drawtext") \
        else [f"{base},tile=5x4"]
    stamped = False
    for i, vf in enumerate(tried):
        r = run(["ffmpeg", "-y", "-v", "error", "-i", src, "-an", "-vf", vf,
                 "-q:v", "4", out / "sheet_%02d.jpg"], check=False)
        if r.returncode == 0 and list(out.glob("sheet_*.jpg")):
            stamped = (i == 0 and len(tried) == 2)
            break
    files = sorted(p.name for p in out.glob("sheet_*.jpg"))
    return {"interval_s": interval, "per_sheet": 20, "timestamps_burned": stamped, "files": files,
            "note": "frame k (0-based, row-major across sheets) is at k * interval_s seconds"}


def to_traditional():
    """Simplified -> Traditional (Taiwan glyphs) WITHOUT swapping vocabulary: s2tw, not
    s2twp. The speaker is Taiwanese; whatever words they said stay as said. Only
    matters when Whisper drifts into Simplified; Traditional input passes unchanged."""
    try:
        from opencc import OpenCC
        return OpenCC("s2tw").convert
    except Exception:
        return None


def convert_words(words, conv):
    """Convert a segment's words with the whole segment as context, then hand each word
    its slice back. Single characters are ambiguous (发 -> 發/髮, 面 -> 面/麵, 干 -> 乾/幹);
    only the surrounding phrase decides. s2tw maps character for character, so the
    lengths line up; if they ever don't, fall back to word by word."""
    raw = [w["w"] for w in words]
    joined = "".join(raw)
    out = conv(joined)
    if len(out) != len(joined):
        return [conv(x) for x in raw]
    pieces, i = [], 0
    for x in raw:
        pieces.append(out[i:i + len(x)])
        i += len(x)
    return pieces


def load_glossary(path: Path | None):
    pairs = []
    if path and path.exists():
        for line in path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line and not line.startswith("#") and "→" in line:
                a, b = line.split("→", 1)
                pairs.append((a.strip(), b.strip()))
    return pairs


def transcribe(src: Path, lang: str, model: str, prompt: str):
    try:
        import mlx_whisper
    except ImportError:
        return None
    r = mlx_whisper.transcribe(str(src), path_or_hf_repo=model, language=lang,
                               word_timestamps=True, initial_prompt=prompt)
    return [{"start": s["start"], "end": s["end"], "text": s["text"],
             "words": [{"w": w["word"], "start": w["start"], "end": w["end"]}
                       for w in s.get("words", [])]} for s in r.get("segments", [])]


def write_transcript(out: Path, segments, lang, engine, duration, glossary):
    conv = to_traditional() if lang.startswith("zh") else None
    fix = (lambda s: s)
    if conv:
        fix = conv
    clean = []
    for s in segments:
        text = fix(s["text"]).strip()
        for a, b in glossary:
            text = text.replace(a, b)
        ws = [w for w in s.get("words", []) if w["w"].strip()]
        texts = convert_words(ws, conv) if conv else [w["w"] for w in ws]
        words = [{"w": t.strip(), "start": round(float(w["start"]), 3),
                  "end": round(float(w["end"]), 3)} for w, t in zip(ws, texts)]
        clean.append({"start": round(float(s["start"]), 3), "end": round(float(s["end"]), 3),
                      "text": text, "words": words})
    save_json(out / "transcript.json", {"language": lang, "engine": engine,
                                        "traditional": bool(conv), "segments": clean})
    (out / "transcript.txt").write_text(
        "".join(f"[{s['start']:07.2f}-{s['end']:07.2f}] {s['text']}\n" for s in clean),
        encoding="utf-8")
    chars = sum(len(re.sub(r"\s", "", s["text"])) for s in clean)
    return {"available": True, "engine": engine, "traditional": bool(conv), "chars": chars,
            "chars_per_min": round(chars / duration * 60) if duration else None}


def build_map(root: Path, out: Path):
    rows = []
    for idx in sorted(root.glob("*/index.json")):
        j = load_json(idx)
        summ = idx.with_name("summary.md")
        line = summ.read_text(encoding="utf-8").strip().splitlines()[0] if summ.exists() \
            and summ.read_text(encoding="utf-8").strip() else "（尚無摘要）"
        m, a, t = j["meta"], j.get("audio") or {}, j.get("transcript") or {}
        speech = "口白" if t.get("chars", 0) > 20 else "無口白"
        rows.append(f"| {idx.parent.name} | {tc(m['duration'])} | "
                    f"{m.get('width', '-')}x{m.get('height', '-')} | {speech} | "
                    f"{(j.get('shots') or {}).get('count', '-')} | {line.lstrip('# ').strip()} |")
    body = ("# Footage map\n\n主對話只讀這份。需要細節時才去讀 "
            "`work/index/<clip>/summary.md` 或 `transcript.txt`。\n\n"
            "| clip | 長度 | 尺寸 | 聲音 | 鏡頭數 | 摘要 |\n|---|---|---|---|---|---|\n"
            + "\n".join(rows) + "\n")
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(body, encoding="utf-8")
    print(f"wrote {out} ({len(rows)} clips)")


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawTextHelpFormatter)
    ap.add_argument("media", nargs="?")
    ap.add_argument("--out", help="index root, e.g. work/index")
    ap.add_argument("--proxy-dir", help="write a 720p CFR proxy here (omit for reference videos)")
    ap.add_argument("--fps", type=int, default=30, help="proxy frame rate")
    ap.add_argument("--scene-threshold", type=float, default=0.30)
    ap.add_argument("--no-transcript", action="store_true")
    ap.add_argument("--lang", default="zh")
    ap.add_argument("--model", default=DEFAULT_MODEL)
    ap.add_argument("--prompt", default=DEFAULT_PROMPT)
    ap.add_argument("--glossary", help="brand/glossary.txt (lines of 錯字→正字)")
    ap.add_argument("--transcript-json", help="use an existing transcript instead of running Whisper")
    ap.add_argument("--force", action="store_true")
    ap.add_argument("--build-map", metavar="INDEX_ROOT")
    ap.add_argument("-o", "--output")
    a = ap.parse_args()

    if a.build_map:
        return build_map(Path(a.build_map), Path(a.output or "footage_map.md"))
    if not a.media or not a.out:
        ap.error("media and --out are required")

    src = Path(a.media)
    out = Path(a.out) / src.stem
    out.mkdir(parents=True, exist_ok=True)
    idx_path = out / "index.json"
    fp = fingerprint(src)
    if idx_path.exists() and not a.force and load_json(idx_path).get("fingerprint") == fp:
        print(f"cached: {src.name}")
        return

    meta = probe(src)
    dur = meta["duration"]
    warnings = []
    if meta.get("hdr"):
        warnings.append("HDR 素材：proxy 與預覽顏色會偏灰，調色請以原檔／剪輯軟體為準")
    if meta.get("vfr"):
        warnings.append("可變影格率 (VFR)：proxy 已轉成固定影格率")

    work = src
    if a.proxy_dir and meta["has_video"]:
        px = Path(a.proxy_dir) / (src.stem + ".mp4")
        make_proxy(src, px, a.fps, meta)
        work = px

    index = {"src": str(src), "fingerprint": fp, "meta": meta, "warnings": warnings}
    if meta["has_audio"]:
        index["audio"] = audio_pass(work, dur)
    if meta["has_video"]:
        index["shots"] = shot_pass(work, dur, a.scene_threshold)
        index["color"] = color_pass(work)
        index["sheets"] = sheets(work, out, dur)

    index["transcript"] = {"available": False}
    if meta["has_audio"] and not a.no_transcript:
        gl = load_glossary(Path(a.glossary)) if a.glossary else []
        if a.transcript_json:
            segs, engine = load_json(a.transcript_json)["segments"], "imported"
        else:
            segs, engine = transcribe(work, a.lang, a.model, a.prompt), "mlx-whisper"
        if segs is None:
            index["transcript"]["error"] = "mlx-whisper 未安裝（執行 /setup）"
        else:
            index["transcript"] = write_transcript(out, segs, a.lang, engine, dur, gl)

    save_json(idx_path, index)
    s, t = index.get("shots") or {}, index["transcript"]
    print(f"indexed {src.name}: {tc(dur)}, {s.get('count', 0)} shots, "
          f"{len(index.get('sheets', {}).get('files', []))} sheets, "
          f"transcript={'yes' if t.get('available') else 'no'}"
          + (f" | {'; '.join(warnings)}" if warnings else ""))


if __name__ == "__main__":
    if shutil.which(tool("ffmpeg")) is None:
        raise SystemExit("ffmpeg not found — run /setup")
    main()

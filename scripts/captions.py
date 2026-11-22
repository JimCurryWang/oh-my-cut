#!/usr/bin/env python3
"""Captions are DERIVED, never hand-timed: source transcripts + cut.json -> timeline.
Re-run after any timeline change and they stay in sync.

  captions.py build <cut.json> --index-dir <ep>/work/index -o <prefix>
                    [--max-chars 14] [--max-gap 0.6] [--glossary brand/glossary.txt]
        writes <prefix>.json (lines + per-word timing, for the overlay engine)
        and    <prefix>.srt  (for Final Cut / YouTube)
  captions.py check <cut.json> --index-dir <ep>/work/index
        lists spine cuts that land inside a spoken word, with the nearest safe point

Only spine clips are captioned (the storyline you hear); muted clips are skipped.
"""
from __future__ import annotations

import argparse
import math
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from omc_common import fps_of, layout, load_json, save_json, secs  # noqa: E402

PUNCT = "，。！？、；：,.!?;:…"


def words_of(index_dir: Path, src: str, cache: dict):
    stem = Path(src).stem
    if stem not in cache:
        p = index_dir / stem / "transcript.json"
        ws = []
        if p.exists():
            for s in load_json(p)["segments"]:
                ws += s.get("words") or [{"w": s["text"], "start": s["start"], "end": s["end"]}]
        cache[stem] = ws
    return cache[stem]


def width(text: str) -> float:
    return sum(1.0 if ord(ch) > 0x2E7F else 0.5 for ch in text if not ch.isspace())


def srt_time(t: float) -> str:
    ms = int(round(t * 1000))
    h, ms = divmod(ms, 3600000)
    m, ms = divmod(ms, 60000)
    s, ms = divmod(ms, 1000)
    return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"


def timeline_words(cut, index_dir):
    fps = fps_of(cut)
    items, total = layout(cut)
    cache, out = {}, []
    for c, t0, d in items:
        if "gap" in c or c.get("mute") or float(c.get("gain_db", 0) or 0) <= -40:
            continue
        start, dur = secs(t0, fps), secs(d, fps)
        for w in words_of(index_dir, c["src"], cache):
            mid = (w["start"] + w["end"]) / 2
            if c["in"] <= mid < c["out"]:
                a = min(max(start + w["start"] - c["in"], start), start + dur)
                b = min(max(start + w["end"] - c["in"], a), start + dur)
                out.append({"w": w["w"], "start": round(a, 3), "end": round(b, 3), "clip": c["id"],
                            "src": c["src"], "src_start": w["start"], "src_end": w["end"]})
    return out, secs(total, fps)


def do_build(a):
    cut = load_json(a.cut)
    words, total = timeline_words(cut, Path(a.index_dir))
    glossary = []
    if a.glossary and Path(a.glossary).exists():
        for line in Path(a.glossary).read_text(encoding="utf-8").splitlines():
            if "→" in line and not line.strip().startswith("#"):
                x, y = line.split("→", 1)
                glossary.append((x.strip(), y.strip()))

    # 1) phrases: break on punctuation, on a pause, and where a cut jumps in the source
    phrases, cur = [], []
    for w in words:
        text = w["w"].strip()
        if not text:
            continue
        if cur:
            prev = cur[-1]
            jump = w["clip"] != prev["clip"] and (
                w["src"] != prev["src"] or abs(w["src_start"] - prev["src_end"]) > a.max_gap)
            if jump or w["start"] - prev["end"] > a.max_gap:
                phrases.append(cur)
                cur = []
        cur.append({**w, "w": text})
        if text[-1] in PUNCT:
            phrases.append(cur)
            cur = []
    if cur:
        phrases.append(cur)

    # 2) lines: split a long phrase into the fewest lines of roughly equal width
    lines = []
    for ph in phrases:
        widths = [width(x["w"]) for x in ph]
        left = max(1, math.ceil(sum(widths) / a.max_chars))
        target, line, acc = sum(widths) / left, [], 0.0
        for x, wx in zip(ph, widths):
            if line and left > 1 and acc + wx / 2 > target:
                lines.append(line)
                line, acc, left = [], 0.0, left - 1
            line.append(x)
            acc += wx
        if line:
            lines.append(line)

    result = []
    for i, ws in enumerate(lines):
        raw = "".join(x["w"] if ord(x["w"][0]) > 0x2E7F else " " + x["w"] for x in ws).strip()
        text = raw.strip(PUNCT + " ") if not a.keep_punct else raw
        if not a.keep_punct:
            text = re.sub(f"[{re.escape(PUNCT)}]+", " ", text).strip()
        for x, y in glossary:
            text = text.replace(x, y)
        if not text:
            continue
        start, end = ws[0]["start"], ws[-1]["end"]
        nxt = lines[i + 1][0]["start"] if i + 1 < len(lines) else total
        end = min(max(end + a.hold, start + a.min_dur), nxt, total)
        result.append({"n": len(result) + 1, "start": round(start, 3), "end": round(end, 3),
                       "text": text,
                       "words": [{k: x[k] for k in ("w", "start", "end", "clip")} for x in ws]})

    prefix = Path(a.output)
    prefix.parent.mkdir(parents=True, exist_ok=True)
    save_json(prefix.with_suffix(".json"), {"fps": cut.get("fps"), "duration": total,
                                            "lines": result})
    prefix.with_suffix(".srt").write_text(
        "".join(f"{c['n']}\n{srt_time(c['start'])} --> {srt_time(c['end'])}\n{c['text']}\n\n"
                for c in result), encoding="utf-8")
    print(f"captions: {len(result)} lines from {len(words)} words → "
          f"{prefix.with_suffix('.json')}, {prefix.with_suffix('.srt')}")
    if not words:
        print("（沒有找到任何 transcript 文字——確認 /index 有跑 Whisper）")


def do_check(a):
    cut = load_json(a.cut)
    cache, bad = {}, 0
    for c in cut.get("spine", []):
        if "gap" in c:
            continue
        ws = words_of(Path(a.index_dir), c["src"], cache)
        for edge in ("in", "out"):
            t = c[edge]
            for w in ws:
                if w["start"] + a.tolerance < t < w["end"] - a.tolerance:
                    safe = w["start"] if (t - w["start"] < w["end"] - t) else w["end"]
                    bad += 1
                    print(f"{c['id']} {edge}={t:.3f} 切在「{w['w'].strip()}」中間 "
                          f"({w['start']:.3f}–{w['end']:.3f}) → 建議 {safe:.3f}")
                    break
    print("cuts ok：沒有切在字中間" if not bad else f"{bad} 個切點落在字中間")
    return 1 if bad else 0


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawTextHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    b = sub.add_parser("build")
    b.add_argument("cut")
    b.add_argument("--index-dir", required=True)
    b.add_argument("-o", "--output", required=True)
    b.add_argument("--max-chars", type=float, default=14)
    b.add_argument("--max-gap", type=float, default=0.6)
    b.add_argument("--min-dur", type=float, default=0.7)
    b.add_argument("--hold", type=float, default=0.15)
    b.add_argument("--keep-punct", action="store_true")
    b.add_argument("--glossary")
    c = sub.add_parser("check")
    c.add_argument("cut")
    c.add_argument("--index-dir", required=True)
    c.add_argument("--tolerance", type=float, default=0.03)
    a = ap.parse_args()
    if a.cmd == "build":
        do_build(a)
    else:
        sys.exit(do_check(a))


if __name__ == "__main__":
    main()

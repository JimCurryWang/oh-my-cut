#!/usr/bin/env python3
"""Captions are DERIVED, never hand-timed: source transcripts + cut.json -> timeline.
Re-run after any timeline change and they stay in sync.

  captions.py build <cut.json> --index-dir <ep>/work/index -o <prefix>
                    [--max-chars 14] [--max-gap 0.6] [--glossary brand/glossary.txt]
        writes <prefix>.json (lines + per-word timing, for the overlay engine)
        and    <prefix>.srt  (for Final Cut / YouTube)
  captions.py check <cut.json> --index-dir <ep>/work/index
        lists spine cuts that land inside a spoken word, with the nearest safe point
  captions.py fcpxml <prefix>.json -o <prefix>.fcpxml [--brand brand/brand.json]
                    [--style taste/<style>/profile/style.json] [--font F] [--size PX]
                    [--y PX] [--no-stroke] [--limit N]
        every caption line as an editable Final Cut title (Basic Title), styled from
        brand.json (font, colours) and style.json (size). Opens as its own project:
        copy the titles, paste them into your project at 0 with Option-V.

Only spine clips are captioned (the storyline you hear); muted clips are skipped.
"""
from __future__ import annotations

import argparse
import math
import re
import sys
import xml.etree.ElementTree as ET
from fractions import Fraction
from pathlib import Path
from xml.dom import minidom

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
    save_json(prefix.with_suffix(".json"), {"fps": cut.get("fps"), "size": cut.get("size"),
                                            "duration": total, "lines": result})
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


BASIC_TITLE = (".../Titles.localized/Bumper:Opener.localized/Basic Title.localized/"
               "Basic Title.moti")
POSITION_KEY = "9999/999166631/999166633/1/100/101"


def colour(hexstr: str, default="1 1 1 1") -> str:
    """'#FFD23F' -> '1 0.8235 0.2471 1' (FCPXML colour)."""
    m = re.fullmatch(r"#?([0-9a-fA-F]{6})", (hexstr or "").strip())
    if not m:
        return default
    v = [int(m.group(1)[i:i + 2], 16) / 255 for i in (0, 2, 4)]
    return " ".join(f"{x:.4g}" for x in v) + " 1"


def do_fcpxml(a):
    from fcpxml_bridge import format_name, rt
    cap = load_json(a.captions)
    n, d = cap.get("fps") or [30, 1]
    fps = Fraction(int(n), int(d))
    fd = 1 / fps
    w, h = cap.get("size") or [1920, 1080]
    brand = load_json(a.brand) if a.brand and Path(a.brand).exists() else {}
    style = load_json(a.style) if a.style and Path(a.style).exists() else {}
    fonts, colors = brand.get("fonts") or {}, brand.get("colors") or {}
    font = a.font or fonts.get("caption")
    if not font:
        font = "PingFang TC"
        print("⚠ brand.json 沒有 fonts.caption，暫用 PingFang TC")
    pct = (style.get("captions") or {}).get("size_pct_of_height") or 5.5
    size = a.size or round(h * float(pct) / 100)
    margin = float((brand.get("caption") or {}).get("safe_margin_pct") or 6)
    y = a.y if a.y is not None else -round(h / 2 - h * margin / 100 - size * 0.6)

    def fr(sec):
        return int(round(Fraction(str(sec)) * fps))

    total = fr(cap["duration"])
    root = ET.Element("fcpxml", version="1.10")
    res = ET.SubElement(root, "resources")
    fmt = {"id": "r1", "frameDuration": rt(fd), "width": str(w), "height": str(h)}
    if format_name(w, h, fps):
        fmt["name"] = format_name(w, h, fps)
    ET.SubElement(res, "format", fmt)
    ET.SubElement(res, "effect", id="r2", name="Basic Title", uid=BASIC_TITLE)
    name = a.name or Path(a.captions).parent.parent.parent.name or "captions"
    ev = ET.SubElement(ET.SubElement(root, "library"), "event", name=f"{name} 字幕")
    seq = ET.SubElement(ET.SubElement(ev, "project", name=f"{name} 字幕"), "sequence",
                        format="r1", duration=rt(total * fd), tcStart="0s", tcFormat="NDF",
                        audioLayout="stereo", audioRate="48k")
    gap = ET.SubElement(ET.SubElement(seq, "spine"), "gap", name="Gap", offset="0s",
                        start="0s", duration=rt(total * fd))
    lines = cap["lines"][:a.limit] if a.limit else cap["lines"]
    for i, ln in enumerate(lines, 1):
        f0, f1 = fr(ln["start"]), fr(ln["end"])
        if f1 <= f0:
            f1 = f0 + 1
        t = ET.SubElement(gap, "title", ref="r2", lane="1", offset=rt(f0 * fd),
                          duration=rt((f1 - f0) * fd), name=f"{i:03d} {ln['text'][:20]}")
        ET.SubElement(t, "param", name="Position", key=POSITION_KEY, value=f"0 {y}")
        ts_id = f"ts{i}"
        ET.SubElement(ET.SubElement(t, "text"), "text-style", ref=ts_id).text = ln["text"]
        style_attrs = {"font": font, "fontSize": str(size), "fontColor": colour(colors.get("primary")),
                       "alignment": "center", "bold": "1"}
        if not a.no_stroke:
            style_attrs.update(strokeColor=colour(colors.get("stroke"), "0 0 0 1"),
                               strokeWidth=f"{max(1, round(size * 0.05)):g}")
        ET.SubElement(ET.SubElement(t, "text-style-def", id=ts_id), "text-style", style_attrs)

    xml = minidom.parseString(ET.tostring(root, encoding="unicode")).toprettyxml(indent="  ")
    xml = xml.replace('<?xml version="1.0" ?>',
                      '<?xml version="1.0" encoding="UTF-8"?>\n<!DOCTYPE fcpxml>')
    # whitespace inside <text> is text: keep the caption exactly as written
    xml = re.sub(r"<text>\s+<text-style", "<text><text-style", xml)
    xml = re.sub(r"</text-style>\s+</text>", "</text-style></text>", xml)
    out = Path(a.output)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(xml, encoding="utf-8")
    print(f"fcpxml: {len(lines)} 行字幕 → {out}（{font} {size}px，位置 0 {y}，{w}x{h}）")
    print("Final Cut：File > Import > XML… → 打開「字幕」專案 → 選取所有標題 ⌘C → "
          "回到你的專案，播放頭移到最開頭 → ⌥V（貼上為連接片段）")


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
    x = sub.add_parser("fcpxml")
    x.add_argument("captions", help="captions.json written by `build`")
    x.add_argument("-o", "--output", required=True)
    x.add_argument("--brand", default=str(Path(__file__).resolve().parent.parent / "brand" / "brand.json"))
    x.add_argument("--style")
    x.add_argument("--font")
    x.add_argument("--size", type=int, help="font size in px (default: style.json size_pct_of_height)")
    x.add_argument("--y", type=int, help="vertical position from centre, px (negative = lower)")
    x.add_argument("--no-stroke", action="store_true")
    x.add_argument("--limit", type=int, help="only the first N lines (a sample to check the look)")
    x.add_argument("--name")
    a = ap.parse_args()
    if a.cmd == "build":
        do_build(a)
    elif a.cmd == "fcpxml":
        do_fcpxml(a)
    else:
        sys.exit(do_check(a))


if __name__ == "__main__":
    main()

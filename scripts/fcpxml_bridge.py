#!/usr/bin/env python3
"""Round-trip between cut.json and Final Cut Pro (FCPXML 1.10).

  fcpxml_bridge.py export <cut.json> --episode-dir <ep> [-o out.fcpxml] [--proxy]
  fcpxml_bridge.py import <file.fcpxml | bundle.fcpxmld> --episode-dir <ep> -o cut.fcp.json
  fcpxml_bridge.py diff   <ours.json> <theirs.json> [-o diff.json]

export  spine -> primary storyline; overlays -> connected clips (lane 1, video only
        unless gain_db is set); audio -> connected clips (lane -1); sections -> markers.
        Points at the ORIGINAL media unless --proxy.
import  reads what Final Cut exported after you finished (File > Export XML…).
        Titles, transitions, retimes and compound clips are listed under "unparsed"
        rather than guessed at.
diff    what you changed: trims in frames, deletions, splits, reorders, additions,
        plus aggregate habits (average head/tail trim) for /learn.
"""
from __future__ import annotations

import argparse
import os
import re
import statistics
import sys
import urllib.parse
import xml.etree.ElementTree as ET
from fractions import Fraction
from pathlib import Path
from xml.dom import minidom

sys.path.insert(0, str(Path(__file__).parent))
from omc_common import (ID_IN_NAME, fps_of, frames, layout, load_json, probe,  # noqa: E402
                        resolve, save_json, tc, validate)

RATE_NAMES = {Fraction(24000, 1001): "2398", Fraction(24): "24", Fraction(25): "25",
              Fraction(30000, 1001): "2997", Fraction(30): "30", Fraction(50): "50",
              Fraction(60000, 1001): "5994", Fraction(60): "60"}


# ---------- time ----------
def rt(fr: Fraction) -> str:
    fr = Fraction(fr)
    return f"{fr.numerator}s" if fr.denominator == 1 else f"{fr.numerator}/{fr.denominator}s"


def pt(text: str | None) -> Fraction:
    if not text:
        return Fraction(0)
    return Fraction(text.strip().rstrip("s"))


def tc_to_time(tcode: str | None, fps: Fraction) -> Fraction:
    """Source timecode -> seconds (handles drop-frame for 29.97/59.94)."""
    m = re.match(r"(\d+):(\d+):(\d+)([:;.,])(\d+)", tcode or "")
    if not m:
        return Fraction(0)
    h, mi, s, sep, f = int(m[1]), int(m[2]), int(m[3]), m[4], int(m[5])
    base = round(fps)
    total = ((h * 60 + mi) * 60 + s) * base + f
    if sep in ";,." and base in (30, 60):
        mins = h * 60 + mi
        total -= (2 if base == 30 else 4) * (mins - mins // 10)
    return Fraction(total) / fps


def format_name(w, h, fps):
    rate = RATE_NAMES.get(fps)
    if not rate:
        return None
    if (w, h) == (1920, 1080):
        return f"FFVideoFormat1080p{rate}"
    if (w, h) == (1280, 720):
        return f"FFVideoFormat720p{rate}"
    if (w, h) == (3840, 2160):
        return f"FFVideoFormat3840x2160p{rate}"
    return None


# ---------- export ----------
def do_export(a):
    cut_path, ep = Path(a.cut), Path(a.episode_dir).resolve()
    cut = load_json(cut_path)
    problems = validate(cut, ep)
    if problems:
        raise SystemExit("cut.json 有問題：\n  " + "\n  ".join(problems))
    fps = fps_of(cut)
    fd = 1 / fps
    w, h = cut.get("size", [1920, 1080])
    items, total = layout(cut)

    root = ET.Element("fcpxml", version="1.10")
    res = ET.SubElement(root, "resources")
    counter = [0]
    formats, assets = {}, {}

    def new_id():
        counter[0] += 1
        return f"r{counter[0]}"

    def fmt_id(fw, fh, ffps):
        key = (fw, fh, ffps)
        if key not in formats:
            attrs = {"id": new_id(), "frameDuration": rt(1 / ffps),
                     "width": str(fw), "height": str(fh)}
            nm = format_name(fw, fh, ffps)
            if nm:
                attrs["name"] = nm
            ET.SubElement(res, "format", attrs)
            formats[key] = attrs["id"]
        return formats[key]

    seq_fmt = fmt_id(w, h, fps)

    def asset(src: str):
        if src in assets:
            return assets[src]
        path = resolve(ep, src, proxy=a.proxy).resolve()
        info = probe(path)
        attrs = {"id": new_id(), "name": Path(src).stem}
        if info["has_video"]:
            afps = Fraction(*info["fps"])
            start = tc_to_time(info.get("timecode"), afps)
            n = int(round(Fraction(str(info["duration"])) * afps))
            attrs.update(start=rt(start), duration=rt(Fraction(n) / afps), hasVideo="1",
                         format=fmt_id(info["width"], info["height"], afps))
        else:
            start = Fraction(0)
            rate = info.get("audio_rate", 48000)
            attrs.update(start="0s",
                         duration=rt(Fraction(int(round(info["duration"] * rate)), rate)))
        if info["has_audio"]:
            attrs.update(hasAudio="1", audioSources="1",
                         audioChannels=str(info.get("audio_channels", 2)),
                         audioRate=str(info.get("audio_rate", 48000)))
        el = ET.SubElement(res, "asset", attrs)
        ET.SubElement(el, "media-rep", kind="original-media", src=path.as_uri())
        assets[src] = (attrs["id"], start, info)
        return assets[src]

    lib = ET.SubElement(root, "library")
    ev = ET.SubElement(lib, "event", name=a.event or ep.name)
    proj = ET.SubElement(ev, "project", name=a.project or cut.get("name", cut_path.stem))
    seq = ET.SubElement(proj, "sequence", format=seq_fmt, duration=rt(total * fd),
                        tcStart="0s", tcFormat="NDF", audioLayout="stereo", audioRate="48k")
    spine = ET.SubElement(seq, "spine")

    def src_range(c):
        f_in = frames(c["in"], fps)
        return f_in, frames(c["out"], fps) - f_in

    placed = []  # (element, start_frame, dur_frames, parent_local_start: Fraction)
    for c, t0, d in items:
        if "gap" in c:
            el = ET.SubElement(spine, "gap", name="Gap", offset=rt(t0 * fd), start="0s",
                               duration=rt(d * fd))
            placed.append((el, t0, d, Fraction(0)))
            continue
        aid, astart, info = asset(c["src"])
        f_in, _ = src_range(c)
        local = astart + f_in * fd
        el = ET.SubElement(spine, "asset-clip", ref=aid,
                           name=f"{Path(c['src']).stem} [{c['id']}]", offset=rt(t0 * fd),
                           start=rt(local), duration=rt(d * fd), tcFormat="NDF")
        if c.get("mute"):
            el.set("srcEnable", "video")
        elif c.get("gain_db"):
            ET.SubElement(el, "adjust-volume", amount=f"{float(c['gain_db']):g}dB")
        placed.append((el, t0, d, local))

    if not placed:
        raise SystemExit("spine 是空的，沒有東西可以匯出")

    def attach(c, lane, video_only):
        aid, astart, info = asset(c["src"])
        at = frames(c["at"], fps)
        parent = placed[-1]
        for p in placed:
            if p[1] <= at < p[1] + p[2]:
                parent = p
                break
        pel, p0, _, plocal = parent
        f_in, d = src_range(c)
        el = ET.Element("asset-clip", ref=aid, lane=str(lane),
                        name=f"{Path(c['src']).stem} [{c['id']}]",
                        offset=rt(plocal + (at - p0) * fd), start=rt(astart + f_in * fd),
                        duration=rt(d * fd), tcFormat="NDF")
        if video_only and info["has_audio"]:
            el.set("srcEnable", "video")
        if c.get("gain_db") and not video_only:
            ET.SubElement(el, "adjust-volume", amount=f"{float(c['gain_db']):g}dB")
        # DTD order: adjust-* first, then connected clips, then markers
        idx = len([x for x in pel if x.tag.startswith("adjust-") or x.tag == "asset-clip"])
        pel.insert(idx, el)

    for o in cut.get("overlays", []):
        attach(o, 1, video_only=("gain_db" not in o))
    for m in cut.get("audio", []):
        attach(m, -1, video_only=False)

    for s in cut.get("sections", []):
        at = frames(s["at"], fps)
        for pel, p0, d, plocal in placed:
            if p0 <= at < p0 + d:
                ET.SubElement(pel, "marker", start=rt(plocal + (at - p0) * fd),
                              duration=rt(fd), value=s["name"])
                break

    xml = minidom.parseString(ET.tostring(root, encoding="unicode")).toprettyxml(indent="  ")
    xml = xml.replace('<?xml version="1.0" ?>',
                      '<?xml version="1.0" encoding="UTF-8"?>\n<!DOCTYPE fcpxml>')
    out = Path(a.output) if a.output else cut_path.with_suffix(".fcpxml")
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(xml, encoding="utf-8")
    print(f"exported {out}: {len(items)} spine clips, {len(cut.get('overlays', []))} overlays, "
          f"{len(cut.get('audio', []))} audio, {tc(float(total * fd))}")
    print("Final Cut：File > Import > XML…  （會建立事件與專案；媒體指向"
          + ("proxy" if a.proxy else "原始檔") + "）")


# ---------- import ----------
SKIP_TAGS = {"note", "marker", "chapter-marker", "keyword", "rating", "metadata",
             "audio-channel-source", "conform-rate"}


def do_import(a):
    src, ep = Path(a.file), Path(a.episode_dir).resolve()
    if src.is_dir():
        inner = sorted(src.glob("*.fcpxml"))
        if not inner:
            raise SystemExit(f"{src} 內找不到 .fcpxml")
        src = inner[0]
    root = ET.parse(src).getroot()
    res = root.find("resources")
    fmts = {f.get("id"): f for f in res.findall("format")}
    assets = {}
    for el in res.findall("asset"):
        rep = el.find("media-rep")
        url = (rep.get("src") if rep is not None else None) or el.get("src") or ""
        path = Path(urllib.parse.unquote(urllib.parse.urlparse(url).path))
        rel = os.path.relpath(path.resolve(), ep) if url else ""
        assets[el.get("id")] = {"src": rel, "start": pt(el.get("start")),
                                "video": el.get("hasVideo") == "1"}

    seq = root.find(".//sequence")
    if seq is None:
        raise SystemExit("找不到 <sequence>（請匯出「專案」而非事件或資源庫）")
    f = fmts.get(seq.get("format"))
    fd = pt(f.get("frameDuration")) if f is not None else Fraction(1, 30)
    fps = 1 / fd
    cut = {"version": 1, "name": src.stem,
           "fps": [fps.numerator, fps.denominator],
           "size": [int(f.get("width", 1920)), int(f.get("height", 1080))] if f is not None else [1920, 1080],
           "source": str(src), "spine": [], "overlays": [], "audio": [], "unparsed": []}
    proj = root.find(".//project")
    cut["name"] = proj.get("name") if proj is not None else src.stem
    counters = {"x": 0, "gap": 0}

    def cid(el, prefix):
        m = ID_IN_NAME.search(el.get("name") or "")
        if m:
            return m.group(1)
        counters["x"] += 1
        return f"{prefix}{counters['x']}"

    def gain(el):
        v = el.find("adjust-volume")
        if v is not None and v.get("amount"):
            try:
                return float(v.get("amount").replace("dB", ""))
            except ValueError:
                return None
        return None

    def unparsed(el, where):
        cut["unparsed"].append({"tag": el.tag, "name": el.get("name"), "where": where,
                                "offset": round(float(pt(el.get("offset"))), 3),
                                "duration": round(float(pt(el.get("duration"))), 3)})

    def item_from(el):
        asset = assets.get(el.get("ref"))
        if asset is None:
            return None
        t_in = pt(el.get("start")) - asset["start"]
        d = {"src": asset["src"], "in": round(float(t_in), 4),
             "out": round(float(t_in + pt(el.get("duration"))), 4)}
        g = gain(el)
        if g is not None:
            d["gain_db"] = g
        if el.find("timeMap") is not None:
            d["retimed"] = True
            cut["unparsed"].append({"tag": "timeMap", "name": el.get("name"),
                                    "where": "speed change — in/out 可能不準"})
        return d, asset

    def connected(parent, parent_offset, parent_start):
        for ch in parent:
            if ch.get("lane") is None:
                if ch.tag not in SKIP_TAGS and not ch.tag.startswith(("adjust-", "filter-")) \
                        and ch.tag != "timeMap":
                    unparsed(ch, f"inside {parent.get('name')}")
                continue
            at = parent_offset + (pt(ch.get("offset")) - parent_start)
            if ch.tag != "asset-clip" or item_from(ch) is None:
                unparsed(ch, f"connected @ {tc(float(at))}")
                continue
            d, asset = item_from(ch)
            lane = int(ch.get("lane"))
            is_audio = lane < 0 or not asset["video"] or ch.get("srcEnable") == "audio"
            d = {"id": cid(ch, "fa" if is_audio else "fo"), **d, "at": round(float(at), 4)}
            if not is_audio and ch.get("srcEnable") != "video" and "gain_db" not in d:
                d["gain_db"] = 0.0  # overlay audio is live in Final Cut
            cut["audio" if is_audio else "overlays"].append(d)

    spine = seq.find("spine")
    for el in spine:
        off, start = pt(el.get("offset")), pt(el.get("start"))
        if el.tag == "asset-clip" and item_from(el) is not None:
            d, _ = item_from(el)
            item = {"id": cid(el, "fs"), **d}
            if el.get("srcEnable") == "video":
                item["mute"] = True
            cut["spine"].append(item)
            connected(el, off, start)
        elif el.tag == "gap":
            counters["gap"] += 1
            cut["spine"].append({"id": f"gap{counters['gap']}",
                                 "gap": round(float(pt(el.get("duration"))), 4)})
            connected(el, off, start)
        elif el.tag == "transition":
            unparsed(el, "spine")
        else:
            unparsed(el, "spine")
            counters["gap"] += 1  # keep timing: stand in a gap of the same length
            cut["spine"].append({"id": f"gap{counters['gap']}", "unparsed_tag": el.tag,
                                 "gap": round(float(pt(el.get("duration"))), 4)})

    # split pieces share an id: make them unique but traceable (s3, s3#2, ...)
    seen = {}
    for kind in ("spine", "overlays", "audio"):
        for c in cut[kind]:
            n = seen.get(c["id"], 0) + 1
            seen[c["id"]] = n
            if n > 1:
                c["origin"] = c["id"]
                c["id"] = f"{c['id']}#{n}"
    out = Path(a.output)
    save_json(out, cut)
    _, total = layout(cut)
    print(f"imported {out}: {len(cut['spine'])} spine, {len(cut['overlays'])} overlays, "
          f"{len(cut['audio'])} audio, {tc(float(total / fps))}")
    if cut["unparsed"]:
        kinds = sorted({u["tag"] for u in cut["unparsed"]})
        print(f"未解析（保留在 Final Cut，不會進 cut.json）：{len(cut['unparsed'])} 項 {kinds}")


# ---------- diff ----------
def do_diff(a):
    ours, theirs = load_json(a.ours), load_json(a.theirs)
    fps = fps_of(ours)

    def fr(x):
        return frames(x, fps)

    def anchor(cut, c):
        """(spine clip id, source frame of that clip) under an overlay's start."""
        at = fr(c["at"])
        for sc, t0, d in layout(cut)[0]:
            if t0 <= at < t0 + d and "gap" not in sc:
                return sc.get("origin", sc["id"]), fr(sc["in"]) + (at - t0)
        return None

    events, head, tail = [], [], []
    stats = {}
    for kind in ("spine", "overlays", "audio"):
        A = [c for c in ours.get(kind, []) if "gap" not in c]
        B = [c for c in theirs.get(kind, []) if "gap" not in c]
        groups = {}
        for c in B:
            groups.setdefault(c.get("origin", c["id"]), []).append(c)
        known = {c["id"] for c in A}
        removed = kept = 0
        for c in A:
            g = groups.get(c["id"])
            if not g:
                removed += 1
                events.append({"type": "removed", "kind": kind, "id": c["id"],
                               "src": c["src"], "duration_frames": fr(c["out"]) - fr(c["in"]),
                               "role": c.get("role"), "note": c.get("note")})
                continue
            kept += 1
            if os.path.normpath(g[0]["src"]) != os.path.normpath(c["src"]):
                events.append({"type": "replaced", "kind": kind, "id": c["id"],
                               "from": c["src"], "to": g[0]["src"]})
                continue
            dh = fr(min(x["in"] for x in g)) - fr(c["in"])
            dtl = fr(max(x["out"] for x in g)) - fr(c["out"])
            if len(g) > 1:
                inner = sum(fr(x["out"]) - fr(x["in"]) for x in g)
                events.append({"type": "split", "kind": kind, "id": c["id"], "pieces": len(g),
                               "removed_inside_frames":
                                   (fr(c["out"]) + dtl) - (fr(c["in"]) + dh) - inner})
            if dh or dtl:
                events.append({"type": "trimmed", "kind": kind, "id": c["id"],
                               "head_frames": dh, "tail_frames": dtl,
                               "role": c.get("role"), "note": c.get("note")})
            if kind == "spine":
                head.append(dh)
                tail.append(dtl)
            if kind != "spine":
                # connected clips ripple with their parent in Final Cut, so compare the
                # position relative to the spine clip underneath, not the absolute time
                pa, pb = anchor(ours, c), anchor(theirs, g[0])
                if pa and pb and pa[0] == pb[0]:
                    dat = pb[1] - pa[1] - dh
                    if dat:
                        events.append({"type": "shifted", "kind": kind, "id": c["id"],
                                       "frames": dat, "relative_to": pa[0]})
                elif pa and pb:
                    events.append({"type": "reanchored", "kind": kind, "id": c["id"],
                                   "from": pa[0], "to": pb[0]})
            ga, gb = c.get("gain_db", 0) or 0, g[0].get("gain_db", 0) or 0
            if abs(ga - gb) >= 0.5:
                events.append({"type": "gain", "kind": kind, "id": c["id"], "from": ga, "to": gb})
        added = [c for c in B if c.get("origin", c["id"]) not in known]
        for c in added:
            events.append({"type": "added", "kind": kind, "id": c["id"], "src": c["src"],
                           "in": c["in"], "out": c["out"], "at": c.get("at")})
        stats[kind] = {"ours": len(A), "kept": kept, "removed": removed, "added": len(added)}

    order_a = [c["id"] for c in ours.get("spine", []) if "gap" not in c]
    order_b, seen = [], set()
    for c in theirs.get("spine", []):
        o = c.get("origin", c.get("id"))
        if "gap" not in c and o in set(order_a) and o not in seen:
            order_b.append(o)
            seen.add(o)
    common = [x for x in order_a if x in seen]
    if common != order_b:
        events.append({"type": "reordered", "kind": "spine", "ours": common, "theirs": order_b})

    _, ta = layout(ours)
    _, tb = layout(theirs)
    changed = [x for x in zip(head, tail) if x[0] or x[1]]
    habits = {
        "spine_clips_compared": len(head),
        "spine_clips_trimmed": len(changed),
        "mean_head_frames": round(statistics.mean(head), 2) if head else 0,
        "mean_tail_frames": round(statistics.mean(tail), 2) if tail else 0,
        "median_tail_frames": statistics.median(tail) if tail else 0,
        "tails_tightened": len([t for t in tail if t < 0]),
        "tails_extended": len([t for t in tail if t > 0]),
        "heads_tightened": len([x for x in head if x > 0]),
        "heads_extended": len([x for x in head if x < 0]),
        "total_frames_ours": ta, "total_frames_theirs": tb,
        "duration_change_pct": round((tb - ta) / ta * 100, 1) if ta else 0,
    }
    result = {"fps": ours.get("fps"), "stats": stats, "habits": habits, "events": events,
              "unparsed": theirs.get("unparsed", [])}
    if a.output:
        save_json(a.output, result)

    print(f"## Diff（我們的 → Final Cut）  長度 {tc(float(ta / fps))} → {tc(float(tb / fps))} "
          f"({habits['duration_change_pct']:+}%)")
    for k, s in stats.items():
        print(f"- {k}: 保留 {s['kept']}/{s['ours']}，刪除 {s['removed']}，新增 {s['added']}")
    print(f"- spine 修剪 {habits['spine_clips_trimmed']}/{habits['spine_clips_compared']} 段；"
          f"尾巴收緊 {habits['tails_tightened']}、放長 {habits['tails_extended']}"
          f"（平均 {habits['mean_tail_frames']:+} 格）；"
          f"開頭收緊 {habits['heads_tightened']}、放長 {habits['heads_extended']}"
          f"（平均 {habits['mean_head_frames']:+} 格）")
    for e in events:
        t = e["type"]
        if t == "trimmed":
            print(f"  · {e['id']}: 頭 {e['head_frames']:+}f / 尾 {e['tail_frames']:+}f")
        elif t == "removed":
            print(f"  · {e['id']}: 刪除（{e['duration_frames']}f, {Path(e['src']).stem}）")
        elif t == "added":
            print(f"  · 新增 {e['id']}: {Path(e['src']).stem} {e['in']:.2f}–{e['out']:.2f}")
        elif t == "split":
            print(f"  · {e['id']}: 切成 {e['pieces']} 段，中間拿掉 {e['removed_inside_frames']}f")
        elif t == "shifted":
            print(f"  · {e['id']}: 相對於 {e['relative_to']} 移動 {e['frames']:+}f")
        elif t == "reanchored":
            print(f"  · {e['id']}: 從 {e['from']} 改掛到 {e['to']}")
        elif t == "gain":
            print(f"  · {e['id']}: 音量 {e['from']:g} → {e['to']:g} dB")
        elif t == "replaced":
            print(f"  · {e['id']}: 換素材 {Path(e['from']).stem} → {Path(e['to']).stem}")
        elif t == "reordered":
            print(f"  · 順序改變：{' '.join(e['theirs'])}")
    if result["unparsed"]:
        kinds = sorted({u["tag"] for u in result["unparsed"]})
        print(f"- Final Cut 內另有 {len(result['unparsed'])} 個未解析元素：{', '.join(kinds)}")
    if not events:
        print("- 沒有差異")


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawTextHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    e = sub.add_parser("export")
    e.add_argument("cut")
    e.add_argument("--episode-dir", required=True)
    e.add_argument("-o", "--output")
    e.add_argument("--proxy", action="store_true", help="link proxies instead of originals")
    e.add_argument("--event")
    e.add_argument("--project")
    i = sub.add_parser("import")
    i.add_argument("file")
    i.add_argument("--episode-dir", required=True)
    i.add_argument("-o", "--output", required=True)
    d = sub.add_parser("diff")
    d.add_argument("ours")
    d.add_argument("theirs")
    d.add_argument("-o", "--output")
    a = ap.parse_args()
    {"export": do_export, "import": do_import, "diff": do_diff}[a.cmd](a)


if __name__ == "__main__":
    main()

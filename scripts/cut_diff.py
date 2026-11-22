#!/usr/bin/env python3
"""What the user changed between two cut.json files, in frames, for /learn.

  cut_diff.py <ours.json> <theirs.json> [-o diff.json]

`ours` is what we handed over (the assembled timeline); `theirs` is what came
back: imported from Final Cut (fcpxml_bridge.py import) or reconstructed from the
finished video (reconform.py), whatever the editor. Clips are matched by id; a clip
split into pieces comes back as id, id#2... with "origin" set.

Reports trims (head/tail frames), deletions, splits, reorders, additions, source
swaps, overlay shifts relative to the clip underneath, gain changes, plus habits
(average head/tail trim) and anything the importer could not parse.
"""
from __future__ import annotations

import argparse
import os
import statistics
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from omc_common import fps_of, frames, layout, load_json, save_json, tc  # noqa: E402


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
            if any(x.get("edges_approx") for x in g):
                continue  # reconformed music: present, but its exact edges are unknown
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
            if not g[0].get("gain_unknown") and abs(ga - gb) >= 0.5:  # reconform can't measure gain
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

    print(f"## Diff（我們交出去的 → 精修後）  長度 {tc(float(ta / fps))} → {tc(float(tb / fps))} "
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
        print(f"- 另有 {len(result['unparsed'])} 個未解析元素：{', '.join(kinds)}")
    if not events:
        print("- 沒有差異")


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawTextHelpFormatter)
    ap.add_argument("ours")
    ap.add_argument("theirs")
    ap.add_argument("-o", "--output")
    do_diff(ap.parse_args())


if __name__ == "__main__":
    main()

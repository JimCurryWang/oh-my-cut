#!/usr/bin/env python3
"""Join the per-sequence cuts into one timeline cut.json.

  assemble.py <episode_dir> [--order 01-intro 02-arrival ...] [-o work/timeline/cut.json]

Order comes from --order, else from episode.json "sequences". Ids are prefixed
with the sequence name ("02-arrival/s3") so every clip stays traceable. Reads
only the cut.json files — never transcripts or frames.

Timeline-level items (music beds, clips that span sequences) live in
work/timeline/extras.json as {"overlays": [...], "audio": [...]} with `at` in
whole-timeline seconds; they are merged in with a "tl/" id prefix.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from omc_common import fps_of, layout, load_json, save_json, secs, tc, validate  # noqa: E402


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawTextHelpFormatter)
    ap.add_argument("episode_dir")
    ap.add_argument("--order", nargs="*")
    ap.add_argument("-o", "--output")
    a = ap.parse_args()

    ep = Path(a.episode_dir)
    meta = load_json(ep / "episode.json")
    order = a.order or meta.get("sequences") or []
    if not order:
        raise SystemExit("沒有順序：用 --order 或在 episode.json 填 sequences")

    out = {"version": 1, "name": meta.get("episode", ep.name), "fps": meta.get("fps", [30, 1]),
           "size": meta.get("size", [1920, 1080]), "sections": [],
           "spine": [], "overlays": [], "audio": []}
    fps = fps_of(out)
    cursor = 0  # frames
    print("| sequence | 起點 | 長度 | clips |\n|---|---|---|---|")
    for name in order:
        p = ep / "work" / "sequences" / name / "cut.json"
        if not p.exists():
            raise SystemExit(f"缺少 {p}")
        cut = load_json(p)
        if fps_of(cut) != fps:
            raise SystemExit(f"{name}: fps {cut.get('fps')} 與 episode {out['fps']} 不一致")
        items, total = layout(cut)
        start_s = secs(cursor, fps)
        out["sections"].append({"name": name, "at": start_s, "duration": secs(total, fps)})
        for c in cut.get("spine", []):
            out["spine"].append({**c, "id": f"{name}/{c['id']}"})
        for kind in ("overlays", "audio"):
            for c in cut.get(kind, []):
                out[kind].append({**c, "id": f"{name}/{c['id']}",
                                  "at": round(float(c["at"]) + start_s, 4)})
        print(f"| {name} | {tc(start_s)} | {secs(total, fps):.2f}s | {len(items)} |")
        cursor += total

    extras = ep / "work" / "timeline" / "extras.json"
    if extras.exists():
        ex = load_json(extras)
        for kind in ("overlays", "audio"):
            for c in ex.get(kind, []):
                out[kind].append({**c, "id": f"tl/{c['id']}"})
        print(f"+ extras: {len(ex.get('overlays', []))} overlays, {len(ex.get('audio', []))} audio")

    problems = validate(out, ep)
    if problems:
        raise SystemExit("組合後有問題：\n  " + "\n  ".join(problems))
    dst = Path(a.output) if a.output else ep / "work" / "timeline" / "cut.json"
    save_json(dst, out)
    print(f"total {tc(secs(cursor, fps))} → {dst}")


if __name__ == "__main__":
    main()

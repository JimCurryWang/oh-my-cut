#!/usr/bin/env python3
"""Frame-accurate edits to a cut.json. Every edit is appended to edits.jsonl next
to the cut file, so the user's habits are recorded without anyone remembering to.

  cut_edit.py <cut.json> trim  <id> [--head ±N] [--tail ±N] [--why "..."]
  cut_edit.py <cut.json> slip  <id> ±N          # move the source window, keep length
  cut_edit.py <cut.json> delete <id>
  cut_edit.py <cut.json> move  <id> --before <id> | --after <id>
  cut_edit.py <cut.json> swap  <id> <id>
  cut_edit.py <cut.json> shift <overlay/audio id> ±N   # move on the timeline
  cut_edit.py <cut.json> gain  <id> <dB>
  cut_edit.py <cut.json> show

Amounts: "6f" / "-6f" = frames (timeline fps), "0.2s" / "-0.2s" = seconds.
trim --head +N starts the clip N later; --tail -N ends it N earlier.
Add --by user|claude (default user) and --why to keep the reason.
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import re
import sys
from fractions import Fraction
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from omc_common import fps_of, layout, load_json, save_json, secs, tc, validate  # noqa: E402


def amount(text: str, fps: Fraction) -> float:
    """'6f' / '-0.2s' -> seconds (frame amounts stay exact multiples of a frame)."""
    t = text.strip().lower().replace("~", "-")
    if t.endswith("f"):
        return float(Fraction(int(t[:-1])) / fps)
    return float(t[:-1] if t.endswith("s") else t)


def find(cut, cid):
    for kind in ("spine", "overlays", "audio"):
        for i, c in enumerate(cut.get(kind, [])):
            if c.get("id") == cid:
                return kind, i, c
    raise SystemExit(f"找不到 id: {cid}")


def show(cut):
    fps = fps_of(cut)
    items, total = layout(cut)
    for c, t0, d in items:
        what = "gap" if "gap" in c else f"{Path(c['src']).stem} {c['in']:.3f}–{c['out']:.3f}"
        print(f"{c['id']:>14}  {tc(secs(t0, fps))}  {secs(d, fps):6.2f}s  {what}")
    for kind in ("overlays", "audio"):
        for c in cut.get(kind, []):
            print(f"{c['id']:>14}  {tc(c['at'])}  {c['out'] - c['in']:6.2f}s  "
                  f"{Path(c['src']).stem} {c['in']:.3f}–{c['out']:.3f}  ({kind})")
    print(f"total {tc(secs(total, fps))}")


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawTextHelpFormatter)
    ap.add_argument("cut")
    ap.add_argument("op", choices=["trim", "slip", "delete", "move", "swap", "shift", "gain", "show"])
    ap.add_argument("args", nargs="*")
    ap.add_argument("--head")
    ap.add_argument("--tail")
    ap.add_argument("--before")
    ap.add_argument("--after")
    ap.add_argument("--why", default="")
    ap.add_argument("--by", default="user", choices=["user", "claude"])
    # "-6f" would be read as an option by argparse; shield negative amounts
    argv = [("~" + x[1:]) if re.fullmatch(r"-\d+(\.\d+)?[fs]?", x) else x for x in sys.argv[1:]]
    a = ap.parse_args(argv)

    path = Path(a.cut)
    cut = load_json(path)
    fps = fps_of(cut)
    if a.op == "show":
        return show(cut)
    if not a.args:
        ap.error("需要 id")

    kind, i, c = find(cut, a.args[0])
    before = json.loads(json.dumps(c))
    rec = {"op": a.op, "id": c["id"], "kind": kind}

    if a.op == "trim":
        if a.head is None and a.tail is None:
            ap.error("trim 需要 --head 或 --tail")
        if a.head is not None:
            dh = amount(a.head, fps)
            c["in"] = round(c["in"] + dh, 4)
            rec["head_frames"] = int(round(Fraction(str(dh)) * fps))
            if kind != "spine":
                c["at"] = round(c["at"] + dh, 4)  # keep the rest of the overlay in place
        if a.tail is not None:
            dtl = amount(a.tail, fps)
            c["out"] = round(c["out"] + dtl, 4)
            rec["tail_frames"] = int(round(Fraction(str(dtl)) * fps))
    elif a.op == "slip":
        d = amount(a.args[1], fps)
        c["in"], c["out"] = round(c["in"] + d, 4), round(c["out"] + d, 4)
        rec["frames"] = int(round(Fraction(str(d)) * fps))
    elif a.op == "delete":
        cut[kind].pop(i)
    elif a.op == "move":
        target = a.before or a.after
        if kind != "spine" or not target:
            ap.error("move 只用於 spine，且需要 --before 或 --after")
        cut["spine"].pop(i)
        _, j, _ = find(cut, target)
        cut["spine"].insert(j if a.before else j + 1, c)
        rec["to"] = ("before " if a.before else "after ") + target
    elif a.op == "swap":
        k2, j, c2 = find(cut, a.args[1])
        if kind != "spine" or k2 != "spine":
            ap.error("swap 只用於 spine")
        cut["spine"][i], cut["spine"][j] = c2, c
        rec["with"] = c2["id"]
    elif a.op == "shift":
        if kind == "spine":
            ap.error("spine 片段用 move / swap；shift 只用於 overlays 與 audio")
        d = amount(a.args[1], fps)
        c["at"] = round(max(0.0, c["at"] + d), 4)
        rec["frames"] = int(round(Fraction(str(d)) * fps))
    elif a.op == "gain":
        c["gain_db"] = float(a.args[1])
        rec["gain_db"] = c["gain_db"]

    problems = validate(cut)
    if problems:
        raise SystemExit("編輯後不合法，未寫入：\n  " + "\n  ".join(problems))
    layout(cut)  # raises on non-positive durations
    save_json(path, cut)

    rec.update(ts=dt.datetime.now().isoformat(timespec="seconds"), by=a.by, why=a.why,
               cut=str(path), before=before, after=(None if a.op == "delete" else c),
               role=before.get("role"), note=before.get("note"))
    with (path.parent / "edits.jsonl").open("a", encoding="utf-8") as f:
        f.write(json.dumps(rec, ensure_ascii=False) + "\n")
    print(f"{a.op} {before['id']}: ok" + (f"  ({a.why})" if a.why else ""))
    show(cut)


if __name__ == "__main__":
    main()

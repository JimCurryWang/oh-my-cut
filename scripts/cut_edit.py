#!/usr/bin/env python3
"""Frame-accurate edits to a cut.json. Every edit is appended to edits.jsonl next
to the cut file, so the user's habits are recorded without anyone remembering to.

  cut_edit.py <cut.json> trim    <id> [--head ±N] [--tail ±N]
  cut_edit.py <cut.json> slip    <id> ±N            # move the source window, keep length
  cut_edit.py <cut.json> set     <id> [--in T] [--out T] [--at T]   # absolute times
  cut_edit.py <cut.json> add     --src FILE --in T --out T [--at T]
                                 [--before ID | --after ID] [--kind spine|overlays|audio]
                                 [--id ID] [--role R] [--note "..."] [--gain dB] [--mute]
  cut_edit.py <cut.json> add     --gap T [--before ID | --after ID]
  cut_edit.py <cut.json> replace <id> --src FILE --in T --out T [--role R] [--note "..."]
  cut_edit.py <cut.json> delete  <id>
  cut_edit.py <cut.json> move    <id> --before <id> | --after <id>
  cut_edit.py <cut.json> swap    <id> <id>
  cut_edit.py <cut.json> shift   <overlay/audio id> ±N   # move on the timeline
  cut_edit.py <cut.json> gain    <id> <dB>
  cut_edit.py <cut.json> show

Amounts: "6f" / "-6f" = frames (timeline fps), "0.2s" / "-0.2s" / "0.2" = seconds.
trim --head +N starts the clip N later; --tail -N ends it N earlier.
set/add/replace: --in/--out are seconds inside the SOURCE file, --at is timeline seconds.
add without --kind: has --at -> overlay (audio file -> audio); otherwise spine.
New ids continue the numbering (s7, o3, m2, g2) unless --id is given.
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
from omc_common import (find_episode, fps_of, layout, load_json, save_json, secs,  # noqa: E402
                        tc, validate)

AUDIO_EXT = {".mp3", ".wav", ".m4a", ".aac", ".aif", ".aiff", ".flac", ".ogg", ".opus", ".caf"}
PREFIX = {"spine": "s", "overlays": "o", "audio": "m"}


def amount(text: str, fps: Fraction) -> float:
    """'6f' / '-0.2s' / '-22' -> seconds (frame amounts stay exact multiples of a frame)."""
    t = str(text).strip().lower().replace("~", "-")
    if t.endswith("f"):
        return float(Fraction(int(t[:-1])) / fps)
    return float(t[:-1] if t.endswith("s") else t)


def number(text: str) -> float:
    return float(str(text).strip().replace("~", "-").rstrip("dDbB"))


def frames_of(sec: float, fps: Fraction) -> int:
    return int(round(Fraction(str(sec)) * fps))


def find(cut, cid):
    for kind in ("spine", "overlays", "audio"):
        for i, c in enumerate(cut.get(kind, [])):
            if c.get("id") == cid:
                return kind, i, c
    raise SystemExit(f"找不到 id: {cid}")


def next_id(cut, prefix: str) -> str:
    pat = re.compile(rf"(?:^|/){prefix}(\d+)(?:#\d+)?$")
    n = 0
    for kind in ("spine", "overlays", "audio"):
        for c in cut.get(kind, []):
            m = pat.search(str(c.get("id", "")))
            if m:
                n = max(n, int(m.group(1)))
    return f"{prefix}{n + 1}"


def show(cut, ep=None):
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
    if ep is not None:
        problems = validate(cut, ep)
        if problems:
            print("⚠ 需要修正：\n  " + "\n  ".join(problems))


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawTextHelpFormatter)
    ap.add_argument("cut")
    ap.add_argument("op", choices=["trim", "slip", "set", "add", "replace", "delete", "move",
                                   "swap", "shift", "gain", "show"])
    ap.add_argument("args", nargs="*")
    ap.add_argument("--head")
    ap.add_argument("--tail")
    ap.add_argument("--before")
    ap.add_argument("--after")
    ap.add_argument("--in", dest="in_")
    ap.add_argument("--out")
    ap.add_argument("--at")
    ap.add_argument("--src")
    ap.add_argument("--gap")
    ap.add_argument("--kind", choices=["spine", "overlays", "audio"])
    ap.add_argument("--id")
    ap.add_argument("--role")
    ap.add_argument("--note")
    ap.add_argument("--gain")
    ap.add_argument("--mute", action="store_true")
    ap.add_argument("--why", default="")
    ap.add_argument("--by", default="user", choices=["user", "claude"])
    # "-6f" / "-22" would be read as options by argparse; shield negative amounts
    argv = [("~" + x[1:]) if re.fullmatch(r"-\d+(\.\d+)?([fs]|[dD][bB])?", x) else x for x in sys.argv[1:]]
    a = ap.parse_args(argv)

    path = Path(a.cut)
    cut = load_json(path)
    fps = fps_of(cut)
    ep = find_episode(path)
    if a.op == "show":
        return show(cut, ep)

    def place_in_spine(item, exclude_id=None):
        target = a.before or a.after
        if target:
            if target == exclude_id:
                ap.error("--before/--after 不能指向自己")
            k, j, _ = find(cut, target)
            if k != "spine":
                ap.error("--before/--after 要指向 spine 片段")
            cut["spine"].insert(j if a.before else j + 1, item)
        else:
            cut["spine"].append(item)

    if a.op == "add":
        if a.gap is not None:
            kind = "spine"
            c = {"id": a.id or next_id(cut, "g"), "gap": round(amount(a.gap, fps), 4)}
        else:
            if not (a.src and a.in_ is not None and a.out is not None):
                ap.error("add 需要 --src --in --out（或 --gap）")
            kind = a.kind or (("audio" if Path(a.src).suffix.lower() in AUDIO_EXT else "overlays")
                              if a.at is not None else "spine")
            if kind != "spine" and a.at is None:
                ap.error(f"{kind} 需要 --at（時間軸秒數）")
            c = {"id": a.id or next_id(cut, PREFIX[kind]), "src": a.src,
                 "in": round(amount(a.in_, fps), 4), "out": round(amount(a.out, fps), 4)}
            if kind != "spine":
                c["at"] = round(amount(a.at, fps), 4)
            if a.role:
                c["role"] = a.role
            if a.note:
                c["note"] = a.note
            if a.gain is not None:
                c["gain_db"] = number(a.gain)
            if a.mute:
                c["mute"] = True
        cut.setdefault(kind, [])
        if kind == "spine":
            place_in_spine(c)
        else:
            cut[kind].append(c)
        before = None
        rec = {"op": "add", "id": c["id"], "kind": kind}
        if "src" in c:
            rec["duration_frames"] = frames_of(c["out"], fps) - frames_of(c["in"], fps)
    else:
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
                rec["head_frames"] = frames_of(dh, fps)
                if kind != "spine":
                    c["at"] = round(c["at"] + dh, 4)  # keep the rest of the overlay in place
            if a.tail is not None:
                dtl = amount(a.tail, fps)
                c["out"] = round(c["out"] + dtl, 4)
                rec["tail_frames"] = frames_of(dtl, fps)
        elif a.op == "slip":
            if len(a.args) < 2:
                ap.error("slip 需要格數或秒數")
            d = amount(a.args[1], fps)
            c["in"], c["out"] = round(c["in"] + d, 4), round(c["out"] + d, 4)
            rec["frames"] = frames_of(d, fps)
        elif a.op == "set":
            if "gap" in c:
                if a.out is None and a.gap is None:
                    ap.error("gap 用 set <id> --gap <秒數>")
                c["gap"] = round(amount(a.gap or a.out, fps), 4)
            else:
                if a.in_ is None and a.out is None and a.at is None:
                    ap.error("set 需要 --in、--out 或 --at")
                if a.in_ is not None:
                    new = round(amount(a.in_, fps), 4)
                    rec["head_frames"] = frames_of(new, fps) - frames_of(c["in"], fps)
                    if kind != "spine" and a.at is None:
                        c["at"] = round(c["at"] + new - c["in"], 4)  # tail stays put
                    c["in"] = new
                if a.out is not None:
                    new = round(amount(a.out, fps), 4)
                    rec["tail_frames"] = frames_of(new, fps) - frames_of(c["out"], fps)
                    c["out"] = new
                if a.at is not None:
                    if kind == "spine":
                        ap.error("spine 片段沒有 --at；用 move / swap")
                    c["at"] = round(max(0.0, amount(a.at, fps)), 4)
        elif a.op == "replace":
            if "gap" in c:
                ap.error("gap 不能 replace；先 delete 再 add")
            if not (a.src and a.in_ is not None and a.out is not None):
                ap.error("replace 需要 --src --in --out")
            c["src"] = a.src
            c["in"], c["out"] = round(amount(a.in_, fps), 4), round(amount(a.out, fps), 4)
            if a.role:
                c["role"] = a.role
            if a.note:
                c["note"] = a.note
            rec["from_src"], rec["to_src"] = before["src"], a.src
        elif a.op == "delete":
            cut[kind].pop(i)
        elif a.op == "move":
            if kind != "spine" or not (a.before or a.after):
                ap.error("move 只用於 spine，且需要 --before 或 --after")
            cut["spine"].pop(i)
            place_in_spine(c, exclude_id=c["id"])
            rec["to"] = ("before " if a.before else "after ") + (a.before or a.after)
        elif a.op == "swap":
            if len(a.args) < 2:
                ap.error("swap 需要兩個 id")
            k2, j, c2 = find(cut, a.args[1])
            if kind != "spine" or k2 != "spine":
                ap.error("swap 只用於 spine")
            cut["spine"][i], cut["spine"][j] = c2, c
            rec["with"] = c2["id"]
        elif a.op == "shift":
            if kind == "spine":
                ap.error("spine 片段用 move / swap；shift 只用於 overlays 與 audio")
            if len(a.args) < 2:
                ap.error("shift 需要格數或秒數")
            d = amount(a.args[1], fps)
            c["at"] = round(max(0.0, c["at"] + d), 4)
            rec["frames"] = frames_of(d, fps)
        elif a.op == "gain":
            if len(a.args) < 2:
                ap.error("gain 需要 dB 值，例如 gain m1 -22")
            c["gain_db"] = number(a.args[1])
            rec["gain_db"] = c["gain_db"]

    problems = validate(cut, ep, media=False)
    if ep is not None and a.op != "delete" and "src" in c:
        # the clip just touched must stay inside its source file
        problems += validate({"fps": cut.get("fps"), kind: [c]}, ep, media=True)
    if problems:
        raise SystemExit("編輯後不合法，未寫入：\n  " + "\n  ".join(dict.fromkeys(problems)))
    layout(cut)  # raises on non-positive durations
    save_json(path, cut)

    after = None if a.op == "delete" else c
    ref = before or after
    rec.update(ts=dt.datetime.now().isoformat(timespec="seconds"), by=a.by, why=a.why,
               cut=str(path), before=before, after=after,
               role=ref.get("role"), note=ref.get("note"))
    with (path.parent / "edits.jsonl").open("a", encoding="utf-8") as f:
        f.write(json.dumps(rec, ensure_ascii=False) + "\n")
    print(f"{a.op} {rec['id']}: ok" + (f"  ({a.why})" if a.why else ""))
    show(cut)


if __name__ == "__main__":
    main()

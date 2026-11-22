#!/usr/bin/env python3
"""Hand a cut.json to 剪映 (JianyingPro / CapCut desktop) as a new draft.

  .venv/bin/python scripts/jianying_bridge.py export <cut.json> --episode-dir <ep>
                   [--name NAME] [--drafts DIR]

Needs pyJianYingDraft in .venv (pinned 0.3.1; /setup installs it). Writes a NEW
draft folder and never touches an existing one: if NAME exists the version number
goes up (_v02, _v03...). Media is referenced at its original location (symlinks
resolved), nothing is copied.

  spine     -> main video track, back to back (gaps stay empty)
  overlays  -> video tracks above it (muted unless gain_db is set)
  audio     -> audio tracks (music, sfx)

Getting the edit BACK: 剪映 encrypts its drafts once you save them, so nothing is
read from the draft. Export the finished video and run reconform.py on it.
"""
from __future__ import annotations

import argparse
import datetime as dt
import os
import re
import shutil
import sys
import tempfile
from fractions import Fraction
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from omc_common import fps_of, layout, load_json, resolve, save_json, validate  # noqa: E402

DRAFT_ROOTS = [  # first one that exists wins (剪映專業版, then CapCut desktop)
    "~/Movies/JianyingPro/User Data/Projects/com.lveditor.draft",
    "~/Movies/CapCut/User Data/Projects/com.lveditor.draft",
]


def draft_root(explicit: str | None) -> Path:
    for c in ([explicit] if explicit else DRAFT_ROOTS):
        p = Path(os.path.expanduser(c))
        if p.is_dir():
            return p
    raise SystemExit("找不到剪映的草稿資料夾；用 --drafts 指定（剪映：設定 > 草稿位置）")


def free_name(root: Path, base: str) -> str:
    m = re.search(r"_v(\d+)$", base)
    stem, n = (base[:m.start()], int(m.group(1))) if m else (base, 1)
    while (root / f"{stem}_v{n:02d}").exists():
        n += 1
    return f"{stem}_v{n:02d}"


def pack(items):
    """Greedy lanes so that nothing overlaps inside one track."""
    lanes = []
    for it in sorted(items, key=lambda x: x[0]):
        for lane in lanes:
            if lane[-1][1] <= it[0]:
                lane.append(it)
                break
        else:
            lanes.append([it])
    return lanes


def volume(c, default):
    if c.get("mute"):
        return 0.0
    if "gain_db" in c and c["gain_db"] is not None:
        return round(10 ** (float(c["gain_db"]) / 20), 4)
    return default


def do_export(a):
    try:
        import pyJianYingDraft as jy
    except ImportError:
        raise SystemExit("需要 pyJianYingDraft：用 .venv/bin/python 執行，或先 /setup")
    cut_path, ep = Path(a.cut), Path(a.episode_dir).resolve()
    cut = load_json(cut_path)
    problems = validate(cut, ep)
    if problems:
        raise SystemExit("cut.json 有問題：\n  " + "\n  ".join(problems))
    fps = fps_of(cut)
    w, h = cut.get("size", [1920, 1080])
    items, total = layout(cut)
    US = 1_000_000

    def us(frame) -> int:  # timeline frame -> microseconds, from the origin (no drift)
        return int(round(Fraction(frame) / fps * US))

    def src_path(c) -> str:
        return str(resolve(ep, c["src"], proxy=False).resolve())

    root = draft_root(a.drafts)
    base = a.name or f"{ep.name}_粗剪"
    name = free_name(root, base)
    has_gaps = any("gap" in c for c, _, _ in items)
    # build the whole draft in a temp folder and move it in only when it is complete:
    # a failure must never leave a half-written draft in 剪映's list
    tmp = Path(tempfile.mkdtemp(prefix="omc_jianying_"))
    script = jy.DraftFolder(str(tmp)).create_draft(
        name, int(w), int(h), fps=int(round(float(fps))), maintrack_adsorb=not has_gaps)

    overlays, audios = [], []
    for c in cut.get("overlays", []):
        f0 = int(round(Fraction(str(c["at"])) * fps))
        f1 = f0 + int(round(Fraction(str(c["out"])) * fps)) - int(round(Fraction(str(c["in"])) * fps))
        overlays.append((f0, f1, c))
    for c in cut.get("audio", []):
        f0 = int(round(Fraction(str(c["at"])) * fps))
        f1 = f0 + int(round(Fraction(str(c["out"])) * fps)) - int(round(Fraction(str(c["in"])) * fps))
        audios.append((f0, f1, c))
    ov_lanes, au_lanes = pack(overlays), pack(audios)

    # background -> foreground: main, overlays..., then audio
    specs = [jy.TrackSpec(jy.TrackType.video, "main")]
    specs += [jy.TrackSpec(jy.TrackType.video, f"broll{i + 1}") for i in range(len(ov_lanes))]
    specs += [jy.TrackSpec(jy.TrackType.audio, f"audio{i + 1}") for i in range(len(au_lanes))]
    script.append_tracks(specs)

    mats, clamped = {}, []

    def segment(kind, c, f0, f1, vol):
        path = src_path(c)
        if (kind, path) not in mats:  # 剪映's own idea of the file length (via MediaInfo)
            mats[(kind, path)] = (jy.VideoMaterial if kind == "video" else jy.AudioMaterial)(path)
        m = mats[(kind, path)]
        start, dur = int(round(float(c["in"]) * US)), us(f1) - us(f0)
        over = start + dur - m.duration
        if over > 0:  # a clip cut right at the end of its file: lose the last frame or two
            dur -= over
            clamped.append((c["id"], over / US))
        cls = jy.VideoSegment if kind == "video" else jy.AudioSegment
        return cls(m, jy.Timerange(us(f0), dur), source_timerange=jy.Timerange(start, dur),
                   volume=vol)  # source and target the same length: speed exactly 1

    for c, t0, d in items:
        if "gap" not in c:
            script.add_segment(segment("video", c, t0, t0 + d, volume(c, 1.0)), "main")
    for i, lane in enumerate(ov_lanes):
        for f0, f1, c in lane:
            script.add_segment(segment("video", c, f0, f1, volume(c, 0.0)), f"broll{i + 1}")
    for i, lane in enumerate(au_lanes):
        for f0, f1, c in lane:
            script.add_segment(segment("audio", c, f0, f1, volume(c, 1.0)), f"audio{i + 1}")
    script.save()
    shutil.copy(tmp / name / "draft_content.json", tmp / name / "draft_info.json")  # Mac reads draft_info
    d = root / name
    if d.exists():
        raise SystemExit(f"{d} 剛剛出現了同名草稿，沒有覆蓋；暫存在 {tmp}")
    shutil.move(str(tmp / name), str(d))
    shutil.rmtree(tmp, ignore_errors=True)
    record = {"editor": "jianying", "draft": name, "draft_dir": str(d), "cut": str(cut_path),
              "exported_at": dt.datetime.now().isoformat(timespec="seconds")}
    save_json(ep / "work" / "refine" / "handoff.json", record)

    print(f"剪映草稿：{name}  （{len(items)} 段主軌、{len(overlays)} 個疊加畫面、{len(audios)} 段音訊，"
          f"{float(total / fps):.2f}s）")
    print(f"  位置：{d}")
    for cid, sec in clamped:
        print(f"  {cid}：素材在剪映量到的長度較短，結尾少了 {sec * 1000:.0f} ms")
    if has_gaps:
        print("  主軌有空白，所以這份草稿關閉了「主軌磁吸」，需要時可在剪映裡打開")
    for s in cut.get("sections", []):
        print(f"  段落 {s['name']} 從 {float(s['at']):.2f}s 開始")
    print("下一步：打開剪映（已開著就先回到首頁）→ 草稿列表找到它 → 精修 → 匯出成片 → /refine import")


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawTextHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    e = sub.add_parser("export")
    e.add_argument("cut")
    e.add_argument("--episode-dir", required=True)
    e.add_argument("--name", help="draft name (default <episode>_粗剪_vNN)")
    e.add_argument("--drafts", help="剪映 draft folder (default: auto-detect)")
    a = ap.parse_args()
    do_export(a)


if __name__ == "__main__":
    main()

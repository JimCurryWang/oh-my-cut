#!/usr/bin/env python3
"""The memory of your taste. Raw evidence in, numbers out; /learn turns the
numbers into rules (and only you approve a rule).

  decide.py log --episode EP [--sequence SEQ] --type ab|revision|note
                --context "..." [--proposed "..."] --chosen "..." [--reason "..."]
                [--key short-rule-key]
        append one decision to taste/_me/decisions.jsonl

  decide.py report [--episode EP]
        aggregate every source of evidence:
          taste/_me/decisions.jsonl                       A/B picks, spoken feedback
          video_editor/*/work/**/edits.jsonl              chat micro-adjustments (cut_edit.py)
          video_editor/*/work/refine/diff*.json           what you changed in your editor
          video_editor/*/work/fcp/diff*.json              (older episodes)
        prints counts per rule key and trim habits; keys seen >= 3 times in >= 2
        sequences are flagged as rule candidates.
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import statistics
import sys
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
LOG = ROOT / "taste" / "_me" / "decisions.jsonl"


def read_jsonl(p: Path):
    if not p.exists():
        return []
    return [json.loads(x) for x in p.read_text(encoding="utf-8").splitlines() if x.strip()]


def do_log(a):
    rec = {"ts": dt.datetime.now().isoformat(timespec="seconds"), "episode": a.episode,
           "sequence": a.sequence, "type": a.type, "key": a.key, "context": a.context,
           "proposed": a.proposed, "chosen": a.chosen, "reason": a.reason}
    LOG.parent.mkdir(parents=True, exist_ok=True)
    with LOG.open("a", encoding="utf-8") as f:
        f.write(json.dumps(rec, ensure_ascii=False) + "\n")
    print(f"logged [{a.type}] {a.key or ''} {a.chosen}")


def do_report(a):
    eps = sorted(p for p in (ROOT / "video_editor").glob("*") if p.is_dir()
                 and (a.episode is None or p.name == a.episode))

    print("# Taste evidence report\n")
    decisions = [d for d in read_jsonl(LOG) if a.episode in (None, d.get("episode"))]
    by_key = defaultdict(list)
    for d in decisions:
        by_key[d.get("key") or "(no key)"].append(d)
    print(f"## 決策日誌：{len(decisions)} 筆")
    for key, ds in sorted(by_key.items(), key=lambda kv: -len(kv[1])):
        where = {(d.get("episode"), d.get("sequence")) for d in ds}
        chosen = defaultdict(int)
        for d in ds:
            chosen[d.get("chosen")] += 1
        top, n = max(chosen.items(), key=lambda kv: kv[1])
        flag = "  ← 規則候選" if key != "(no key)" and n >= 3 and len(where) >= 2 else ""
        print(f"- {key}: {len(ds)} 次 / {len(where)} 個段落；最常選「{top}」{n} 次{flag}")

    edits = []
    for ep in eps:
        for p in ep.glob("work/**/edits.jsonl"):
            edits += [{**e, "episode": ep.name} for e in read_jsonl(p)]
    user = [e for e in edits if e.get("by") == "user"]
    print(f"\n## 對話微調：{len(user)} 次（另有 Claude 自己的 {len(edits) - len(user)} 次，不計）")
    ops = defaultdict(int)
    for e in user:
        ops[e["op"]] += 1
    if ops:
        print("- 操作：" + "、".join(f"{k} {v}" for k, v in sorted(ops.items(), key=lambda kv: -kv[1])))
    heads = [e["head_frames"] for e in user if e.get("head_frames")]
    tails = [e["tail_frames"] for e in user if e.get("tail_frames")]
    for name, v in (("開頭", heads), ("尾巴", tails)):
        if v:
            tight = len([x for x in v if (x > 0) == (name == "開頭")])
            print(f"- {name}修剪 {len(v)} 次：收緊 {tight}、放長 {len(v) - tight}，"
                  f"中位數 {statistics.median(v):+g} 格")
    deleted = [e for e in user if e["op"] == "delete"]
    if deleted:
        roles = defaultdict(int)
        for e in deleted:
            roles[e.get("role") or "未標 role"] += 1
        print("- 刪除的片段：" + "、".join(f"{k} {v}" for k, v in roles.items()))
    added = [e for e in user if e["op"] in ("add", "replace")]
    if added:
        roles = defaultdict(int)
        for e in added:
            roles[e.get("role") or "未標 role"] += 1
        print("- 你補上或換掉的片段（我漏選的素材）：" + "、".join(f"{k} {v}" for k, v in roles.items()))
    whys = [e["why"] for e in user if e.get("why")]
    if whys:
        print("- 你給過的理由：")
        for w in whys[-15:]:
            print(f"    · {w}")

    print("\n## 剪輯軟體精修")
    found = False
    for ep in eps:
        for p in sorted(ep.glob("work/refine/diff*.json")) + sorted(ep.glob("work/fcp/diff*.json")):
            found = True
            d = json.loads(p.read_text(encoding="utf-8"))
            h, s = d["habits"], d["stats"]["spine"]
            print(f"- {ep.name}/{p.name}: 長度 {h['duration_change_pct']:+}%；"
                  f"spine 刪 {s['removed']}/{s['ours']}、加 {s['added']}；"
                  f"尾巴收緊 {h['tails_tightened']}／放長 {h['tails_extended']}"
                  f"（平均 {h['mean_tail_frames']:+} 格）；"
                  f"開頭收緊 {h['heads_tightened']}／放長 {h['heads_extended']}"
                  f"（平均 {h['mean_head_frames']:+} 格）")
            un = defaultdict(int)
            for u in d.get("unparsed", []):
                un[u["tag"]] += 1
            if un:
                print("    你在剪輯軟體另外加了／我認不出來的：" + "、".join(f"{k}×{v}" for k, v in un.items()))
    if not found:
        print("- 尚無（跑過 /refine import 之後才會有）")
    print("\n規則門檻：同一個 key 的同一選擇 ≥ 3 次、且出現在 ≥ 2 個段落，才提議寫進 preferences.md。")


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawTextHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    lg = sub.add_parser("log")
    lg.add_argument("--episode", required=True)
    lg.add_argument("--sequence")
    lg.add_argument("--type", required=True, choices=["ab", "revision", "note"])
    lg.add_argument("--key", help="short stable key, e.g. hook-length, caption-size, broll-ratio")
    lg.add_argument("--context", required=True)
    lg.add_argument("--proposed")
    lg.add_argument("--chosen", required=True)
    lg.add_argument("--reason")
    rp = sub.add_parser("report")
    rp.add_argument("--episode")
    a = ap.parse_args()
    (do_log if a.cmd == "log" else do_report)(a)


if __name__ == "__main__":
    sys.exit(main())

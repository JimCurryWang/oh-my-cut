#!/usr/bin/env python3
"""Render a cut.json with FFmpeg: a low-res review preview (default) or the final file.

  render_cut.py <cut.json> --episode-dir <ep> [-o preview.mp4] [--height 480]
                           [--no-burn] [--no-sheet]
  render_cut.py <cut.json> --episode-dir <ep> --final -o exports/ep_v01.mp4
                           [--overlay-mov captions.mov ...] [--lut look.cube] [--lufs -14]

Burns clip ids + timeline timecode into the picture so feedback can be precise
("s7 尾巴少 6 格"). Also writes <output>.sheet.jpg: one frame per spine clip, in
order, for QC without watching. Preview only: overlay audio is muted unless the
overlay has gain_db.

--final uses the ORIGINAL media at the cut's full size, no burn-in, composites
transparent overlay movies (captions / graphics rendered by the overlay engine,
same length as the timeline) on top, applies an optional LUT to the footage only,
and normalises loudness. HDR sources are not tone-mapped here — finish those in
Final Cut.
"""
from __future__ import annotations

import argparse
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from omc_common import (fps_of, layout, load_json, probe, resolve, run,  # noqa: E402
                        secs, tc, validate)

AAC = ["-c:a", "aac", "-b:a", "192k", "-ar", "48000", "-ac", "2"]


def x264(crf: int, preset: str):
    return ["-c:v", "libx264", "-preset", preset, "-crf", str(crf), "-pix_fmt", "yuv420p"]


def drawtext_ok() -> bool:
    return " drawtext " in run(["ffmpeg", "-hide_banner", "-filters"]).stdout


def label(text: str, y: str, size: int) -> str:
    text = text.replace("\\", "").replace(":", "\\:").replace("'", "")
    return (f"drawtext=text='{text}':x=8:y={y}:fontsize={size}:fontcolor=white:"
            "box=1:boxcolor=black@0.55")


def fit(w: int, h: int, fps) -> str:
    return (f"scale={w}:{h}:force_original_aspect_ratio=decrease,"
            f"pad={w}:{h}:(ow-iw)/2:(oh-ih)/2,fps={fps.numerator}/{fps.denominator},setsar=1")


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawTextHelpFormatter)
    ap.add_argument("cut")
    ap.add_argument("--episode-dir", required=True)
    ap.add_argument("-o", "--output")
    ap.add_argument("--height", type=int, default=480)
    ap.add_argument("--no-burn", action="store_true")
    ap.add_argument("--no-sheet", action="store_true")
    ap.add_argument("--final", action="store_true")
    ap.add_argument("--overlay-mov", action="append", default=[])
    ap.add_argument("--lut")
    ap.add_argument("--lufs", type=float)
    a = ap.parse_args()

    cut_path, ep = Path(a.cut), Path(a.episode_dir)
    cut = load_json(cut_path)
    problems = validate(cut, ep)
    if problems:
        raise SystemExit("cut.json 有問題：\n  " + "\n  ".join(problems))
    fps = fps_of(cut)
    cw, ch = cut.get("size", [1920, 1080])
    if a.final:
        w, h = cw, ch
        if not a.output:
            raise SystemExit("--final 需要 -o（不要覆蓋舊版本，用 _v01, _v02 …）")
        if Path(a.output).exists():
            raise SystemExit(f"{a.output} 已存在；換一個版本號")
    else:
        h = a.height - a.height % 2
        w = int(round(h * cw / ch / 2)) * 2
    out = Path(a.output) if a.output else cut_path.with_name(cut_path.stem + ".preview.mp4")
    burn = (not a.no_burn) and (not a.final) and drawtext_ok()
    proxy = not a.final
    seg_enc = x264(12, "veryfast") if a.final else x264(25, "veryfast")   # intermediate
    out_enc = x264(18, "medium") if a.final else x264(25, "veryfast")
    lufs = a.lufs if a.lufs is not None else (-14.0 if a.final else None)
    items, total = layout(cut)
    total_s = float(total / fps)

    with tempfile.TemporaryDirectory(prefix="omc_") as tmp:
        tmp = Path(tmp)
        concat = []
        for i, (c, t0, d) in enumerate(items):
            seg, dur = tmp / f"seg_{i:04d}.mp4", float(d / fps)
            vf = fit(w, h, fps)
            if burn:
                name = "gap" if "gap" in c else Path(c["src"]).stem
                vf += "," + label(f"{c['id']}  {name}", "8", max(12, h // 26))
            if "gap" in c:
                cmd = ["ffmpeg", "-y", "-v", "error",
                       "-f", "lavfi", "-t", f"{dur:.4f}", "-i", f"color=c=black:s={w}x{h}",
                       "-f", "lavfi", "-t", f"{dur:.4f}", "-i", "anullsrc=r=48000:cl=stereo",
                       "-vf", vf]
            else:
                src = resolve(ep, c["src"], proxy)
                info = probe(src)
                cmd = ["ffmpeg", "-y", "-v", "error", "-ss", f"{float(c['in']):.4f}",
                       "-t", f"{dur + 0.5:.4f}", "-i", src]
                if info["has_audio"] and not c.get("mute"):
                    cmd += ["-af", f"aresample=48000,volume={float(c.get('gain_db', 0))}dB"]
                else:
                    cmd += ["-f", "lavfi", "-t", f"{dur:.4f}", "-i",
                            "anullsrc=r=48000:cl=stereo", "-map", "0:v:0", "-map", "1:a:0"]
                cmd += ["-vf", vf]
            run(cmd + ["-frames:v", d, "-t", f"{dur:.4f}", *seg_enc, *AAC, seg])
            concat.append(f"file '{seg}'\n")
        (tmp / "list.txt").write_text("".join(concat))
        base = tmp / "base.mp4"
        run(["ffmpeg", "-y", "-v", "error", "-f", "concat", "-safe", "0",
             "-i", tmp / "list.txt", "-c", "copy", base])

        inputs, fc, vlast, amix, n = ["-i", base], [], "[0:v]", ["[0:a]"], 1
        for o in cut.get("overlays", []):
            dur = float(o["out"]) - float(o["in"])
            at = float(o["at"])
            inputs += ["-ss", f"{float(o['in']):.4f}", "-t", f"{dur:.4f}", "-i", resolve(ep, o["src"], proxy)]
            vf = f"[{n}:v]{fit(w, h, fps)}"
            if burn:
                vf += "," + label(f"{o['id']}  {Path(o['src']).stem}", "h-th-8", max(12, h // 26))
            fc.append(f"{vf},setpts=PTS-STARTPTS+{at:.4f}/TB[ov{n}]")
            fc.append(f"{vlast}[ov{n}]overlay=eof_action=pass:"
                      f"enable='between(t,{at:.4f},{at + dur:.4f})'[v{n}]")
            vlast = f"[v{n}]"
            if "gain_db" in o and probe(resolve(ep, o["src"], proxy))["has_audio"]:
                fc.append(f"[{n}:a]aresample=48000,volume={float(o['gain_db'])}dB,"
                          f"adelay={int(at * 1000)}:all=1[a{n}]")
                amix.append(f"[a{n}]")
            n += 1
        for m in cut.get("audio", []):
            dur = float(m["out"]) - float(m["in"])
            inputs += ["-ss", f"{float(m['in']):.4f}", "-t", f"{dur:.4f}", "-i", resolve(ep, m["src"], proxy)]
            fc.append(f"[{n}:a]aresample=48000,volume={float(m.get('gain_db', 0))}dB,"
                      f"adelay={int(float(m['at']) * 1000)}:all=1[a{n}]")
            amix.append(f"[a{n}]")
            n += 1
        if a.lut:
            lut = str(Path(a.lut).resolve()).replace("\\", "/").replace(":", "\\:").replace("'", "")
            fc.append(f"{vlast}lut3d=file='{lut}'[vlut]")
            vlast = "[vlut]"
        for mov in a.overlay_mov:
            inputs += ["-i", mov]
            fc.append(f"[{n}:v]scale={w}:{h},setsar=1[gfx{n}]")
            fc.append(f"{vlast}[gfx{n}]overlay=eof_action=pass:format=auto[vg{n}]")
            vlast = f"[vg{n}]"
            n += 1
        if a.final and vlast == "[0:v]":
            fc.append("[0:v]null[vnull]")
            vlast = "[vnull]"
        if burn:
            fc.append(f"{vlast}drawtext=text='%{{pts\\:hms}}':x=w-tw-8:y=8:"
                      f"fontsize={max(12, h // 26)}:fontcolor=white:box=1:boxcolor=black@0.55[vtc]")
            vlast = "[vtc]"

        out.parent.mkdir(parents=True, exist_ok=True)
        if not fc:
            run(["ffmpeg", "-y", "-v", "error", "-i", base, "-c", "copy",
                 "-movflags", "+faststart", out])
        else:
            maps = ["-map", vlast if vlast != "[0:v]" else "0:v"]
            norm = f"loudnorm=I={lufs}:TP=-1.5:LRA=11," if lufs is not None else ""
            mix = (f"amix=inputs={len(amix)}:normalize=0:duration=first," if len(amix) > 1
                   else "")
            fc.append("".join(amix) + f"{mix}{norm}aresample=48000[aout]")
            maps += ["-map", "[aout]"]
            run(["ffmpeg", "-y", "-v", "error", *inputs, "-filter_complex", ";".join(fc),
                 *maps, "-t", f"{total_s:.4f}", *out_enc, *AAC, "-movflags", "+faststart", out])

        if not a.no_sheet and items:
            mids = [t0 + d // 2 for _, t0, d in items]
            sel = "+".join(f"eq(n\\,{m})" for m in mids)
            cols = min(6, len(mids))
            rows = -(-len(mids) // cols)
            sheet = out.with_suffix(".sheet.jpg")
            run(["ffmpeg", "-y", "-v", "error", "-i", out, "-an",
                 "-vf", f"select='{sel}',scale=320:-2,tile={cols}x{rows}",
                 "-frames:v", "1", "-q:v", "4", sheet], check=False)

    print(f"{'final' if a.final else 'preview'}: {out}  ({tc(total_s)}, {len(items)} clips, "
          f"{len(cut.get('overlays', []))} overlays, {len(cut.get('audio', []))} audio)")
    print("| id | timeline | 長度 | src | in–out |\n|---|---|---|---|---|")
    for c, t0, d in items:
        s = "gap" if "gap" in c else f"{Path(c['src']).stem} | {c['in']:.2f}–{c['out']:.2f}"
        if "gap" in c:
            s = "gap | -"
        print(f"| {c['id']} | {tc(secs(t0, fps))} | {secs(d, fps):.2f}s | {s} |")
    for o in cut.get("overlays", []):
        print(f"| {o['id']} (overlay) | {tc(o['at'])} | {o['out'] - o['in']:.2f}s | "
              f"{Path(o['src']).stem} | {o['in']:.2f}–{o['out']:.2f} |")


if __name__ == "__main__":
    main()

#!/usr/bin/env python3
"""Reconstruct the edit from the finished video, whatever editor made it.

  .venv/bin/python scripts/reconform.py <final.mp4> --cut <ours.json> --episode-dir <ep>
                   -o <theirs.json> [--pool cut|all] [--music FILE ...]

Some editors (剪映 / CapCut) keep their projects encrypted, so the only honest record
of what the user did is the video they exported. This finds, for every frame of it,
which source and which moment it came from, and writes that back as a cut.json that
cut_diff.py can compare with what we handed over.

  1. audio fingerprints (spectral-peak pairs) of every source and of the final ->
     which source, at which offset, plays where. Robust to music underneath, loudness
     normalisation and EQ.
  2. exact offsets by waveform cross-correlation; overlaps resolved by match density.
  3. cut points refined frame by frame with picture + sound similarity.
  4. frames whose picture does not match the clip underneath (B-roll on top) and
     stretches with no audio match (B-roll on the main track) are searched visually
     among the episode's footage.
  5. ids are carried over from ours.json by source overlap, so a trimmed clip keeps
     its id and a split clip comes back as id, id#2 (origin = id).

Speed changes, heavy zoom/crop and effects are not recognised: those stretches are
listed under "unparsed" instead of being guessed. Gains are not measured.
Needs numpy (.venv).
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from fractions import Fraction
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).parent))
from omc_common import load_json, probe, resolve, save_json, tc, tool  # noqa: E402

SR, NFFT, HOP = 8000, 512, 128            # 16 ms hops
FN, TN = 10, 8                            # peak neighbourhood: ±156 Hz, ±128 ms
FANOUT, DT_MAX, DF_MAX = 6, 63, 96         # landmark pairs
MAX_OCC = 40                               # ignore hashes this common in the sources
MIN_VOTES, RUN_GAP_S = 6, 1.5
TW, TH, ROWS = 48, 27, slice(2, 21)        # thumbnails; rows skip top 7% / bottom 22% (captions)
VIDEO_EXT = {".mov", ".mp4", ".m4v", ".mkv", ".mts", ".m2ts", ".avi", ".webm", ".mxf", ".insv"}


# ---------------------------------------------------------------- decoding
def audio_of(path) -> np.ndarray:
    r = subprocess.run([tool("ffmpeg"), "-v", "error", "-i", str(path), "-vn", "-ac", "1",
                        "-ar", str(SR), "-f", "f32le", "-"], capture_output=True)
    return np.frombuffer(r.stdout, np.float32).copy()


def thumbs(path, fps: Fraction, start=0.0, dur=None):
    """Unit-norm grey thumbnails (dot product = normalised correlation) + flat mask."""
    cmd = [tool("ffmpeg"), "-v", "error"]
    if start > 0:
        cmd += ["-ss", f"{start:.4f}"]
    if dur is not None:
        cmd += ["-t", f"{dur:.4f}"]
    cmd += ["-i", str(path), "-an", "-vf",
            f"fps={fps.numerator}/{fps.denominator},scale={TW}:{TH}:flags=area,format=gray",
            "-f", "rawvideo", "-"]
    raw = subprocess.run(cmd, capture_output=True).stdout
    a = np.frombuffer(raw, np.uint8)[: len(raw) // (TW * TH) * TW * TH]
    a = a.reshape(-1, TH, TW)[:, ROWS, :].reshape(-1, (ROWS.stop - ROWS.start) * TW).astype(np.float32)
    sd = a.std(1, keepdims=True)
    flat = sd[:, 0] < 4.0
    a = (a - a.mean(1, keepdims=True)) / np.maximum(sd, 1e-3) / np.sqrt(a.shape[1])
    return a, flat


def quiet_level(x: np.ndarray) -> float:
    """Below this a 1-frame window counts as silence: 20 dB under the file's typical
    loudness (recordings range from -15 to -50 dBFS, so no absolute threshold works)."""
    if len(x) < SR:
        return 1e-5
    w = x[: len(x) // 800 * 800].reshape(-1, 800).std(1)
    return max(1e-5, 0.1 * float(np.percentile(w, 75)))


# ---------------------------------------------------------------- fingerprints
def _maxfilt(S, r, axis):
    pad = [(0, 0), (0, 0)]
    pad[axis] = (r, r)
    P = np.pad(S, pad, constant_values=-np.inf)
    return np.lib.stride_tricks.sliding_window_view(P, 2 * r + 1, axis=axis).max(axis=-1)


def landmarks(x: np.ndarray):
    """(hash, hop index) pairs from spectral peaks, computed in chunks to bound memory."""
    win = np.hanning(NFFT).astype(np.float32)
    n = 0 if len(x) < NFFT else 1 + (len(x) - NFFT) // HOP
    pt, pf = [], []
    CH, PADF = 12000, TN + 2
    for c0 in range(0, n, CH):
        a0, a1 = max(0, c0 - PADF), min(n, c0 + CH + PADF)
        fr = np.lib.stride_tricks.sliding_window_view(x, NFFT)[a0 * HOP:(a1 - 1) * HOP + 1:HOP]
        S = 20 * np.log10(np.abs(np.fft.rfft(fr * win, axis=1)) + 1e-6)
        S[:, :4] = -120  # drop DC / rumble
        m = _maxfilt(_maxfilt(S, FN, 1), TN, 0)
        thr = np.percentile(S, 85)
        t, f = np.nonzero((S == m) & (S > thr) & (S > -40))
        t = t + a0
        keep = (t >= c0) & (t < min(n, c0 + CH))
        pt.append(t[keep])
        pf.append(f[keep])
    t = np.concatenate(pt) if pt else np.zeros(0, int)
    f = np.concatenate(pf) if pf else np.zeros(0, int)
    o = np.lexsort((f, t))
    t, f = t[o].astype(np.int64), f[o].astype(np.int64)
    hs, ts = [], []
    taken = np.zeros(len(t), int)
    for k in range(1, 48):
        i = np.arange(max(0, len(t) - k))
        j = i + k
        dt = t[j] - t[i]
        ok = (dt >= 1) & (dt <= DT_MAX) & (np.abs(f[j] - f[i]) <= DF_MAX) & (taken[i] < FANOUT)
        i, j = i[ok], j[ok]
        taken[i] += 1
        hs.append((f[i] << 16) | (f[j] << 7) | (t[j] - t[i]))
        ts.append(t[i])
    if not hs:
        return np.zeros(0, np.int64), np.zeros(0, np.int64)
    return np.concatenate(hs), np.concatenate(ts)


class Index:
    def __init__(self):
        self.h, self.t, self.s = [], [], []

    def add(self, sid, x):
        h, t = landmarks(x)
        self.h.append(h)
        self.t.append(t)
        self.s.append(np.full(len(h), sid, np.int32))

    def build(self):
        h = np.concatenate(self.h) if self.h else np.zeros(0, np.int64)
        o = np.argsort(h, kind="stable")
        self.H = h[o]
        self.T = np.concatenate(self.t)[o] if self.t else np.zeros(0, np.int64)
        self.S = np.concatenate(self.s)[o] if self.s else np.zeros(0, np.int32)

    def match(self, qh, qt):
        lo = np.searchsorted(self.H, qh, "left")
        hi = np.searchsorted(self.H, qh, "right")
        cnt = hi - lo
        ok = (cnt > 0) & (cnt <= MAX_OCC)
        lo, cnt, qt = lo[ok], cnt[ok], qt[ok]
        if not len(cnt):
            return np.zeros(0, np.int64), np.zeros(0, np.int32), np.zeros(0, np.int64)
        rep = np.repeat(np.arange(len(cnt)), cnt)
        pos = lo[rep] + (np.arange(cnt.sum()) - np.repeat(np.cumsum(cnt) - cnt, cnt))
        return qt[rep], self.S[pos], self.T[pos] - qt[rep]   # final hop, source id, offset (hops)


def candidates(qt, src, off, gap_hops, min_votes, allowed):
    """(src, offset) hypotheses with enough votes, split into runs along the final."""
    sel = np.isin(src, list(allowed))
    qt, src, off = qt[sel], src[sel], off[sel]
    if not len(qt):
        return []
    key = src.astype(np.int64) * (1 << 32) + (off + (1 << 31))
    uk, uc = np.unique(key, return_counts=True)
    order = np.argsort(-uc)
    used, out = set(), []
    for k, c in zip(uk[order], uc[order]):
        if c < min_votes or int(k) in used:
            continue
        s, o = int(k >> 32), int((k & 0xFFFFFFFF) - (1 << 31))
        group = (src == s) & (np.abs(off - o) <= 1)
        for dk in (-1, 0, 1):
            used.add(int(k) + dk)
        times = np.sort(qt[group])
        if not len(times):
            continue
        cuts = np.nonzero(np.diff(times) > gap_hops)[0]
        for seg in np.split(times, cuts + 1):
            if len(seg) >= min_votes and seg[-1] - seg[0] >= 12:
                out.append({"src": s, "off_hops": o, "q0": int(seg[0]), "q1": int(seg[-1]),
                            "votes": int(len(seg))})
    return out


def refine_offset(final_a, src_a, c):
    """Exact sample offset by normalised cross-correlation over the densest 3 s."""
    q0, q1 = c["q0"] * HOP, c["q1"] * HOP + NFFT
    mid = (q0 + q1) // 2
    y0, y1 = max(q0, mid - 12000), min(q1, mid + 12000)
    y = final_a[y0:y1]
    base, R = c["off_hops"] * HOP, 2 * HOP
    x0 = y0 + base - R
    if x0 < 0 or x0 + len(y) + 2 * R > len(src_a) or len(y) < 800 or np.std(y) < 1e-4:
        return base
    x = src_a[x0:x0 + len(y) + 2 * R]
    yc = (y - y.mean()) / (np.linalg.norm(y - y.mean()) + 1e-9)
    win = np.lib.stride_tricks.sliding_window_view(x, len(y))
    num = win @ yc
    den = np.sqrt(np.maximum((win ** 2).sum(1) - len(y) * win.mean(1) ** 2, 1e-12))
    return base - R + int(np.argmax(num / den))


# ---------------------------------------------------------------- similarity
class Sim:
    """Per-frame similarity of the final to one hypothesis (source + offset)."""

    def __init__(self, ctx, sid, off_s):
        self.ctx, self.sid, self.off_s = ctx, sid, off_s
        self.cache = {}

    def frames(self, a, b):
        ctx = self.ctx
        a, b = max(0, a), min(ctx.N, b)
        key = (a, b)
        if key in self.cache:
            return self.cache[key]
        fps = ctx.fps
        t0 = float(a / fps) + self.off_s
        st = max(0.0, t0)
        lead = int(round((st - t0) * float(fps)))
        src = ctx.sources[self.sid]
        v = np.full(b - a, np.nan, np.float32)
        if src["video"]:
            th, flat = thumbs(src["path"], fps, st, float((b - a) / fps) + 0.2)
            n = min(len(th), b - a - lead)
            if n > 0:
                F, Ff = ctx.final_th[a + lead:a + lead + n], ctx.final_flat[a + lead:a + lead + n]
                d = (F * th[:n]).sum(1)
                d[Ff | flat[:n]] = np.nan
                v[lead:lead + n] = d
        au = np.full(b - a, np.nan, np.float32)
        sa, fa = src["audio"], ctx.final_audio
        spf = SR / float(fps)
        osmp = int(round(self.off_s * SR))
        for i, f in enumerate(range(a, b)):
            y0, y1 = int(f * spf), int((f + 1) * spf)
            x0, x1 = y0 + osmp, y1 + osmp
            if x0 < 0 or x1 > len(sa) or y1 > len(fa):
                continue
            y, x = fa[y0:y1], sa[x0:x1]
            if y.std() < ctx.final_quiet or x.std() < src["quiet"]:
                continue  # silence, relative to that file's own level
            au[i] = float(np.corrcoef(x, y)[0, 1])
        self.cache[key] = (v, au)
        return v, au

    def score(self, a, b):
        v, au = self.frames(a, b)
        return np.nan_to_num(v, nan=0.0) + np.nan_to_num(au, nan=0.0)


# ---------------------------------------------------------------- main
class Ctx:
    pass


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawTextHelpFormatter)
    ap.add_argument("final")
    ap.add_argument("--cut", required=True, help="the cut.json we handed over (ours)")
    ap.add_argument("--episode-dir", required=True)
    ap.add_argument("-o", "--output", required=True)
    ap.add_argument("--pool", choices=["cut", "all"], default="all",
                    help="search only the cut's sources, or all of the episode's footage (default)")
    ap.add_argument("--music", nargs="*", default=[], help="extra music/sfx files to look for")
    a = ap.parse_args()

    ep = Path(a.episode_dir).resolve()
    ours = load_json(a.cut)
    fin = probe(a.final)
    if not fin["has_video"]:
        raise SystemExit("成片沒有影像")
    ctx = Ctx()
    ctx.fps = Fraction(*fin["fps"])

    # ---- sources: everything the cut uses, plus the episode's footage
    srcs = {}
    for kind in ("spine", "overlays", "audio"):
        for c in ours.get(kind, []):
            if "src" in c:
                srcs.setdefault(os.path.normpath(c["src"]), None)
    if a.pool == "all":
        raw = ep / "raw_footage"
        for p in sorted(raw.rglob("*")) if raw.exists() else []:
            if p.suffix.lower() in VIDEO_EXT and not p.name.startswith("."):
                srcs.setdefault(os.path.normpath(os.path.relpath(p, ep)), None)
    for m in a.music:
        srcs.setdefault(os.path.normpath(os.path.relpath(Path(m).resolve(), ep)), None)

    print(f"成片 {tc(fin['duration'])} @ {float(ctx.fps):.3f}fps；比對 {len(srcs)} 支素材…", flush=True)
    ctx.sources = []
    for rel in srcs:
        orig = resolve(ep, rel, proxy=False)
        if not orig.exists():
            continue
        info = probe(orig)
        path = resolve(ep, rel, proxy=True)  # proxies decode faster; same timing
        au = audio_of(path) if info["has_audio"] else np.zeros(0, np.float32)
        ctx.sources.append({"rel": rel, "path": path, "video": info["has_video"], "audio": au,
                            "quiet": quiet_level(au)})
    idx = Index()
    for sid, s in enumerate(ctx.sources):
        if len(s["audio"]):
            idx.add(sid, s["audio"])
    idx.build()

    ctx.final_audio = audio_of(a.final)
    ctx.final_quiet = quiet_level(ctx.final_audio)
    ctx.final_th, ctx.final_flat = thumbs(a.final, ctx.fps)
    ctx.N = N = len(ctx.final_th)
    fps = ctx.fps
    qh, qt = landmarks(ctx.final_audio)
    mq, ms, mo = idx.match(qh, qt)

    video_ids = {i for i, s in enumerate(ctx.sources) if s["video"]}
    audio_ids = {i for i, s in enumerate(ctx.sources) if not s["video"] and len(s["audio"])}
    hop_s = HOP / SR
    spine_c = candidates(mq, ms, mo, RUN_GAP_S / hop_s, MIN_VOTES, video_ids)
    # music sits under the voice, so matches are sparse: bridge long holes; loops make
    # aliases at whole-loop offsets, so a weaker placement that overlaps a stronger one
    # of the same file is dropped
    music_c = []
    for c in sorted(candidates(mq, ms, mo, 15.0 / hop_s, MIN_VOTES, audio_ids),
                    key=lambda c: -c["votes"]):
        if all(m["src"] != c["src"] or c["q1"] < m["q0"] or c["q0"] > m["q1"] for m in music_c):
            music_c.append(c)

    def to_frame(sec):
        return int(round(sec * float(fps)))

    # ---- paint the timeline by match density (strongest first)
    for c in spine_c:
        c["off_s"] = refine_offset(ctx.final_audio, ctx.sources[c["src"]]["audio"], c) / SR
        c["f0"], c["f1"] = to_frame(c["q0"] * hop_s), to_frame(c["q1"] * hop_s + NFFT / SR)
        c["density"] = c["votes"] / max(1, c["f1"] - c["f0"])
    owner = np.full(N, -1, int)
    for i in sorted(range(len(spine_c)), key=lambda i: -spine_c[i]["density"]):
        c = spine_c[i]
        seg = owner[c["f0"]:c["f1"]]
        seg[seg < 0] = i
    segs = []  # [cand index, f0, f1]
    f = 0
    while f < N:
        g = f
        while g < N and owner[g] == owner[f]:
            g += 1
        if owner[f] >= 0 and g - f >= int(0.2 * float(fps)):
            segs.append([int(owner[f]), f, g])
        f = g
    # same hypothesis split only by a short hole -> one segment
    merged = []
    for s in segs:
        if merged and merged[-1][0] == s[0] and s[1] - merged[-1][2] < int(0.5 * float(fps)):
            merged[-1][2] = s[2]
        else:
            merged.append(s)
    segs = merged
    shared = {}
    segs = [{"sid": spine_c[i]["src"], "off_s": spine_c[i]["off_s"], "f0": f0, "f1": f1, "via": "sound",
             "sim": shared.setdefault(i, Sim(ctx, spine_c[i]["src"], spine_c[i]["off_s"]))}
            for i, f0, f1 in merged]
    W = int(round(float(fps)))  # search ±1 s around every cut

    def refine_pairs():
        """Between touching neighbours, cut where the frames before best match A and the
        frames after best match B (picture + sound)."""
        for k in range(len(segs) - 1):
            A, B = segs[k], segs[k + 1]
            if B["f0"] - A["f1"] > 2:
                continue
            lo, hi = max(A["f0"] + 1, A["f1"] - W), min(B["f1"] - 1, B["f0"] + W)
            if hi - lo < 2:
                continue
            sa, sb = A["sim"].score(lo, hi), B["sim"].score(lo, hi)
            cum_a = np.concatenate([[0], np.cumsum(sa)])
            cum_b = np.concatenate([[0], np.cumsum(sb[::-1])])[::-1]
            A["f1"] = B["f0"] = lo + int(np.argmax(cum_a + cum_b))

    def free_edges():
        """Edges next to nothing: grow while the frame clearly belongs, shrink while not."""
        for k, sg in enumerate(segs):
            sim = sg["sim"]
            prev_end = segs[k - 1]["f1"] if k else 0
            next_start = segs[k + 1]["f0"] if k + 1 < len(segs) else N
            if sg["f0"] > prev_end:
                lo = max(prev_end, sg["f0"] - W)
                sc = sim.score(lo, sg["f0"] + W)
                f = sg["f0"]
                while f - 1 >= lo and sc[f - 1 - lo] >= 0.7:
                    f -= 1
                while f < sg["f1"] - 1 and f - lo < len(sc) and sc[f - lo] < 0.4:
                    f += 1
                sg["f0"] = f
            if sg["f1"] < next_start:
                hi = min(next_start, sg["f1"] + W)
                base = sg["f1"] - W
                sc = sim.score(base, hi)
                f = sg["f1"]
                while f < hi and sc[f - base] >= 0.7:
                    f += 1
                while f > sg["f0"] + 1 and sc[f - 1 - base] < 0.4:
                    f -= 1
                sg["f1"] = f

    refine_pairs()
    free_edges()

    # ---- visual search pool (B-roll on top, or on the main track without its sound)
    pool_fps = Fraction(4)
    P, Pmeta = [], []
    for sid, src in enumerate(ctx.sources):
        if src["video"]:
            th, flat = thumbs(src["path"], pool_fps)
            P.append(th[~flat])
            Pmeta += [(sid, float(i / pool_fps)) for i in np.nonzero(~flat)[0]]
    P = np.concatenate(P) if P else np.zeros((0, (ROWS.stop - ROWS.start) * TW), np.float32)

    def visual_find(f0, f1):
        """(sid, off_s, mean sim, Sim) of the footage that best explains final frames f0..f1."""
        cand = [f for f in np.linspace(f0, f1 - 1, num=min(7, f1 - f0)).astype(int)
                if not ctx.final_flat[f]]
        if len(cand) < 2 or not len(P):
            return None
        sc = ctx.final_th[cand] @ P.T
        votes = {}
        for qi, f in enumerate(cand):
            for j in np.argsort(-sc[qi])[:3]:
                if sc[qi, j] < 0.6:
                    continue
                sid, t = Pmeta[j]
                key = (sid, round((t - float(f / fps)) * 4) / 4)
                votes.setdefault(key, []).append(float(sc[qi, j]))
        if not votes:
            return None
        (sid, off), v = max(votes.items(), key=lambda kv: (len(kv[1]), np.mean(kv[1])))
        if len(v) < max(2, len(cand) // 2):
            return None
        best = None
        for d in np.arange(-0.5, 0.5001, 1 / float(fps)):  # frame-accurate offset
            sim = Sim(ctx, sid, off + float(d))
            vv, _ = sim.frames(f0, f1)
            m = np.nanmean(vv) if np.isfinite(vv).any() else -1
            if best is None or m > best[2]:
                best = (sid, off + float(d), float(m), sim)
        return best if best[2] >= 0.7 else None

    # ---- stretches with no sound match: B-roll on the main track (its own sound off)?
    filled, cursor = [], 0
    for sg in segs + [{"f0": N, "f1": N, "end": True}]:
        if sg["f0"] - cursor >= int(0.3 * float(fps)):
            hit = visual_find(cursor, sg["f0"])
            if hit:
                filled.append({"sid": hit[0], "off_s": hit[1], "f0": cursor, "f1": sg["f0"],
                               "via": "picture", "sim": hit[3], "confidence": round(hit[2], 2)})
        if not sg.get("end"):
            filled.append(sg)
            cursor = sg["f1"]
    segs = filled
    refine_pairs()   # again: now picture-found clips have neighbours too
    free_edges()

    spine_out, overlays, unparsed = [], [], []

    def run_lengths(mask, a=0):
        out, f = [], 0
        while f < len(mask):
            if mask[f]:
                g = f
                while g < len(mask) and mask[g]:
                    g += 1
                out.append((a + f, a + g))
                f = g
            else:
                f += 1
        return out

    def place(f0, f1, sid, off_s, **extra):
        t0 = float(f0 / fps) + off_s
        return {"src": ctx.sources[sid]["rel"], "in": round(t0, 4),
                "out": round(t0 + float((f1 - f0) / fps), 4), **extra}

    def gap(f0, f1, why=None):
        if f1 <= f0:
            return
        if why and not ctx.final_flat[f0:f1].all():
            unparsed.append({"tag": why, "at": round(float(f0 / fps), 3),
                             "duration": round(float((f1 - f0) / fps), 3)})
        spine_out.append({"gap": round(float((f1 - f0) / fps), 4), "f0": f0, "f1": f1})

    cursor = 0
    covered = np.zeros(N, bool)
    for sg in segs:
        gap(cursor, sg["f0"], "unmatched")
        v, au = sg["sim"].frames(sg["f0"], sg["f1"])
        item = {**place(sg["f0"], sg["f1"], sg["sid"], sg["off_s"]), "f0": sg["f0"], "f1": sg["f1"],
                "via": sg["via"]}
        if sg["via"] == "picture":
            item.update(mute=True, confidence=sg["confidence"])
        else:
            item["_sim"] = (v, au)
            # picture does not match the clip underneath -> something on top
            low = np.nan_to_num(v, nan=1.0) < 0.5
            covered[sg["f0"]:sg["f1"]] = low & ~ctx.final_flat[sg["f0"]:sg["f1"]]
        spine_out.append(item)
        cursor = sg["f1"]
    gap(cursor, N, "unmatched")

    min_ov = int(0.3 * float(fps))
    for f0, f1 in run_lengths(covered):
        if f1 - f0 < min_ov:
            continue
        hit = visual_find(f0, f1)
        if not hit:
            unparsed.append({"tag": "covered", "at": round(float(f0 / fps), 3),
                             "duration": round(float((f1 - f0) / fps), 3),
                             "note": "畫面被別的東西蓋住：新素材、圖卡、特效、轉場或縮放"})
            continue
        # tighten the overlay's edges with its own picture match
        v, _ = hit[3].frames(f0, f1)
        good = np.nan_to_num(v, nan=0) >= 0.6
        if good.any():
            idx_g = np.nonzero(good)[0]
            f0, f1 = f0 + int(idx_g[0]), f0 + int(idx_g[-1]) + 1
        overlays.append({**place(f0, f1, hit[0], hit[1]), "at": round(float(f0 / fps), 4),
                         "confidence": round(hit[2], 2), "f0": f0})

    # confidence of each sound-matched clip: best of picture / sound per frame,
    # leaving out frames where a recognised overlay hides the picture
    hidden = np.zeros(N, bool)
    for o in overlays:
        f0 = int(round(o["at"] * float(fps)))
        hidden[f0:f0 + int(round((o["out"] - o["in"]) * float(fps)))] = True
    for x in spine_out:
        if "_sim" in x:
            v, au = x.pop("_sim")
            v = np.where(hidden[x["f0"]:x["f1"]], np.nan, v)
            # either signal agreeing strongly is enough: the picture can be hidden by
            # B-roll, the voice can be quiet under music
            means = [float(np.nanmean(z)) for z in (v, au) if np.isfinite(z).sum() >= 10]
            x["confidence"] = round(max(means), 2) if means else 0.0

    audio = []
    for c in music_c:
        at = c["q0"] * hop_s
        dur = (c["q1"] - c["q0"]) * hop_s + NFFT / SR
        audio.append({"src": ctx.sources[c["src"]]["rel"], "in": round(at + c["off_hops"] * hop_s, 4),
                      "out": round(at + c["off_hops"] * hop_s + dur, 4), "at": round(at, 4),
                      "edges_approx": True})  # the voice hides where the music fades in/out

    # ---- carry ids over from ours (by source overlap)
    def assign(items, ours_items, new_prefix):
        pool = [o for o in ours_items if "src" in o]
        n_new, seen = 0, {}
        for it in sorted(items, key=lambda x: x.get("f0", 0)):
            if "src" not in it:
                continue
            best, ov = None, 0.0
            for o in pool:
                if os.path.normpath(o["src"]) != os.path.normpath(it["src"]):
                    continue
                inter = min(o["out"], it["out"]) - max(o["in"], it["in"])
                if inter > ov:
                    best, ov = o, inter
            if best is not None:
                k = seen.get(best["id"], 0) + 1
                seen[best["id"]] = k
                it["id"] = best["id"] if k == 1 else f"{best['id']}#{k}"
                if k > 1:
                    it["origin"] = best["id"]
                for key in ("role", "note"):
                    if key in best:
                        it[key] = best[key]
            else:
                n_new += 1
                it["id"] = f"{new_prefix}{n_new}"
            it["gain_unknown"] = True

    assign([x for x in spine_out if "src" in x], ours.get("spine", []), "rs")
    assign(overlays, ours.get("overlays", []), "ro")
    assign(audio, ours.get("audio", []), "ra")
    g = 0
    for x in spine_out:
        if "gap" in x:
            g += 1
            x["id"] = f"rgap{g}"
    for lst in (spine_out, overlays):
        for x in lst:
            x.pop("f0", None)
            x.pop("f1", None)

    out = {"version": 1, "name": Path(a.final).stem, "fps": [fps.numerator, fps.denominator],
           "size": [fin.get("width"), fin.get("height")], "reconformed_from": str(a.final),
           "spine": [{"id": x.pop("id"), **x} for x in spine_out],
           "overlays": [{"id": x.pop("id"), **x} for x in overlays],
           "audio": [{"id": x.pop("id"), **x} for x in audio], "unparsed": unparsed}
    save_json(a.output, out)
    sp = [x for x in out["spine"] if "src" in x]
    low = [x["id"] for x in sp + out["overlays"] if x.get("confidence", 1) < 0.6]
    print(f"還原 {a.output}：主軸 {len(sp)} 段（聲音 {sum(x['via'] == 'sound' for x in sp)}、"
          f"畫面 {sum(x['via'] == 'picture' for x in sp)}）、疊加畫面 {len(out['overlays'])}、"
          f"音樂 {len(out['audio'])}、無法辨識 {len(unparsed)}")
    if low:
        print(f"  信心偏低（請人工確認）：{', '.join(low)}")


if __name__ == "__main__":
    main()

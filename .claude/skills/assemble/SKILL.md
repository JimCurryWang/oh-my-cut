---
name: assemble
description: 把所有已核准的 sequence 接成完整時間軸，檢查段落銜接、整體節奏與長度，加入跨段落的音樂。所有段落都 /cut 完成後使用。
argument-hint: "[episode]"
---

# /assemble

這一步只看段落之間的關係，不重新審視段落內部。只讀各段的 `STATE.md` 和 `cut.json`，不讀逐字稿。

## 1. 確認可以組合

讀 `EP/STATE.md`。有段落不是「已核准」就列出來，問使用者要先完成還是先組合看看。

## 2. 組合

```bash
python3 scripts/assemble.py EP
python3 scripts/render_cut.py EP/work/timeline/cut.json --episode-dir EP
```

## 3. 檢查

- **長度**：總長度對照 `outline.md` 的目標與 `style.json` 的 `video_length_s`。超出時指出哪幾段超過各自的目標最多。
- **銜接**：啟動 `qc-reviewer` subagent 看時間軸的 sheet，請它特別看每個段落交界的前後兩格：景別太像、亮度落差太大、情緒斷掉。
- **節奏曲線**：用各段的片段數與長度算每段的平均鏡頭長度，列成一行一段的表。連續三段都一樣快或一樣慢時指出來。
- **開場**：前 30 秒的剪接數對照 `style.json` 的 `hook_cuts_per_min`。

## 4. 跨段落的元素

音樂通常跨段落，放在 `EP/work/timeline/extras.json`（`at` 是整條時間軸的秒數）：

```json
{"audio": [{"id": "bed1", "src": "../../brand/music/<檔名>", "in": 0, "out": 95, "at": 12.0, "gain_db": -18}],
 "overlays": []}
```

從 `brand/music/` 依 `style.json` 的 `audio.music_feel` 提出建議；音量先用 `music_under_voice_db`。沒有合適的音樂就說明需要哪種感覺的音樂，請使用者提供，不要從參考影片取。音樂的選擇是分岔點，可以給 A/B。

加完重跑第 2 步。

## 5. 修改的原則

- 段落內部的問題 → 回到 `/cut <sequence>` 改該段的 `cut.json`，再重新組合。`work/timeline/cut.json` 是組合出來的，直接改會在下次組合時被蓋掉。
- 段落順序 → 改 `episode.json` 的 `sequences`，並用 `decide.py log --type revision --key sequence-order` 記錄。
- 交界處的一兩格 → 改該段 `cut.json` 的第一個或最後一個片段。

## 6. 完成

使用者認可整體後，更新 `EP/STATE.md`（階段：已組合，總長度），然後用 AskUserQuestion 問接下來走哪條路：

- **匯出到 Final Cut 精修（建議）** → `/fcp export`
- **直接鎖定，在這裡完成** → 複製 `work/timeline/cut.json` 為 `work/timeline/cut.locked.json`，`episode.json` 設 `locked: true`、`finish_route: "claude"`，接 `/finish`

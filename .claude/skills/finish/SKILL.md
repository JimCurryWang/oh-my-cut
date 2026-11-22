---
name: finish
description: 時間軸鎖定後的完稿：產生繁中字幕、用疊加層引擎做字幕樣式與動態圖卡、調色與響度、輸出成片或交付 Final Cut 用的素材。/fcp import 或直接鎖定之後使用。
argument-hint: "[episode]"
---

# /finish

前提：`episode.json` 的 `locked` 是 `true`，`EP/work/timeline/cut.locked.json` 存在。還沒鎖定就停下來說明原因：字幕和圖卡的時間都依賴剪接點，剪接點還會動就先不做。

先讀：`taste/_me/preferences.md`、`style.json` 的 `captions`、`motion`、`color`、`audio`、`brand/brand.json`、`EP/STATE.md`。

## 1. 字幕文字

字幕是從逐字稿和時間軸**推導**出來的，不手動對時間：

```bash
python3 scripts/captions.py build EP/work/timeline/cut.locked.json \
  --index-dir EP/work/index -o EP/work/timeline/captions \
  --max-chars <style.json captions.max_chars，brand.json 有設定則以它為準> \
  --glossary brand/glossary.txt
```

讀 `captions.srt`（純文字，不大）校對：同音錯字、專有名詞、中英夾雜。**不要直接改 `.srt`**：

- 專有名詞與固定聽錯的字 → 加進 `brand/glossary.txt`，重跑上面的指令。
- 個別錯字 → 改 `EP/work/index/<clip>/transcript.json` 裡對應的字，重跑。

沒把握的字詞列給使用者確認（附時間碼），確認後一樣加進 glossary。斷行不順的地方調 `--max-chars` 或 `--max-gap`；使用者對斷行的意見用 `decide.py log --key caption-linebreak` 記錄。

## 2. 字幕樣式與動態圖卡

讀 `.omc/overlay_engine`，載入該引擎自己的 skill，照它的做法在 `overlay/` 專案裡製作。對兩種引擎的共同要求：

- 尺寸、影格率、總長度與時間軸完全一致（`cut.locked.json` 的 `size`、`fps`，長度見 `captions.json` 的 `duration`）
- 透明背景，輸出 ProRes 4444（`.mov`）
- 字體、顏色、邊距讀 `brand/brand.json`；手法（位置、大小、強調、動畫）讀 `style.json`
- 字幕資料直接讀 `EP/work/timeline/captions.json`，不要把字幕文字抄進程式碼

分成兩支輸出，方便各自重做：

- `EP/exports/overlay_captions_v01.mov`：字幕
- `EP/exports/overlay_graphics_v01.mov`：片頭字卡、地點字卡、地圖動畫等（依 outline 與 `style.json` 的 `motion.graphics`；時間點用 `cut.locked.json` 的 `sections` 推算）

先各渲染 10 秒樣片給使用者確認樣式，再渲染全長。字幕樣式是分岔點：這個 style 第一次做時給 A/B，選定後用 `decide.py log --key caption-style` 記錄，並把選定的參數寫回 `style.json`。

`brand.json` 的字體欄位是空的就先問使用者，不要自己挑字體。

## 3. 輸出

依 `episode.json` 的 `finish_route`：

**`fcp`（成片從 Final Cut 輸出）**：交付 `overlay_captions_v01.mov`、`overlay_graphics_v01.mov`、`captions.srt`。告訴使用者把兩支 `.mov` 放在時間軸最上層、從 0 秒開始；`.srt` 可以用 File > Import > Captions… 匯入，或留著上傳 YouTube。調色與響度在 Final Cut 處理；提供 `style.json` 的目標值（響度、音樂相對音量）作參考。

**`claude`（由這裡渲染）**：全解析度渲染很慢，先告知預估並取得同意。

```bash
python3 scripts/render_cut.py EP/work/timeline/cut.locked.json --episode-dir EP --final \
  -o EP/exports/<episode>_v01.mp4 \
  --overlay-mov EP/exports/overlay_graphics_v01.mov \
  --overlay-mov EP/exports/overlay_captions_v01.mov \
  --lufs <style.json audio.lufs> [--lut <brand.json lut>]
```

LUT 只套用在素材上，不影響字幕與圖卡。有 HDR 素材時這條路的顏色不可靠，建議改走 `fcp`。已存在的檔名不會被覆蓋，版本號往上加。

## 4. 成片檢查

`claude` 路線：啟動 `qc-reviewer` subagent 檢查成片的抽樣畫面（字幕有沒有壓到臉或超出安全邊距、圖卡時間點、黑畫面），並量測響度：

```bash
ffmpeg -hide_banner -nostats -i <成片> -af ebur128 -f null - 2>&1 | grep "I:" | tail -1
```

`fcp` 路線：請使用者輸出後把成片放進 `EP/exports/`，同樣檢查一次。

## 5. 收尾

- 使用者對成片的任何修改意見都照 `/cut` 的方式記錄。
- 更新 `EP/STATE.md`：階段「完成」、成片檔名。
- 建議執行 `/learn`，趁這一集的記憶還在檔案裡時提煉規則。

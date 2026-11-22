---
name: finish
description: 時間軸鎖定後的完稿：產生繁中字幕（剪輯軟體裡可編輯）、用疊加層引擎做動態圖卡、調色與響度、輸出成片或交付剪輯軟體用的素材。/refine import 或直接鎖定之後使用。
argument-hint: "[episode]"
---

# /finish

前提：`episode.json` 的 `locked` 是 `true`，`EP/work/timeline/cut.locked.json` 存在。還沒鎖定就停下來說明原因：字幕和圖卡的時間都依賴剪接點，剪接點還會動就先不做。

`.omc/env.json` 的 `ready_finish` 不是 `true` → 先執行 `/setup finish`（疊加層引擎到這一步才需要）。

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

## 2. 可編輯的字幕（兩條路線都做）

字幕**一定**要有一份使用者能在剪輯軟體裡自己改的版本，不只是燒在影片裡。所有路線都先交付 `.srt`（也是 YouTube 上傳用的字幕檔）：

```bash
cp EP/work/timeline/captions.srt EP/exports/<episode>_captions_v01.srt
```

依 `episode.json` 的 `editor`：

**`jianying`（剪映）**：只用 `.srt`。告訴使用者：在精修好的那份草稿裡，文本 > 本地字幕 > 導入字幕，選這個檔案。匯入後每一行都是可編輯的字幕片段；字體、顏色、描邊在任一行設定後選「應用到全部字幕」，數值照 `brand.json`（字體、`colors.primary`、`colors.stroke`）與 `style.json` 的 `captions`（大小、位置）。時間對得上，是因為鎖定的時間軸就是從這份草稿匯出的成片還原的；如果鎖定後又在剪映改了剪接點，先 `/refine import` 再產生字幕。

**`fcp`（Final Cut）**：再輸出 Basic Title 版本，字體、顏色、描邊取自 `brand.json`，大小取自 `style.json`，每行的文字、時間、樣式都能在 Final Cut 裡改：

```bash
python3 scripts/captions.py fcpxml EP/work/timeline/captions.json \
  -o EP/exports/<episode>_captions_v01.fcpxml --style taste/<style>/profile/style.json
```

`.srt` 也可以用 File > Import > Captions… 匯入成 Final Cut 原生字幕。

**`other`**：`.srt`；DaVinci Resolve 可另外匯入 `.fcpxml`（同上指令）。

**Final Cut 第一次為這個 style 做字幕時**，先加 `--limit 3` 輸出三行樣片，請使用者匯入確認字體、大小、位置、描邊。用 `--font`、`--size`、`--y`、`--no-stroke` 調到滿意，然後：字體寫回 `brand.json` 的 `fonts.caption`，大小寫回 `style.json` 的 `captions.size_pct_of_height`，位置調 `brand.json` 的 `caption.safe_margin_pct`；用 `decide.py log --key caption-style` 記錄。之後的集數直接輸出全部。

`brand.json` 的字體欄位是空的就先問使用者，不要自己挑字體。

Final Cut：告訴使用者怎麼放進專案：File > Import > XML… 選 `_captions_v01.fcpxml` → 打開匯入的「字幕」專案 → 選取所有標題、⌘C → 回到自己的專案，播放頭移到最開頭 → ⌥V（貼上為連接片段）。

提醒使用者：在剪輯軟體裡改字幕文字是最後一步。之後如果重新產生字幕，手改的內容會被新檔取代，所以反覆出現的錯字要回到第 1 步加進 glossary。

## 3. 動態圖卡（以及 `claude` 路線的字幕樣式）

讀 `.omc/overlay_engine`，載入該引擎自己的 skill，照它的做法在 `overlay/` 專案裡製作。對兩種引擎的共同要求：

- 尺寸、影格率、總長度與時間軸完全一致（`cut.locked.json` 的 `size`、`fps`，長度見 `captions.json` 的 `duration`）
- 透明背景，輸出 ProRes 4444（`.mov`）
- 字體、顏色、邊距讀 `brand/brand.json`；手法（位置、大小、強調、動畫）讀 `style.json`
- 字幕資料直接讀 `EP/work/timeline/captions.json`，不要把字幕文字抄進程式碼

依路線輸出：

- `EP/exports/overlay_graphics_v01.mov`：片頭字卡、地點字卡、地圖動畫等（依 outline 與 `style.json` 的 `motion.graphics`；時間點用 `cut.locked.json` 的 `sections` 推算）。兩條路線都要。
- `EP/exports/overlay_captions_v01.mov`：**只有 `claude` 路線**才做（成片在這裡渲染，字幕必須燒進去）。`editor` 路線的字幕用第 2 步的可編輯版本，不做這支。

剪映能不能正確顯示透明背景的 ProRes 4444 還沒驗證過：`editor` 是 `jianying` 時，先給使用者 10 秒樣片放進草稿最上層確認透明背景正常，不正常就改輸出 PNG 序列，或請使用者用剪映內建的文字模板做圖卡。

先渲染 10 秒樣片給使用者確認樣式，再渲染全長。`claude` 路線的字幕動畫樣式是分岔點：這個 style 第一次做時給 A/B，選定後用 `decide.py log --key caption-style` 記錄，並把選定的參數寫回 `style.json`。

## 4. 輸出

依 `episode.json` 的 `finish_route`（舊的 `"fcp"` 等同 `"editor"`）：

**`editor`（成片從剪輯軟體輸出）**：交付第 2 步的字幕檔（剪映：`.srt`；Final Cut：`.fcpxml` 與 `.srt`）和 `overlay_graphics_v01.mov`。告訴使用者：字幕照第 2 步放進專案；圖卡 `.mov` 放在時間軸最上層、從 0 秒開始。調色與響度在剪輯軟體處理；提供 `style.json` 的目標值（響度、音樂相對音量）作參考。

**`claude`（由這裡渲染）**：全解析度渲染很慢，先告知預估並取得同意。

```bash
python3 scripts/render_cut.py EP/work/timeline/cut.locked.json --episode-dir EP --final \
  -o EP/exports/<episode>_v01.mp4 \
  --overlay-mov EP/exports/overlay_graphics_v01.mov \
  --overlay-mov EP/exports/overlay_captions_v01.mov \
  --lufs <style.json audio.lufs> [--lut <brand.json lut>]
```

字幕燒進成片的同時，第 2 步的字幕檔仍然交付，方便日後改字幕重出或上傳 YouTube。

LUT 只套用在素材上，不影響字幕與圖卡。有 HDR 素材時這條路的顏色不可靠，建議改走 `fcp`。已存在的檔名不會被覆蓋，版本號往上加。

## 5. 成片檢查

`claude` 路線：啟動 `qc-reviewer` subagent 檢查成片的抽樣畫面（字幕有沒有壓到臉或超出安全邊距、圖卡時間點、黑畫面），並量測響度：

```bash
ffmpeg -hide_banner -nostats -i <成片> -af ebur128 -f null - 2>&1 | grep "I:" | tail -1
```

`fcp` 路線：請使用者輸出後把成片放進 `EP/exports/`，同樣檢查一次。

## 6. 收尾

- 使用者對成片的任何修改意見都照 `/cut` 的方式記錄。
- 更新 `EP/STATE.md`：階段「完成」、成片檔名。
- 建議執行 `/learn`，趁這一集的記憶還在檔案裡時提煉規則。

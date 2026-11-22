# Oh-my-cut

用 Claude Code 剪我的 YouTube 旅遊／生活 vlog。和我對話一律用**繁體中文**。

## 你必須先知道的三件事

1. **你看不到影片。** 你只能讀文字和靜態圖。所有素材都要先經過 `/index` 變成索引（逐字稿、鏡頭切點、縮圖）才能下判斷。沒有索引就不要猜畫面內容。
2. **你沒有跨 session 的記憶。** 我的習慣只存在於檔案裡：`taste/_me/preferences.md`（規則）、`taste/_me/decisions.jsonl` 和各段落的 `edits.jsonl`（證據）。每次開工先讀 preferences，每次我修正都要留下紀錄。
3. **剪輯決策是一份文字檔。** `cut.json` 才是剪輯本體，影片只是它渲染出來的結果。改剪輯就是改 `cut.json`，一律用 `scripts/cut_edit.py`，不要手改數字。

## 品味鐵則

- 從 `taste/{style}/` 的參考影片學習：節奏、結構、字幕、色彩、動態、聲音、畫面語法。
- 學的是手法，不是照抄。成品要像「我用這種手法拍的片」，不是那支影片的翻版。
- 保留我的臉、我的聲音、我的品牌（`brand/`）。不生成、不替換、不合成我本人。
- 參考影片（`references/`、`taste/*/videos/`）只用來分析，任何片段、音樂都不可以進成片。
- 我會逐格微調。你的工作是讓我下一次需要調的地方變少：每個修正都記錄，累積後用 `/learn` 提煉成規則。
- A/B 只在真正的分岔點給（開場 hook、段落節奏、音樂、字幕樣式），兩版只差一個說得出名字的維度。

## 判斷優先序

我當下說的話 ＞ `taste/_me/preferences.md` ＞ `taste/{style}/profile/style.md` ＞ 你的預設。
衝突時照高的走，並指出衝突，讓我決定要不要改規則。

## 流程與指令

| 階段 | 指令 | 產出 |
|---|---|---|
| 0 | `/setup` | `.omc/env.json`（只在第一次或工具出錯時） |
| 1 | `/taste-profile <style>` | `taste/<style>/profile/style.md`、`style.json`（快取） |
| 2 | `/new-episode <name>` | `video_editor/<name>/` 骨架，選 style 與大綱模式 |
| 3 | `/index` | `work/index/`、`work/footage_map.md` |
| 4 | `/outline` | `work/outline.md`（模式 A：我給故事；模式 B：你提案） |
| 5 | `/cut <sequence>` | `work/sequences/<seq>/cut.json`，每個大 cut 獨立粗剪到約 80% |
| 6 | `/assemble` | `work/timeline/cut.json` |
| 7 | `/fcp export` → 我在 Final Cut 精修 → `/fcp import` | 鎖定時間軸，並把我的改動變成學習證據 |
| 8 | `/finish` | 字幕、動態圖卡、成片 |
| 9 | `/learn` | 更新 `taste/_me/preferences.md` |

第 7 步可跳過：我說「直接鎖定」就以目前時間軸為準。任何階段我都可以用對話微調。

## Context 紀律

- 主對話只讀摘要：`footage_map.md`、`outline.md` 裡當前段落、`style.md`、`preferences.md`、各種 `STATE.md`。
- 逐字稿全文、縮圖、參考影片分析交給 subagent（`footage-indexer`、`style-profiler`、`sequence-editor`、`qc-reviewer`），它們把結論寫進檔案，只回報幾行。
- 一次只處理一個 sequence。完成後更新該段的 `STATE.md`，並建議我 `/clear` 再開下一段。
- 狀態都在檔案裡，任何時候中斷都能從 `STATE.md` 接續。

## 慣例

- 路徑：`cut.json` 的 `src` 相對於 episode 資料夾（`video_editor/<episode>/`）。
- 時間：`cut.json` 用秒；我和你溝通用「格」（frame）或秒都可以。格數換算交給腳本。
- id：spine 片段 `s1, s2…`，疊在上面的畫面 `o1…`，音樂音效 `m1…`。組合後會加上段落前綴（`02-arrival/s3`）。
- 預覽畫面左上角燒有片段 id、右上角有時間碼，我會用這些指給你看。
- 腳本用 `.omc/env.json` 裡的 `python` 執行；格式說明在 `docs/schemas.md`。

## 不可以做的事

- 不修改、不搬移、不刪除 `raw_footage/` 裡的任何檔案。
- 不覆蓋 `exports/` 裡的既有檔案，新版本一律加版本號（`_v02`）。
- 不把影片、音訊、縮圖 commit 進 git（`.gitignore` 已處理；只追蹤文字檔）。
- 全片完整解析度渲染很慢，開始前先跟我確認。
- 沒有我的同意不安裝任何東西。
- 不把單次的修正當成規則；規則只經由 `/learn` 並由我核准後才寫入。

---
name: setup
description: 檢查並安裝 Oh-my-cut 需要的工具，分兩層：基本（FFmpeg-full、Python、Whisper）與完稿（Node、疊加層引擎）。第一次使用、.omc/env.json 不存在或 ready 不是 true、/finish 發現 ready_finish 不是 true、或任何腳本回報找不到工具時使用。
argument-hint: "[recheck | finish]"
---

# /setup

目標：只裝缺的、裝之前先問、結果寫進檔案，之後不再重複檢查。

工具分兩層，**基本**先裝好就能開始剪；**完稿**到 `/finish` 才需要：

| 層 | 項目 | 用途 | env.json |
|---|---|---|---|
| 基本 | ffmpeg-full（含 drawtext）、Python ≥ 3.10、mlx-whisper、opencc | 索引、粗剪、預覽燒 id 與時間碼、剪輯軟體往返 | `ready` |
| 完稿 | Node ≥ 22、疊加層引擎（`./overlay`） | 字幕樣式、動態圖卡 | `ready_finish` |
| 選用 | 剪映＋pyJianYingDraft、Final Cut Pro、yt-dlp、Homebrew | 依 `editor` 需要；不影響就緒 | — |

`$ARGUMENTS` 含 `finish` 時兩層都要處理；否則先處理基本，完稿層問使用者要現在裝還是到 `/finish` 再裝。

## 1. 先看要不要做

讀 `.omc/env.json`。`ready` 是 `true`（要求 `finish` 時還要 `ready_finish` 是 `true`），而且 `$ARGUMENTS` 不含 `recheck`：把上次的檢查表重跑一次貼給使用者（`bash scripts/preflight.sh`），結束。

## 2. 檢查

```bash
bash scripts/preflight.sh
```

它只檢查、不安裝，印出一張分層的檢查表（✓ 可用、✗ 缺少、· 選用資訊）和每個缺項的修復指令，並寫入 `.omc/env.json`（含實際使用的 `ffmpeg` 路徑）。結束碼：0 全部就緒、2 基本未就緒、3 只有完稿未就緒。

**把整張檢查表原樣貼給使用者**（Bash 的輸出使用者不一定看得到）。

關於 ffmpeg：Homebrew 一般的 `ffmpeg` 沒有 `drawtext`，預覽就不會有片段 id 與時間碼。要裝的是 `ffmpeg-full`（keg-only，和原本的 `ffmpeg` 並存，不會互相覆蓋）。腳本透過 `.omc/env.json` 自動使用它，不需要改 PATH。

## 3. 選疊加層引擎（只會問一次）

如果 `.omc/overlay_engine` 不存在，用 AskUserQuestion 問：

- **HyperFrames（建議）**：用 HTML 寫畫面，Apache 2.0 授權，可直接輸出帶透明通道的 ProRes 4444。
- **Remotion**：用 React 寫畫面，生態成熟；公司使用在某些情況需要購買授權。
- **兩個各試一次再決定**：走第 6 步的比較。

把選擇寫進 `.omc/overlay_engine`（內容只有 `hyperframes` 或 `remotion` 一個字）。整個專案只保留一個引擎；字幕與動態圖卡都用它。

## 4. 安裝缺少的項目

把缺少的項目和對應指令一次列給使用者，取得同意後才執行。順序：

**基本**

1. Homebrew（缺的話請使用者自己在終端機貼上安裝指令，因為需要輸入密碼）
2. `brew install ffmpeg-full python@3.12`（只裝缺的）
3. Python 環境：`python3.12 -m venv .venv && .venv/bin/pip install -U pip mlx-whisper opencc-python-reimplemented`

安裝 `ffmpeg-full` 可能會升級共用的函式庫（例如 x265），讓原本的 `ffmpeg` 無法執行。裝完執行 `ffmpeg -version`；出現 `Library not loaded` 就執行 `brew upgrade ffmpeg` 修復，並告訴使用者。

**完稿**

4. `brew install node`（缺的或版本低於 22 時）
5. 疊加層引擎：
   - HyperFrames：`npx skills add heygen-com/hyperframes`，然後 `npx hyperframes init overlay`，最後 `npx hyperframes doctor`
   - Remotion：`npx create-video --yes --blank overlay`，然後在 `overlay/` 裡 `npx skills add remotion-dev/skills`
   
   引擎的指令可能改版。指令失敗時先查該引擎的官方文件或它裝進來的 skill，不要猜參數。

**選用**（使用者要才裝）：

- `brew install yt-dlp`（用網址下載參考影片時才需要）
- 剪映支線（`editor` 是 `jianying`，或使用者說他用剪映／CapCut）：`.venv/bin/pip install --only-binary :all: "pyJianYingDraft==0.3.1"`。版本固定、只裝預先編好的 wheel（安裝時不執行套件程式碼）；0.3.1 已比對過與 GitHub 原始碼一致。要升級版本前，重做一次同樣的檢查：PyPI wheel 與 GitHub tag 逐檔比對、掃描連網／執行外部指令／動態執行／刪檔的程式碼，並請使用者同意。

裝完重跑 `bash scripts/preflight.sh`，直到該層就緒。

## 5. 首次煙霧測試（各做一次，結果寫入 `.omc/smoke.json`）

**Whisper**：請使用者指定任一支有講話的影片，取 15 秒測試：

```bash
ffmpeg -y -v error -ss 0 -t 15 -i <影片> /tmp/omc_smoke.mp4
.venv/bin/python scripts/index_clip.py /tmp/omc_smoke.mp4 --out /tmp/omc_smoke_index --glossary brand/glossary.txt
cat /tmp/omc_smoke_index/omc_smoke/transcript.txt
```

第一次會下載模型（約 1.5 GB）。確認輸出是繁體中文、內容大致正確。

**剪映相容測試**（裝了 pyJianYingDraft 才做；剪映改版後也重做一次）：做一支畫面上燒有素材時間與格數的 20 秒測試影片，用 `jianying_bridge.py export` 產生兩段的草稿（例如素材 2.000–5.000 秒、10.500–12.500 秒），請使用者打開剪映確認：草稿出現在列表、能打開、兩段的第一格分別是 `frame 60`、`frame 315`、聲音正常。結果記入 `.omc/smoke.json`；測完請使用者在剪映裡刪掉測試草稿。

**Final Cut 往返**（`.omc/env.json` 的 `final_cut_pro` 是 `yes` 才做）：這一步無法自動驗證，必須請使用者動手。

1. 用同一支影片做一個兩段的測試 `cut.json`，執行 `python3 scripts/fcpxml_bridge.py export …`。
2. 請使用者在 Final Cut 選 File > Import > XML…，確認兩段畫面的起訖和預覽影片一致（特別是相機有時間碼的素材）。
3. 請使用者不做任何修改，File > Export XML… 存回來。
4. 執行 `import` 再 `diff`，結果必須是「沒有差異」。

如果第 2 步畫面對不上，或第 4 步出現差異，把現象記進 `.omc/smoke.json` 並告訴使用者：在修好之前 `/refine` 的 Final Cut 支線不可靠，先走純 Claude Code 路徑。

## 6. 引擎比較（只有選「兩個各試一次」才做）

兩個引擎各建一個臨時專案，做同一份作業：同一段 10 秒畫面、同一份字幕（3–4 行）、一張地點字卡，輸出透明背景的 ProRes 4444，再用 `render_cut.py --final --overlay-mov` 疊上去。把兩支成品給使用者看，用 AskUserQuestion 讓他選；刪掉沒選上的專案，寫入 `.omc/overlay_engine`，並用 `scripts/decide.py log --key overlay-engine` 記下原因。

## 完成時回報

1. 最後一次 `bash scripts/preflight.sh` 印出的**完整檢查表**，原樣貼出（哪些 ✓、哪些 ✗、修復指令）。
2. 選定的疊加層引擎、兩個煙霧測試的結果（沒做的寫「未做」與原因）。
3. 完稿層還沒就緒時，說明到 `/finish` 前再執行 `/setup finish` 即可。
4. 下一步：把參考影片放進 `taste/<style>/videos/` 後執行 `/taste-profile <style>`。

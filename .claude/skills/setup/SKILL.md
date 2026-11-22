---
name: setup
description: 檢查並安裝 Oh-my-cut 需要的工具（FFmpeg、Node、yt-dlp、Whisper、疊加層引擎）。第一次使用、.omc/env.json 不存在或 ready 不是 true、或任何腳本回報找不到工具時使用。
argument-hint: "[recheck]"
---

# /setup

目標：只裝缺的、裝之前先問、結果寫進檔案，之後不再重複檢查。

## 1. 先看要不要做

讀 `.omc/env.json`。如果 `ready` 是 `true` 而且使用者沒有要求重新檢查（`$ARGUMENTS` 不含 `recheck`），回報「環境已就緒」並結束。

## 2. 檢查

```bash
bash scripts/preflight.sh
```

它只檢查、不安裝，會列出每一項的狀態與修復指令，並寫入 `.omc/env.json`。

## 3. 選疊加層引擎（只會問一次）

如果 `.omc/overlay_engine` 不存在，用 AskUserQuestion 問：

- **HyperFrames（建議）**：用 HTML 寫畫面，Apache 2.0 授權，可直接輸出帶透明通道的 ProRes 4444 給 Final Cut。
- **Remotion**：用 React 寫畫面，生態成熟；公司使用在某些情況需要購買授權。
- **兩個各試一次再決定**：走第 6 步的比較。

把選擇寫進 `.omc/overlay_engine`（內容只有 `hyperframes` 或 `remotion` 一個字）。整個專案只保留一個引擎；字幕與動態圖卡都用它。

## 4. 安裝缺少的項目

把缺少的項目和對應指令一次列給使用者，取得同意後才執行。順序：

1. Homebrew（缺的話請使用者自己在終端機貼上安裝指令，因為需要輸入密碼）
2. `brew install ffmpeg node yt-dlp python@3.12`（只裝缺的）
3. Python 環境：`python3.12 -m venv .venv && .venv/bin/pip install -U pip mlx-whisper opencc-python-reimplemented`
4. 疊加層引擎：
   - HyperFrames：`npx skills add heygen-com/hyperframes`，然後 `npx hyperframes init overlay`，最後 `npx hyperframes doctor`
   - Remotion：`npx create-video --yes --blank overlay`，然後在 `overlay/` 裡 `npx skills add remotion-dev/skills`
   
   引擎的指令可能改版。指令失敗時先查該引擎的官方文件或它裝進來的 skill，不要猜參數。

裝完重跑 `bash scripts/preflight.sh`，直到 `ready: true`。

## 5. 首次煙霧測試（各做一次，結果寫入 `.omc/smoke.json`）

**Whisper**：請使用者指定任一支有講話的影片，取 15 秒測試：

```bash
ffmpeg -y -v error -ss 0 -t 15 -i <影片> /tmp/omc_smoke.mp4
.venv/bin/python scripts/index_clip.py /tmp/omc_smoke.mp4 --out /tmp/omc_smoke_index --glossary brand/glossary.txt
cat /tmp/omc_smoke_index/omc_smoke/transcript.txt
```

第一次會下載模型（約 1.5 GB）。確認輸出是繁體中文、內容大致正確。

**Final Cut 往返**（`.omc/env.json` 的 `final_cut_pro` 是 `yes` 才做）：這一步無法自動驗證，必須請使用者動手。

1. 用同一支影片做一個兩段的測試 `cut.json`，執行 `python3 scripts/fcpxml_bridge.py export …`。
2. 請使用者在 Final Cut 選 File > Import > XML…，確認兩段畫面的起訖和預覽影片一致（特別是相機有時間碼的素材）。
3. 請使用者不做任何修改，File > Export XML… 存回來。
4. 執行 `import` 再 `diff`，結果必須是「沒有差異」。

如果第 2 步畫面對不上，或第 4 步出現差異，把現象記進 `.omc/smoke.json` 並告訴使用者：在修好之前 `/fcp` 不可靠，先走純 Claude Code 路徑。

## 6. 引擎比較（只有選「兩個各試一次」才做）

兩個引擎各建一個臨時專案，做同一份作業：同一段 10 秒畫面、同一份字幕（3–4 行）、一張地點字卡，輸出透明背景的 ProRes 4444，再用 `render_cut.py --final --overlay-mov` 疊上去。把兩支成品給使用者看，用 AskUserQuestion 讓他選；刪掉沒選上的專案，寫入 `.omc/overlay_engine`，並用 `scripts/decide.py log --key overlay-engine` 記下原因。

## 完成時回報

一張表：每項工具的狀態、選定的引擎、兩個煙霧測試的結果。接著提示下一步：把參考影片放進 `taste/<style>/videos/` 後執行 `/taste-profile <style>`。

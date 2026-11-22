---
name: index
description: 把 raw_footage 裡的素材轉成 Claude 能讀的索引（proxy、逐字稿、鏡頭切點、縮圖、摘要）並產生 footage_map.md。素材放好之後、/outline 之前使用；之後新增素材時再跑一次只會處理新的。
argument-hint: "[episode]"
---

# /index

這一步決定之後所有判斷的品質。主對話在這裡**不要**打開任何縮圖或逐字稿，只看腳本輸出的摘要行和 subagent 的回報。

episode 取 `$0`；沒給就用 `video_editor/` 裡最近修改的那一個，並向使用者確認。以下 `EP` 代表 `video_editor/<episode>`。

## 1. 盤點

列出 `EP/raw_footage/` 的影片與音訊檔（含子資料夾）。回報數量和總長度的估計，並提醒：第一次索引時間大約是素材總長度的幾分之一，主要花在 Whisper。

檢查檔名：不同資料夾有相同主檔名（例如兩個 `IMG_0001.MOV`）會讓 proxy 與索引互相覆蓋。有的話先請使用者改名，不要自己動 `raw_footage/`。

## 2. 腳本索引

逐支執行（同時最多兩支，Whisper 會吃滿記憶體）：

```bash
.venv/bin/python scripts/index_clip.py "EP/raw_footage/<檔案>" \
  --out EP/work/index --proxy-dir EP/work/proxies --glossary brand/glossary.txt
```

已索引且沒變的檔案會顯示 `cached`。純空景、縮時這類確定沒人講話的素材，使用者有說的話可以加 `--no-transcript` 省時間。

收集每行輸出裡的警告（HDR、VFR、沒有逐字稿）。

## 3. 摘要（subagent）

把還沒有 `summary.md` 的素材分批（每批 6–8 支），每批啟動一個 `footage-indexer` subagent，平行進行。給它：`EP/work/index/` 路徑和這一批的素材名稱清單。它會為每支素材寫 `summary.md`。

## 4. 產生地圖

```bash
python3 scripts/index_clip.py --build-map EP/work/index -o EP/work/footage_map.md
```

## 5. 決定時間軸規格

讀各素材 `index.json` 的 `meta`（只讀 `fps`、`width`、`height`，可以用一行 python 彙整，不要整份讀進來）。取有口白的素材中最常見的影格率與尺寸，寫入 `episode.json` 的 `fps` 與 `size`。有多種影格率時告訴使用者你選了哪一個、哪些素材會被轉換。

## 6. 回報並更新 STATE.md

- 素材數、總長度、有口白的支數
- 警告：HDR 素材（預覽顏色會偏灰，調色以 Final Cut 為準）、沒有聲音的檔案、索引失敗的檔案
- 下一步：`/outline`

`STATE.md` 的階段改為「已索引」。

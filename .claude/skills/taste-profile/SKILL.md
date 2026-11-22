---
name: taste-profile
description: 分析 taste/<style>/videos 裡的參考影片，產生並快取風格 profile（style.md、style.json）。新增或更換參考影片後、或 /new-episode 發現 profile 過期時使用。
argument-hint: "<style> [url ...]"
---

# /taste-profile

把參考影片變成一份可以重複使用、可以被使用者修改的風格描述。每個 style 只需要做一次；影片沒變就不重跑。

style 名稱是 `$0`。之後的參數如果是網址，先下載：

```bash
yt-dlp -f "bv*[height<=1080]+ba/b" --merge-output-format mp4 \
  -o "taste/$0/videos/%(title).60s.%(ext)s" <url>
```

參考影片只用於分析，不會進任何成片。

## 1. 檢查快取

```bash
python3 scripts/taste_cache.py status taste/$0
```

- `fresh`：讀出 `style.md` 的前 30 行給使用者，結束。
- `empty`：請使用者放 2–5 支手法一致的影片進 `taste/$0/videos/`，結束。
- `stale`：繼續。只處理新增或變更的影片（`index_clip.py` 自己會跳過沒變的）。

## 2. 量測（腳本）

對 `taste/$0/videos/` 每支影片執行（不產生 proxy）：

```bash
.venv/bin/python scripts/index_clip.py "<影片>" --out taste/$0/profile/index
```

全部完成後：

```bash
python3 scripts/taste_cache.py stats taste/$0
```

這會產生 `style.stats.json`：鏡頭長度分布、每分鐘剪接數、前 30 秒剪接數、響度、說話比例、語速、亮度與飽和度。

## 3. 觀察（subagent）

量得到的只是一部分。對每支影片平行啟動一個 `style-profiler` subagent，給它該影片的索引資料夾路徑，請它把觀察寫到 `taste/$0/profile/index/<影片>/observations.md`。主對話不要自己開縮圖。

## 4. 綜合

讀所有 `observations.md` 和 `style.stats.json`，寫出兩份檔案：

**`taste/$0/profile/style.md`**（給人讀，一頁以內），依這些面向：

1. 結構：hook 怎麼開、多長；有沒有片頭；章節怎麼分；怎麼收尾
2. 節奏：口白段與 B-roll 段的鏡頭長度、哪裡加快哪裡放慢、最後一個字之後留多久
3. 字幕：位置、字體感覺、大小、描邊或底色、一行幾個字、有沒有標點、強調方式、動畫
4. 色彩：整體調性、對比、膚色、陰影與高光的處理
5. 動態：轉場類型與頻率、推拉搖移、變速、動態圖卡的種類
6. 聲音：音樂類型與能量、音樂和人聲的相對音量、音效、留白
7. 畫面語法：口白畫面與 B-roll 的比例、常用景別、畫面文字的密度
8. 不要照抄的東西：對方的 logo、口頭禪、招牌梗、片頭音樂

每一點區分「所有影片都這樣」和「只有某一支這樣」。只寫共通的；單支的特例放在最後的備註。

**`taste/$0/profile/style.json`**：格式見 `docs/schemas.md`。數字從 `style.stats.json` 帶入，量不到的欄位依觀察填寫。

## 5. 請使用者校正

把 `style.md` 的重點列給使用者，問一個問題：「哪些是你要學的，哪些只是他們的特色、你不想要？」依回答修改兩份檔案。使用者不想要的項目移到 `do_not_copy`。

## 6. 標記完成

```bash
python3 scripts/taste_cache.py commit taste/$0
```

回報：分析了幾支影片、三個最鮮明的特徵、檔案位置。

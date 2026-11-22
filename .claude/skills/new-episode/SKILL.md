---
name: new-episode
description: 開始剪一支新影片：建立 video_editor/<episode> 資料夾結構，讓使用者選擇 taste style 與大綱模式。使用者說要剪新的一集、新的 vlog 時使用。
argument-hint: "<episode-name>"
---

# /new-episode

episode 名稱是 `$0`（建議 `年-月-主題`，例如 `2026-11-kyoto`）。沒有給就先問。

## 1. 前置檢查

`.omc/env.json` 不存在或 `ready` 不是 `true` → 先執行 `/setup`。

## 2. 建立結構

```
video_editor/$0/
├── raw_footage/     使用者放原始素材（不會被修改）
├── references/      這一集專用的參考（選用）
├── exports/         成片、交給剪輯軟體的檔案
├── work/
│   ├── index/       素材索引
│   ├── proxies/     低解析代理檔
│   ├── sequences/   每個大 cut 一個資料夾
│   ├── timeline/    組合後的時間軸
│   └── refine/      剪輯軟體往返（還原的時間軸、diff）
├── episode.json
└── STATE.md
```

## 3. 問三件事（用 AskUserQuestion，一次問完）

**Style**：列出 `taste/` 底下除了 `_me` 以外的資料夾作為選項，每個選項的說明取自該 style 的 `style.md` 第一行。使用者也可以輸入新的名稱。

- 選了既有 style：執行 `python3 scripts/taste_cache.py status taste/<style>`，不是 `fresh` 就執行 `/taste-profile <style>`。
- 輸入新名稱：建立 `taste/<名稱>/videos/`，請使用者放影片或給網址，再執行 `/taste-profile`。
- `taste/` 是空的：說明需要先建立至少一種 style；使用者堅持不用參考時，以 `preferences.md` 加預設值進行，並在 `episode.json` 寫 `"style": null`。

**大綱模式**：

- A：我已經有想說的故事，幫我對照素材看可不可行
- B：我還沒想法，先看素材再給我幾個大綱

**精修用的剪輯軟體**（預設沿用上一集的 `editor`；沒有上一集就以 CLAUDE.md 寫的為準，目前是剪映）：

- 剪映／CapCut（`jianying`）：粗剪直接變成剪映草稿；精修完匯出成片，從成片還原你的改動
- Final Cut Pro（`fcp`）：FCPXML 往返
- 其他（`other`）：FCPXML（DaVinci Resolve 可讀）或預覽＋片段表；從成片還原改動

## 4. 寫入狀態

`episode.json`（格式見 `docs/schemas.md`）：先填 `episode`、`style`、`outline_mode`、`editor`、`language: "zh"`、`locked: false`。`fps` 和 `size` 留給 `/index` 依素材決定。

`STATE.md`：

```markdown
# <episode>
- style: <style>
- 模式: A / B
- 階段: 等待素材
- 下一步: 把素材放進 raw_footage/，然後 /index

## 段落進度
（/outline 之後填）

## 這一集的特別指示
（使用者針對這集說的話記在這裡）
```

## 5. 回報

資料夾位置、選定的 style 與模式，以及下一步：把素材放進 `raw_footage/`（或建立捷徑）後執行 `/index`。模式 A 的使用者可以同時把想說的故事寫進 `work/story.md`，或直接在對話裡說。

---
name: cut
description: 粗剪一個大 cut（sequence）到約 80%：產生 cut.json、渲染預覽、在分岔點給 A/B、依使用者的回饋逐格微調並記錄。/outline 完成後，對每個段落各執行一次；使用者想回頭調整某一段時也用這個。
argument-hint: "<sequence> [episode]"
---

# /cut

一次只處理一個段落：`$0`。以下 `SEQ` 代表 `EP/work/sequences/$0`。

目標是**粗剪到 80%**：片段選對、順序對、長度接近。不做字幕、調色、圖卡；細到一兩格的東西使用者會在這裡用對話調，或留到 Final Cut。

## 0. 接續或開始

`SEQ/STATE.md` 存在就讀它並從記錄的步驟接續。否則建立 `SEQ/`，只讀：

- `EP/work/outline.md` 裡 `## $0` 這一節
- `taste/_me/preferences.md`
- `taste/<style>/profile/style.json`（`pacing`、`grammar`）
- `EP/STATE.md` 的「這一集的特別指示」

如果 `EP/episode.json` 的 `locked` 是 `true`，這一段已經凍結：告訴使用者要改請直接改鎖定的時間軸（見步驟 5 的指令，檔案換成 `work/timeline/cut.locked.json`），或先解除鎖定。

## 1. 初稿（subagent）

啟動 `sequence-editor` subagent。給它：episode 路徑、段落名稱、outline 該節的全文、style.json 的 `pacing` 與 `grammar`、preferences.md 全文。它會讀逐字稿和縮圖，寫出 `SEQ/cut.json` 和 `SEQ/notes.md`（為什麼這樣選、哪裡沒把握），需要 A/B 時另寫 `SEQ/cut.B.json`。

主對話只讀 `notes.md`。

## 2. 機械檢查

```bash
python3 scripts/captions.py check SEQ/cut.json --index-dir EP/work/index
```

切在字中間的切點，用 `cut_edit.py … --by claude` 移到建議的位置。

## 3. 預覽與 QC

```bash
python3 scripts/render_cut.py SEQ/cut.json --episode-dir EP
```

產生 `cut.preview.mp4`（480p，左上角有片段 id、右上角有時間碼）和 `cut.preview.sheet.jpg`。

啟動 `qc-reviewer` subagent 看 sheet 和片段表（不給它 notes.md）。它回報的硬傷（黑畫面、同景別跳接、用錯素材、長度離 style 太遠）先修掉再給使用者看，修正一律 `--by claude`。

## 4. 交給使用者

給：預覽檔路徑、片段表（腳本輸出的那張）、總長度與目標長度的差距、`notes.md` 裡沒把握的地方（最多三點）。

**A/B 只在下列情況給**，其他情況直接給一版：

- 這是開場 hook
- outline 這一節有「未決」
- 兩種剪法在一個維度上差異明顯，而 preferences 和 style 都沒有答案（例如：節奏快慢、口白先行還是畫面先行、有沒有音樂）
- 使用者要求

A/B 的規則：兩版只差**一個**說得出名字的維度，其他完全相同。渲染成 `cut.A.preview.mp4` 和 `cut.B.preview.mp4`，說明差在哪裡。使用者選定後：

```bash
python3 scripts/decide.py log --episode <ep> --sequence $0 --type ab \
  --key <維度代號> --context "<這段是什麼>" --proposed "A: … / B: …" \
  --chosen "<A 或 B 的描述>" --reason "<使用者說的原因>"
```

選中的存成 `cut.json`，另一版刪除。使用者沒說原因就問一句，原因比選擇本身更有用。

## 5. 微調迴圈

把使用者的話翻成 `cut_edit.py` 指令。**每一次都用 `--why` 帶上使用者的原話**，這是 `/learn` 的原料。

| 使用者說 | 指令 |
|---|---|
| s7 尾巴少 6 格 | `cut_edit.py SEQ/cut.json trim s7 --tail -6f --why "…"` |
| s3 開頭晚一點、0.2 秒 | `trim s3 --head 0.2s` |
| s5 長度不變，內容往後挪 10 格 | `slip s5 10f` |
| 拿掉 s4 | `delete s4` |
| s5 和 s6 對調 | `swap s5 s6` |
| s8 移到 s2 後面 | `move s8 --after s2` |
| o2 那個空景早半秒出來 | `shift o2 -0.5s` |
| 音樂小聲一點 | `gain m1 -22` |

表中省略了開頭的 `python3 scripts/cut_edit.py SEQ/cut.json`。正的 `--head` 是晚一點開始，負的 `--tail` 是早一點結束。指令完成會印出新的片段表。

不是格數的回饋（「這段太拖」「不夠有感覺」）：提出具體改法（刪哪幾段、哪幾段各縮多少），使用者同意後用同樣的指令執行，`--why` 寫使用者的原話。另外記一筆：

```bash
python3 scripts/decide.py log --episode <ep> --sequence $0 --type revision \
  --key <代號> --context "…" --proposed "<原本的做法>" --chosen "<改成的做法>" --reason "…"
```

需要換素材或加新片段時，直接編輯 `cut.json`（新 id 接著編號），之後照樣做第 2、3 步的檢查。

每輪修改後重新渲染預覽。只改了一兩格時可以先問使用者要不要累積幾個修改再一起渲染。

## 6. 完成

使用者說可以了：

- `SEQ/STATE.md`：狀態「已核准」、最終長度、三行以內的摘要（頭尾各是什麼畫面、結尾的情緒，給 `/assemble` 判斷段落銜接用）
- `EP/STATE.md` 的段落進度同步更新
- 回報下一個未完成的段落，並建議先 `/clear`

中途停下時也要更新 `SEQ/STATE.md`：做到第幾步、使用者最後一個還沒處理的回饋。

---
name: fcp
description: 與 Final Cut Pro 往返。export：把時間軸匯出成 FCPXML 讓使用者精修；import：讀回使用者改過的時間軸、列出他改了什麼、記錄為學習證據並鎖定時間軸。/assemble 之後使用，或使用者說他在 Final Cut 改完了。
argument-hint: "export | import [檔案路徑]"
---

# /fcp

這是整套流程裡學習訊號最密集的地方：使用者在 Final Cut 做的每個修改，都是他的習慣的直接證據。

## export

```bash
python3 scripts/fcpxml_bridge.py export EP/work/timeline/cut.json \
  --episode-dir EP -o EP/exports/<episode>_rough.fcpxml
```

連結的是 `raw_footage/` 的原始檔。告訴使用者：

1. Final Cut：File > Import > XML…，選這個檔案。會建立一個事件和專案；主故事線是 spine，B-roll 是連接片段，音樂在下方，各段起點有標記。片段名稱結尾的 `[02-arrival/s3]` 是我們的 id，請不要改名。
2. 自由修改。標題、轉場、調色、變速都可以加，它們會留在 Final Cut 裡。
3. 改完後 File > Export XML…，存到 `EP/work/fcp/`，然後執行 `/fcp import`。

`.omc/smoke.json` 顯示 Final Cut 往返測試沒通過或沒做過時，先提醒使用者匯入後核對前兩個片段的畫面是否正確。

## import

檔案路徑取參數；沒給就用 `EP/work/fcp/` 裡最新的 `.fcpxml` 或 `.fcpxmld`。

```bash
python3 scripts/fcpxml_bridge.py import <檔案> --episode-dir EP -o EP/work/fcp/cut.fcp.json
python3 scripts/fcpxml_bridge.py diff EP/work/timeline/cut.json EP/work/fcp/cut.fcp.json \
  -o EP/work/fcp/diff.json
```

同一集第二次以上的匯入，diff 檔名加序號（`diff_2.json`），比較對象改為上一次的 `cut.locked.json`。

### 把差異變成理解

把 diff 的摘要給使用者，然後自己先歸納模式，例如：

- 尾巴普遍收緊幾格 → 我留的尾巴太長
- 被刪掉的片段有沒有共同點（都是 B-roll？都是重複的意思？都在段落結尾？）
- 被切開、拿掉中間的片段 → 中間有我沒發現的贅字或停頓
- 新增的片段 → 我漏掉了哪種素材
- 順序改變 → 敘事邏輯和我想的哪裡不同

只針對**看不出原因**的改動提問，最多兩題，用使用者容易回答的方式（「s3 整段拿掉，是內容重複還是畫面不好？」）。看得出原因的不要問。

把歸納出的每個模式記一筆：

```bash
python3 scripts/decide.py log --episode <ep> --type revision --key <代號> \
  --context "Final Cut 精修" --proposed "<我原本的做法>" --chosen "<使用者改成的做法>" \
  --reason "<使用者說的，或從 diff 看出來的>"
```

數字不用另外記，`diff.json` 會被 `/learn` 直接讀取。這裡不寫入 `preferences.md`，那是 `/learn` 的工作。

### 鎖定

- 複製 `cut.fcp.json` 為 `EP/work/timeline/cut.locked.json`。
- `episode.json`：`locked: true`。
- `finish_route` 的判斷：diff 的 `unparsed` 有標題、轉場、變速或複合片段，表示成片必須從 Final Cut 輸出，設為 `"fcp"`；否則用 AskUserQuestion 問使用者成片要從 Final Cut 輸出還是由這裡渲染（`"claude"`）。
- 更新 `EP/STATE.md`：階段「已鎖定」，下一步 `/finish`。

### 限制（如實告知使用者）

- 變速過的片段，匯回的 in／out 可能不準，字幕在那一段可能對不上。
- 複合片段、多機位片段不會被解析，只保留時間長度。
- 鎖定之後如果又在 Final Cut 改了剪接點，要再 `/fcp import` 一次，字幕才會跟著更新。

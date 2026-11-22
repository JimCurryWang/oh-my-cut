---
name: refine
description: 和使用者的剪輯軟體往返精修（依 episode.json 的 editor：剪映、Final Cut 或其他）。export：把組合好的時間軸交出去；import：從使用者精修後的結果還原時間軸、列出他改了什麼、記錄為學習證據並鎖定時間軸。/assemble 之後使用，或使用者說他精修完了、匯出了成片。
argument-hint: "export | import [檔案路徑]"
---

# /refine

這是整套流程裡學習訊號最密集的地方：使用者在剪輯軟體做的每個修改，都是他的習慣的直接證據。

先讀 `EP/episode.json` 的 `editor`（`jianying`／`fcp`／`other`；沒有這個欄位就用 AskUserQuestion 問一次並寫回）。三條支線只差「怎麼交出去」和「怎麼讀回來」，之後的歸納、記錄、鎖定都一樣。

| editor | export（交出去） | import（讀回來） |
|---|---|---|
| `jianying` 剪映／CapCut | 直接產生剪映草稿 | 使用者匯出成片 → `reconform.py` 從成片還原 |
| `fcp` Final Cut Pro | FCPXML | 使用者匯出 XML → `fcpxml_bridge.py import` |
| `other` 其他軟體 | FCPXML（DaVinci Resolve 可匯入）＋預覽與片段表 | 使用者匯出成片 → `reconform.py` |

## export

### jianying

```bash
.venv/bin/python scripts/jianying_bridge.py export EP/work/timeline/cut.json --episode-dir EP
```

會在剪映的草稿資料夾新增 `<episode>_粗剪_vNN`（不會覆蓋任何現有草稿），並寫 `EP/work/refine/handoff.json` 記下交出去的是哪一版。告訴使用者：

1. 打開剪映（已開著就回到首頁），草稿列表找到它。主軌是 spine，上面的視訊軌是 B-roll，音樂在音訊軌。
2. 自由精修。轉場、調色、貼紙、文字都可以加；變速和大幅縮放／裁切之後讀不回來，會列為「無法辨識」。
3. 精修完匯出成片，**不要加字幕**（字幕在 `/finish` 才做，時間要以鎖定後的時間軸為準），存到 `EP/exports/`，然後執行 `/refine import`。

腳本印出「結尾少了 N ms」：表示片段切到素材的最後一兩格，剪映量到的檔案長度較短，已自動縮短，告訴使用者即可。

### fcp

```bash
python3 scripts/fcpxml_bridge.py export EP/work/timeline/cut.json \
  --episode-dir EP -o EP/exports/<episode>_rough.fcpxml
```

連結的是 `raw_footage/` 的原始檔。告訴使用者：

1. Final Cut：File > Import > XML…，選這個檔案。會建立一個事件和專案；主故事線是 spine，B-roll 是連接片段，音樂在下方，各段起點有標記。片段名稱結尾的 `[02-arrival/s3]` 是我們的 id，請不要改名。
2. 自由修改。標題、轉場、調色、變速都可以加，它們會留在 Final Cut 裡。
3. 改完後 File > Export XML…，存到 `EP/work/refine/`，然後執行 `/refine import`。

`.omc/smoke.json` 顯示 Final Cut 往返測試沒通過或沒做過時，先提醒使用者匯入後核對前兩個片段的畫面是否正確。

### other

同 `fcp` 的指令產生 FCPXML（DaVinci Resolve：File > Import > Timeline 可讀；Premiere 對 FCPXML 1.10 的支援不完整），另外給使用者 `work/timeline/cut.preview.mp4` 與片段表作為對照。精修完請使用者匯出成片到 `EP/exports/`，然後 `/refine import`。

## import

### 還原時間軸

**fcp**：檔案路徑取參數；沒給就用 `EP/work/refine/` 裡最新的 `.fcpxml` 或 `.fcpxmld`。

```bash
python3 scripts/fcpxml_bridge.py import <檔案> --episode-dir EP -o EP/work/refine/cut.edited.json
```

**jianying／other**：檔案路徑取參數；沒給就用 `EP/exports/` 裡最新的影片並向使用者確認是哪一支。

```bash
.venv/bin/python scripts/reconform.py <成片> --cut EP/work/timeline/cut.json --episode-dir EP \
  -o EP/work/refine/cut.edited.json --music <cut.json 用到的音樂檔…>
```

它比對聲音（說話的片段，能準到影格）和畫面（B-roll、靜音片段），把成片還原成 cut.json，id 沿用我們的。印出的「信心偏低」片段和 `unparsed`（無法辨識的畫面：變速、縮放、特效、新的圖卡）要列給使用者，請他確認或說明，不要猜。音樂只確認「還在」，頭尾與音量量不到。

### 比較

```bash
python3 scripts/cut_diff.py EP/work/timeline/cut.json EP/work/refine/cut.edited.json \
  -o EP/work/refine/diff.json
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
  --context "<剪映／Final Cut> 精修" --proposed "<我原本的做法>" --chosen "<使用者改成的做法>" \
  --reason "<使用者說的，或從 diff 看出來的>"
```

數字不用另外記，`diff.json` 會被 `/learn` 直接讀取。這裡不寫入 `preferences.md`，那是 `/learn` 的工作。

### 鎖定

- 複製 `cut.edited.json` 為 `EP/work/timeline/cut.locked.json`。
- `episode.json`：`locked: true`。
- `finish_route`：成片要從剪輯軟體輸出（`"editor"`）還是由這裡渲染（`"claude"`）。剪映與 `other` 一律 `"editor"`（精修的調色、轉場只存在那裡）；`fcp` 的 diff 若有標題、轉場、變速或複合片段也是 `"editor"`，否則用 AskUserQuestion 問。
- 更新 `EP/STATE.md`：階段「已鎖定」，下一步 `/finish`。

### 限制（如實告知使用者）

- 變速過的片段：Final Cut 匯回的 in／out 可能不準；從成片還原則讀不出來（列在 `unparsed`）。
- 大幅縮放、裁切、特效、新的圖卡：從成片還原時讀不出來，只會標出位置。
- 複合片段、多機位片段（Final Cut）不會被解析，只保留時間長度。
- 鎖定之後如果又改了剪接點，要再 `/refine import` 一次，字幕才會跟著更新。

# 檔案格式

## episode.json（`video_editor/<episode>/episode.json`）

```json
{
  "episode": "2026-11-kyoto",
  "style": "cinematic-travel",
  "outline_mode": "A",
  "language": "zh",
  "fps": [30000, 1001],
  "size": [3840, 2160],
  "sequences": ["01-hook", "02-arrival", "03-market"],
  "locked": false,
  "finish_route": "fcp"
}
```

`fps` 是分數（29.97 = `[30000, 1001]`）。`sequences` 的順序就是 `/assemble` 的順序。
`locked: true` 之後，`work/timeline/cut.locked.json` 是唯一依據，各段落的 cut.json 不再修改。

## cut.json

```json
{
  "version": 1,
  "name": "02-arrival",
  "fps": [30000, 1001],
  "size": [3840, 2160],
  "spine": [
    {"id": "s1", "src": "raw_footage/A001.MOV", "in": 12.48, "out": 17.92,
     "role": "aroll", "note": "抵達車站的第一句話", "gain_db": 0},
    {"id": "g1", "gap": 0.5}
  ],
  "overlays": [
    {"id": "o1", "src": "raw_footage/B014.MOV", "in": 3.0, "out": 6.5, "at": 2.1,
     "role": "broll", "note": "月台空景"}
  ],
  "audio": [
    {"id": "m1", "src": "../../brand/music/calm_01.mp3", "in": 0, "out": 40, "at": 0, "gain_db": -18}
  ]
}
```

- `spine`：主故事線，依序相接，聽得到的口白都在這裡。`in`／`out` 是**素材**內的秒數。`mute: true` 表示只用畫面。
- `overlays`：蓋在 spine 上的畫面（B-roll）。`at` 是**時間軸**上的秒數。預設靜音；有 `gain_db` 才出聲。
- `audio`：音樂與音效，`at` 是時間軸秒數。
- `role`（`aroll`／`broll`／`timelapse`／`drone`…）和 `note` 請盡量填，`/learn` 靠它們歸納「我常刪哪一種」。
- 組合後的時間軸另有 `sections`（各段起點），匯出到 Final Cut 會變成標記。
- 從 Final Cut 匯回的檔案另有 `unparsed`（標題、轉場、變速等沒有進 cut.json 的元素）與 `origin`（被切開的片段原本的 id）。

## style.json（`taste/<style>/profile/style.json`）

`style.stats.json` 是腳本量出來的數字；`style.json` 是 skill 讀的最終版本，數字可以被我修正。

```json
{
  "style": "cinematic-travel",
  "video_length_s": [480, 720],
  "structure": {"hook_s": [8, 15], "intro_card": true, "chapters": "依地點", "ending": "回顧＋一句話"},
  "pacing": {"shot_len_median_s": 2.8, "shot_len_aroll_s": [3, 8], "shot_len_broll_s": [1.2, 3],
             "cuts_per_min": 18, "hook_cuts_per_min": 30, "tail_after_last_word_frames": 4},
  "captions": {"max_chars": 14, "lines": 1, "position": "下方置中", "font_feel": "圓體、粗",
               "size_pct_of_height": 5.5, "stroke": "深色描邊", "highlight": "關鍵詞變色",
               "punctuation": false, "animation": "無／淡入"},
  "color": {"look": "暖、低對比、陰影微抬", "brightness_yavg": 118, "saturation_avg": 96, "lut": null},
  "motion": {"transitions": ["直切為主", "段落間淡黑"], "zoom": "慢推", "graphics": ["地點字卡", "路線地圖"]},
  "audio": {"lufs": -14, "music_under_voice_db": -18, "music_alone_db": -8, "sfx": "少量環境音",
            "music_feel": "lo-fi、木吉他"},
  "grammar": {"broll_ratio": 0.45, "aroll_framing": "手持自拍、半身", "text_density": "低"},
  "do_not_copy": ["對方的 logo 動畫", "口頭禪", "片頭音樂"]
}
```

## taste/_me/decisions.jsonl

每行一筆，由 `scripts/decide.py log` 寫入：

```json
{"ts": "…", "episode": "2026-11-kyoto", "sequence": "01-hook", "type": "ab",
 "key": "hook-length", "context": "開場 A=6s 直接丟畫面 / B=12s 先講話",
 "proposed": "A / B", "chosen": "A", "reason": "太慢會被滑走"}
```

`key` 是短而穩定的規則代號（`hook-length`、`caption-size`、`broll-ratio`、`tail-hold`、`music-energy`…）。同一件事永遠用同一個 key，`/learn` 才數得出來。

## edits.jsonl（每個 cut.json 旁邊）

`scripts/cut_edit.py` 每次執行自動附加一行（操作、前後狀態、`by`、`why`）。不需要手動維護。

## work/fcp/diff.json

`scripts/fcpxml_bridge.py diff` 的輸出：`events`（每個片段的修剪、刪除、切開、新增、移動）、`habits`（頭尾修剪的統計）、`unparsed`。

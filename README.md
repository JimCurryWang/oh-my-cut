# Oh-my-cut

用 Claude Code 剪 YouTube 旅遊／生活 vlog 的工作流程。Claude 負責素材整理、大綱、粗剪、字幕與重複性的工作；精修在你的剪輯軟體（剪映／CapCut、Final Cut Pro 或其他）；每一次修正都會被記錄，讓下一集更接近你要的樣子。

## 第一次使用

```bash
cd Oh-my-cut
git init            # 還沒有 repo 的話
claude              # 在這個資料夾啟動 Claude Code
```

然後依序：

1. `/setup`：分「基本」與「完稿」兩層檢查工具，只裝缺的，印出檢查表，並做煙霧測試（Whisper；用剪映時做剪映相容測試，用 Final Cut 時做 FCPXML 往返）。完稿層（Node、疊加層引擎）可以等到 `/finish` 前再 `/setup finish`
2. 把 2–5 支參考影片放進 `taste/<風格名>/videos/`，執行 `/taste-profile <風格名>`
3. 填 `brand/brand.json`（字體、顏色、logo），把音樂放進 `brand/music/`

## 每一集

| 指令 | 做什麼 |
|---|---|
| `/new-episode 2026-11-kyoto` | 建資料夾，選 style 和大綱模式 |
| （把素材放進 `raw_footage/`） | |
| `/index` | 素材 → 逐字稿、縮圖、摘要 |
| `/outline` | 大綱，拆成數個大 cut |
| `/cut 01-hook` … | 逐段粗剪、看預覽、對話微調（每段之間 `/clear`） |
| `/assemble` | 接成完整時間軸 |
| `/refine export` → 在剪輯軟體精修 → `/refine import` | 讀回你的修改並鎖定時間軸 |
| `/finish` | 字幕、圖卡、成片 |
| `/learn` | 把這一集的修正變成規則（由你核准） |

## 結構

```
CLAUDE.md            Claude 每次都會讀的核心規則
.claude/skills/      上表的每個指令
.claude/agents/      四個 subagent：索引、風格分析、初稿、品管
scripts/             確定性的工作都在這裡（Claude 呼叫，你也可以直接用）
docs/schemas.md      cut.json 等檔案格式
brand/               你的品牌：字體、顏色、logo、音樂、專有名詞表
taste/<style>/       參考影片與快取的風格 profile
taste/_me/           你的偏好規則與決策紀錄
video_editor/<ep>/   每一集：raw_footage、references、exports、work（整個資料夾不進 git）
```

## 腳本

| 腳本 | 用途 |
|---|---|
| `preflight.sh` | 分層檢查工具、印出檢查表（不安裝） |
| `index_clip.py` | 單支素材 → proxy、逐字稿、切點、縮圖 |
| `render_cut.py` | `cut.json` → 預覽（預設）或成片（`--final`） |
| `cut_edit.py` | 逐格修改、增刪換片段（`trim`/`set`/`add`/`replace`…），自動記錄每次修改 |
| `assemble.py` | 各段 → 完整時間軸 |
| `jianying_bridge.py` | `cut.json` → 剪映草稿（不覆蓋現有草稿） |
| `reconform.py` | 從匯出的成片還原時間軸（聲音指紋＋畫面比對），任何剪輯軟體都適用 |
| `fcpxml_bridge.py` | 匯出到 Final Cut／DaVinci Resolve（FCPXML）、從 Final Cut 匯回 |
| `cut_diff.py` | 比較交出去與精修後的兩份 `cut.json`：修剪格數、刪除、切開、順序… |
| `captions.py` | 逐字稿 + 時間軸 → 字幕（`.srt`、Final Cut 可編輯的 `.fcpxml`）；檢查切點有沒有切在字中間 |
| `decide.py` | 記錄決策、彙整所有修正證據 |
| `taste_cache.py` | 風格 profile 的快取與量測統計 |

每個腳本都有 `--help`。

## 三條精修支線

每一集在 `episode.json` 的 `editor` 選一條，`/refine` 依它分支：

| `editor` | 交出去 | 讀回來 |
|---|---|---|
| `jianying` 剪映／CapCut | 直接產生剪映草稿 | 你匯出成片 → `reconform.py` 還原 |
| `fcp` Final Cut Pro | FCPXML | 你匯出 XML → `fcpxml_bridge.py import` |
| `other` 其他 | FCPXML（DaVinci Resolve 可讀）＋預覽 | 你匯出成片 → `reconform.py` 還原 |

剪映的草稿存檔後是加密的，所以改動是從**成片**讀回來的：說話的片段比對聲音（準到影格），B-roll 比對畫面。

## 已知限制

- **剪映草稿是用社群套件 pyJianYingDraft（0.3.1，非官方）產生的。** 已在剪映專業版 8.1.1（macOS）實測：草稿能開、切點正確。剪映改版可能讓它失效，失效時 `/setup` 的剪映相容測試會抓到。
- **從成片還原（`reconform.py`）讀不出：** 變速、大幅縮放或裁切、特效、新的圖卡（標出位置，列在 `unparsed`），以及音量與音樂的確切頭尾。畫面變化很慢的 B-roll 可能差 1 格。
- **Final Cut 匯入尚未在真實的 Final Cut 上驗證。** FCPXML 的匯出、匯回、差異比較已用合成素材測過往返一致，但實際匯入 Final Cut 的行為（特別是帶時間碼的相機素材）要靠 `/setup` 的往返測試確認。
- Whisper（mlx-whisper）的部分只能在 Apple Silicon 上執行，同樣由 `/setup` 的測試確認。
- 預覽上的片段 id 與時間碼需要有 `drawtext` 的 ffmpeg。Homebrew 一般的 `ffmpeg` 沒有，`/setup` 會裝 keg-only 的 `ffmpeg-full`，腳本自動使用它。
- **可編輯字幕（`captions.py fcpxml`）尚未在真實的 Final Cut 上驗證。** 字級、位置、描邊的數值單位以實際匯入為準：第一次先用 `--limit 3` 輸出樣片確認。
- HDR 素材：proxy 與 `--final` 渲染不做色調映射，顏色會偏灰；有 HDR 素材時成片請從剪輯軟體輸出。
- 變速、複合片段、多機位片段從 Final Cut 匯回時不會被解析。
- 不同資料夾裡同名的素材檔會互相覆蓋索引，請先改名。
- 疊加層引擎（HyperFrames 或 Remotion）的用法依它們自己的 skill 與文件，本專案只規定輸出規格。

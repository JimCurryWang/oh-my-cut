#!/usr/bin/env bash
# Oh-my-cut preflight: CHECKS ONLY. Never installs anything.
#
# 兩層：
#   基本  索引、粗剪、預覽（燒 id 與時間碼）、剪輯軟體往返    → env.json "ready"
#   完稿  字幕樣式與動態圖卡（疊加層引擎）                       → env.json "ready_finish"
#   選用  不影響就緒（剪映＋pyJianYingDraft、Final Cut Pro、yt-dlp、Homebrew）
# Prints a checklist, writes .omc/env.json, and lists the fix command for each gap.
# Usage: scripts/preflight.sh            (run from anywhere; works on macOS bash 3.2)
set -u
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT" || exit 1
mkdir -p .omc

ROWS=()          # "tier|mark|name|detail"
OK=(); MISS_CORE=(); MISS_FINISH=(); FIXES=()
have() { command -v "$1" >/dev/null 2>&1; }
row()  { ROWS+=("$1|$2|$3|$4"); }
pass() { row "$1" "✓" "$2" "${3:-}"; OK+=("$2"); }
info() { row "$1" "·" "$2" "${3:-}"; }
fail() {  # tier name detail fix
  row "$1" "✗" "$2" "${3:-缺少}"
  case "$1" in core) MISS_CORE+=("$2");; finish) MISS_FINISH+=("$2");; esac
  [ -n "${4:-}" ] && FIXES+=("$1|$2|$4")
}

# ---------------- 基本 ----------------
OS="$(uname -s)"; ARCH="$(uname -m)"
if [ "$OS" = "Darwin" ] && [ "$ARCH" = "arm64" ]; then pass core platform "$OS $ARCH"
else fail core platform "$OS ${ARCH}：Whisper 部分需要 Apple Silicon（其他平台請改用 faster-whisper）"; fi

# ffmpeg: prefer Homebrew's keg-only ffmpeg-full (has drawtext for burned-in ids)
FF=""; FP=""; FF_KIND=""
for d in /opt/homebrew/opt/ffmpeg-full/bin /usr/local/opt/ffmpeg-full/bin; do
  if [ -x "$d/ffmpeg" ] && [ -x "$d/ffprobe" ]; then FF="$d/ffmpeg"; FP="$d/ffprobe"; FF_KIND="ffmpeg-full"; break; fi
done
if [ -z "$FF" ] && have ffmpeg && have ffprobe; then
  FF="$(command -v ffmpeg)"; FP="$(command -v ffprobe)"; FF_KIND="PATH"
fi
if [ -n "$FF" ] && "$FF" -version >/dev/null 2>&1; then
  feats=""
  "$FF" -hide_banner -encoders 2>/dev/null | grep -q 'h264_videotoolbox' && feats="$feats videotoolbox"
  "$FF" -hide_banner -encoders 2>/dev/null | grep -q 'prores_ks' && feats="$feats prores"
  pass core ffmpeg "$("$FF" -version | head -1 | cut -d' ' -f3)（${FF_KIND}）[${feats# }]"
  if "$FF" -hide_banner -filters 2>/dev/null | grep -q ' drawtext '; then
    pass core drawtext "預覽可燒入片段 id 與時間碼"
  else
    fail core drawtext "這個 ffmpeg 沒有 drawtext：預覽不會有片段 id 與時間碼" \
      "brew install ffmpeg-full   # keg-only，不影響原本的 ffmpeg；腳本會自動使用它"
  fi
elif [ -n "$FF" ]; then
  FF=""; FP=""
  fail core ffmpeg "已安裝但無法執行（常見原因：相依函式庫升級）" "brew upgrade ffmpeg ffmpeg-full"
else
  fail core ffmpeg "" "brew install ffmpeg-full"
fi

PY=""
for c in python3.12 python3.11 python3.13 python3; do have "$c" && PY="$c" && break; done
if [ -n "$PY" ] && "$PY" -c 'import sys; sys.exit(0 if sys.version_info >= (3,10) else 1)'; then
  pass core python "$("$PY" --version 2>&1)"
else fail core python "需要 3.10 以上" "brew install python@3.12"; fi

VENV_FIX="${PY:-python3} -m venv .venv && .venv/bin/pip install -U pip mlx-whisper opencc-python-reimplemented"
if [ -x .venv/bin/python ]; then
  if .venv/bin/python -c 'import mlx_whisper' 2>/dev/null; then pass core whisper "mlx-whisper (.venv)"
  else fail core whisper "" ".venv/bin/pip install mlx-whisper"; fi
  if .venv/bin/python -c 'import opencc' 2>/dev/null; then pass core opencc "簡→繁 s2tw（只換字形，不換詞彙）"
  else fail core opencc "" ".venv/bin/pip install opencc-python-reimplemented"; fi
else
  fail core whisper "尚未建立 .venv" "$VENV_FIX"
  fail core opencc "尚未建立 .venv"
fi

# ---------------- 完稿 ----------------
if have node; then
  NODE_MAJOR="$(node -p 'process.versions.node.split(".")[0]')"
  if [ "$NODE_MAJOR" -ge 22 ]; then pass finish node "v$(node -p process.versions.node)"
  else fail finish node "目前 v${NODE_MAJOR}，疊加層引擎需要 >= 22" "brew upgrade node"; fi
else fail finish node "" "brew install node"; fi

ENGINE="$(cat .omc/overlay_engine 2>/dev/null || true)"
if [ -z "$ENGINE" ]; then
  fail finish overlay-engine "尚未選擇（/setup 會問；預設 hyperframes）"
  fail finish overlay-project "選好引擎後建立 ./overlay"
else
  pass finish overlay-engine "$ENGINE"
  if [ -d overlay ]; then pass finish overlay-project "./overlay"
  elif [ "$ENGINE" = "hyperframes" ]; then
    fail finish overlay-project "./overlay 不存在" "npx skills add heygen-com/hyperframes && npx hyperframes init overlay"
  else
    fail finish overlay-project "./overlay 不存在" "npx create-video --yes --blank overlay && (cd overlay && npx skills add remotion-dev/skills)"
  fi
fi

# ---------------- 選用 ----------------
if have brew; then info optional brew "$(brew --version | head -1)"
else info optional brew "未安裝：上面的修復指令需要它 → /bin/bash -c \"\$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)\""; fi
if have yt-dlp; then info optional yt-dlp "$(yt-dlp --version)"
else info optional yt-dlp "未安裝：只有用網址下載參考影片時需要 → brew install yt-dlp"; fi
JY="no"
for app in /Applications/VideoFusion-macOS.app /Applications/CapCut.app; do
  if [ -d "$app" ]; then
    JY="yes"; info optional jianying "$(basename "$app" .app) $(defaults read "$app/Contents/Info" CFBundleShortVersionString 2>/dev/null)"
    break
  fi
done
[ "$JY" = no ] && info optional jianying "未安裝（剪映專業版／CapCut）"
if [ -x .venv/bin/python ] && .venv/bin/python -c 'import pyJianYingDraft' 2>/dev/null; then
  info optional pyjianyingdraft "$(.venv/bin/pip show pyJianYingDraft 2>/dev/null | awk '/^Version/{print $2}')（產生剪映草稿）"
else
  info optional pyjianyingdraft "未安裝：用剪映時需要 → .venv/bin/pip install --only-binary :all: \"pyJianYingDraft==0.3.1\""
fi
FCP="no"
if [ -d "/Applications/Final Cut Pro.app" ]; then FCP="yes"; info optional final-cut-pro "已安裝"
else info optional final-cut-pro "未安裝"; fi

# ---------------- 檢查表 ----------------
print_tier() {  # tier title
  echo "$2"
  for r in ${ROWS[@]+"${ROWS[@]}"}; do
    IFS='|' read -r t mark name detail <<EOF
$r
EOF
    [ "$t" = "$1" ] && printf '  %s %-16s %s\n' "$mark" "$name" "$detail"
  done
}
verdict() { [ "$1" -eq 0 ] && echo "✓ 就緒" || echo "✗ 缺 $1 項"; }
NC=${#MISS_CORE[@]}; NF=${#MISS_FINISH[@]}

echo "Oh-my-cut 環境檢查表（$(date '+%Y-%m-%d %H:%M')）"
echo
print_tier core     "【基本】索引、粗剪、預覽、剪輯軟體往返"
echo
print_tier finish   "【完稿】字幕樣式、動態圖卡"
echo
print_tier optional "【選用】不影響就緒"
echo
echo "結果：基本 $(verdict "$NC")｜完稿 $(verdict "$NF")"
if [ ${#FIXES[@]} -gt 0 ]; then
  echo "修復指令："
  for f in "${FIXES[@]}"; do
    IFS='|' read -r t name cmd <<EOF
$f
EOF
    [ "$t" = core ] && label="基本" || label="完稿"
    printf '  [%s] %-16s %s\n' "$label" "$name" "$cmd"
  done
fi

json_list() { local first=1; for x in "$@"; do [ $first = 1 ] && first=0 || printf ', '; printf '"%s"' "$x"; done; }
{
  printf '{\n  "checked_at": "%s",\n' "$(date -u +%Y-%m-%dT%H:%M:%SZ)"
  printf '  "platform": "%s %s",\n' "$OS" "$ARCH"
  printf '  "python": "%s",\n' "$( [ -x .venv/bin/python ] && echo .venv/bin/python || echo "${PY:-python3}")"
  printf '  "ffmpeg": "%s",\n  "ffprobe": "%s",\n' "$FF" "$FP"
  printf '  "overlay_engine": "%s",\n' "$ENGINE"
  printf '  "jianying": "%s",\n' "$JY"
  printf '  "final_cut_pro": "%s",\n' "$FCP"
  printf '  "ok": [%s],\n' "$(json_list ${OK[@]+"${OK[@]}"})"
  printf '  "missing": [%s],\n' "$(json_list ${MISS_CORE[@]+"${MISS_CORE[@]}"})"
  printf '  "missing_finish": [%s],\n' "$(json_list ${MISS_FINISH[@]+"${MISS_FINISH[@]}"})"
  printf '  "ready": %s,\n' "$( [ "$NC" -eq 0 ] && echo true || echo false)"
  printf '  "ready_finish": %s\n}\n' "$( [ "$NF" -eq 0 ] && echo true || echo false)"
} > .omc/env.json
echo "（已寫入 .omc/env.json）"

[ "$NC" -eq 0 ] || exit 2
[ "$NF" -eq 0 ] || exit 3
exit 0

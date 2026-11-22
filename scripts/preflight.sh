#!/usr/bin/env bash
# Oh-my-cut preflight: CHECKS ONLY. Never installs anything.
# Writes .omc/env.json and prints the fix command for whatever is missing.
# Usage: scripts/preflight.sh            (run from the repo root)
set -u
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT" || exit 1
mkdir -p .omc

ok=();  missing=();  fixes=()
have() { command -v "$1" >/dev/null 2>&1; }
pass() { ok+=("$1"); printf '  ✓ %-18s %s\n' "$1" "${2:-}"; }
fail() { missing+=("$1"); fixes+=("$2"); printf '  ✗ %-18s 缺少 → %s\n' "$1" "$2"; }

echo "Oh-my-cut preflight"
OS="$(uname -s)"; ARCH="$(uname -m)"
printf '  · %-18s %s %s\n' "platform" "$OS" "$ARCH"
[ "$OS" = "Darwin" ] && [ "$ARCH" = "arm64" ] || echo "  ! 此流程以 macOS Apple Silicon 為準；其他平台 Whisper 部分需改用 faster-whisper"

if have brew; then pass brew "$(brew --version | head -1)"; else
  fail brew '/bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)"'; fi

if have ffmpeg && have ffprobe; then
  feats=""
  ffmpeg -hide_banner -filters 2>/dev/null | grep -q ' drawtext ' && feats="$feats drawtext"
  ffmpeg -hide_banner -encoders 2>/dev/null | grep -q 'h264_videotoolbox' && feats="$feats videotoolbox"
  ffmpeg -hide_banner -encoders 2>/dev/null | grep -q 'prores_ks' && feats="$feats prores"
  pass ffmpeg "$(ffmpeg -version | head -1 | cut -d' ' -f3) [${feats# }]"
else fail ffmpeg "brew install ffmpeg"; fi

if have node; then
  NODE_MAJOR="$(node -p 'process.versions.node.split(".")[0]')"
  if [ "$NODE_MAJOR" -ge 22 ]; then pass node "v$(node -p process.versions.node)"
  else fail node "brew install node   # 目前 v$NODE_MAJOR，疊加層引擎需要 >= 22"; fi
else fail node "brew install node"; fi

if have yt-dlp; then pass yt-dlp "$(yt-dlp --version)"; else fail yt-dlp "brew install yt-dlp"; fi

PY=""
for c in python3.12 python3.11 python3.13 python3; do have "$c" && PY="$c" && break; done
if [ -n "$PY" ] && "$PY" -c 'import sys; sys.exit(0 if sys.version_info >= (3,10) else 1)'; then
  pass python "$("$PY" --version 2>&1)"
else fail python "brew install python@3.12"; fi

VENV_FIX="${PY:-python3} -m venv .venv && .venv/bin/pip install -U pip mlx-whisper opencc-python-reimplemented"
if [ -x .venv/bin/python ]; then
  if .venv/bin/python -c 'import mlx_whisper' 2>/dev/null; then pass whisper "mlx-whisper (.venv)"
  else fail whisper ".venv/bin/pip install mlx-whisper"; fi
  if .venv/bin/python -c 'import opencc' 2>/dev/null; then pass opencc "簡→繁 (s2twp)"
  else fail opencc ".venv/bin/pip install opencc-python-reimplemented"; fi
else
  fail whisper "$VENV_FIX"
fi

# Overlay engine: exactly one, recorded in .omc/overlay_engine (hyperframes | remotion)
ENGINE="$(cat .omc/overlay_engine 2>/dev/null || true)"
if [ -z "$ENGINE" ]; then
  fail overlay-engine "尚未選擇 → 執行 /setup 選一個（預設 hyperframes）"
elif [ ! -d overlay ]; then
  if [ "$ENGINE" = "hyperframes" ]; then
    fail overlay-project "npx skills add heygen-com/hyperframes && npx hyperframes init overlay"
  else
    fail overlay-project "npx create-video --yes --blank overlay && (cd overlay && npx skills add remotion-dev/skills)"
  fi
else pass overlay-engine "$ENGINE (./overlay)"; fi

FCP="no"
if [ -d "/Applications/Final Cut Pro.app" ]; then FCP="yes"; pass final-cut-pro "installed"
else printf '  · %-18s %s\n' "final-cut-pro" "未安裝（選用；沒有就只走 Claude Code 路徑）"; fi

join() { local first=1; for x in "$@"; do [ $first = 1 ] && first=0 || printf ', '; printf '"%s"' "$x"; done; }
{
  printf '{\n  "checked_at": "%s",\n' "$(date -u +%Y-%m-%dT%H:%M:%SZ)"
  printf '  "platform": "%s %s",\n' "$OS" "$ARCH"
  printf '  "python": "%s",\n' "$( [ -x .venv/bin/python ] && echo .venv/bin/python || echo "${PY:-python3}")"
  printf '  "overlay_engine": "%s",\n' "$ENGINE"
  printf '  "final_cut_pro": "%s",\n' "$FCP"
  printf '  "ok": [%s],\n' "$(join ${ok[@]+"${ok[@]}"})"
  printf '  "missing": [%s],\n' "$(join ${missing[@]+"${missing[@]}"})"
  printf '  "ready": %s\n}\n' "$( [ ${#missing[@]} -eq 0 ] && echo true || echo false)"
} > .omc/env.json

echo
if [ ${#missing[@]} -eq 0 ]; then echo "全部就緒。結果已寫入 .omc/env.json"; exit 0; fi
echo "缺少 ${#missing[@]} 項。修復指令："
for f in "${fixes[@]}"; do echo "  $f"; done
echo "結果已寫入 .omc/env.json"
exit 2

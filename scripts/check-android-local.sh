#!/usr/bin/env bash
# 检查 TalkTool uni-app Android 本地/云打包前置条件（对齐小树学堂，不下载离线 SDK）。
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
MANIFEST="$ROOT/frontend/src/manifest.json"
ENV_PROD="$ROOT/frontend/.env.production"

ok=0
warn=0
fail=0

pass() { echo "✅ $*"; ok=$((ok + 1)); }
note() { echo "⚠️  $*"; warn=$((warn + 1)); }
need() { echo "❌ $*"; fail=$((fail + 1)); }

echo "=== TalkTool · Android 打包环境检查 ==="
echo

if [[ -n "${JAVA_HOME:-}" && -x "$JAVA_HOME/bin/java" ]]; then
  pass "JAVA_HOME=$JAVA_HOME ($("$JAVA_HOME/bin/java" -version 2>&1 | head -1))"
elif [[ -x /opt/homebrew/opt/openjdk@21/bin/java ]]; then
  note "未设 JAVA_HOME，可用: export JAVA_HOME=/opt/homebrew/opt/openjdk@21"
else
  need "未找到 Java。建议: brew install openjdk@21"
fi

SDK="${ANDROID_HOME:-${ANDROID_SDK_ROOT:-$HOME/Library/Android/sdk}}"
if [[ -d "$SDK/platforms" && -x "$SDK/platform-tools/adb" ]]; then
  pass "Android SDK: $SDK"
  [[ -x "$SDK/cmdline-tools/latest/bin/sdkmanager" ]] && pass "sdkmanager 可用" || note "cmdline-tools/latest 缺失"
else
  need "未找到 Android SDK（期望 $HOME/Library/Android/sdk 或 ANDROID_HOME）"
fi

if ls /Applications/HBuilderX*.app >/dev/null 2>&1; then
  pass "已安装 HBuilderX: $(ls -d /Applications/HBuilderX*.app | head -1)"
elif [[ -d "/Applications/HBuilderX.app" ]]; then
  pass "已安装 HBuilderX.app"
else
  need "未安装 HBuilderX。可: brew install --cask hbuilderx"
fi

if ls /Applications/Android\ Studio*.app >/dev/null 2>&1; then
  pass "已安装 Android Studio"
else
  note "未安装 Android Studio（离线 SDK 出包时建议安装）: brew install --cask android-studio"
fi

if [[ -f "$MANIFEST" ]]; then
  appid="$(python3 -c "import json; print(json.load(open('$MANIFEST')).get('appid') or '')" 2>/dev/null || true)"
  if [[ -n "$appid" ]]; then
    pass "manifest.json appid=$appid"
  else
    need "frontend/src/manifest.json 的 appid 为空 → 请到 https://dev.dcloud.net.cn/ 创建应用后填入"
  fi
  if python3 -c "import json; d=json.load(open('$MANIFEST')); raise SystemExit(0 if d.get('app-plus') else 1)" 2>/dev/null; then
    pass "manifest.json 已配置 app-plus（含麦克风等权限）"
  else
    need "manifest.json 缺少 app-plus 配置"
  fi
else
  need "缺少 $MANIFEST"
fi

if [[ -f "$ENV_PROD" ]] && grep -q 'VITE_API_BASE=https://talk.aidigitcloud.cn' "$ENV_PROD"; then
  pass "VITE_API_BASE 已指向生产 https://talk.aidigitcloud.cn"
elif [[ -f "$ENV_PROD" ]]; then
  note "请确认 $ENV_PROD 中 VITE_API_BASE 是否正确"
else
  need "缺少 $ENV_PROD"
fi

if [[ -d "$ROOT/frontend/node_modules/@dcloudio/uni-app-plus" ]]; then
  pass "已安装 @dcloudio/uni-app-plus"
else
  note "未安装 uni-app-plus。执行: cd frontend && npm install"
fi

OFFLINE_HINT="$HOME/DCloud/Android-SDK"
if [[ -d "$OFFLINE_HINT/HBuilder-Integrate-AS" ]]; then
  pass "发现离线 SDK 工程: $OFFLINE_HINT/HBuilder-Integrate-AS"
else
  note "未发现 ~/DCloud/Android-SDK/HBuilder-Integrate-AS（云打包可不装；本地出包需下载）"
fi

if [[ -d "$ROOT/frontend/dist/build/app" ]]; then
  pass "已有 CLI app 资源: frontend/dist/build/app"
else
  note "尚未生成 app 资源。执行: cd frontend && npm run build:app"
fi

echo
echo "汇总: ok=$ok warn=$warn fail=$fail"
echo "完整步骤见: scripts/build-android-local.md"
if [[ "$fail" -gt 0 ]]; then
  exit 1
fi
exit 0

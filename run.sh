#!/usr/bin/env bash
# 一键启动：建 venv、装依赖、起服务。
set -e
cd "$(dirname "$0")"

# 优先用 3.12/3.13（pandas wheel 更稳），否则用默认 python3
PY=""
for c in python3.13 python3.12 python3; do
  if command -v "$c" >/dev/null 2>&1; then PY="$c"; break; fi
done
echo "使用解释器：$PY ($($PY --version))"

if [ ! -d .venv ]; then
  "$PY" -m venv .venv
fi
# shellcheck disable=SC1091
source .venv/bin/activate

pip install -q --upgrade pip
pip install -q -r requirements.txt

echo "✅ 依赖就绪，启动服务 http://127.0.0.1:8000"
uvicorn app.main:app --reload --port 8000

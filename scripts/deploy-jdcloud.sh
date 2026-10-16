#!/usr/bin/env bash
# 把 TalkTool 部署到京东云：/opt/talktool + nginx talk.aidigitcloud.cn → :8793
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
REMOTE="${DEPLOY_HOST:-ubuntu@111.228.6.222}"
REMOTE_DIR="${DEPLOY_PATH:-/opt/talktool}"
STAGING="/tmp/talktool-deploy"
PORT="${DEPLOY_PORT:-8793}"
DOMAIN="${DEPLOY_DOMAIN:-talk.aidigitcloud.cn}"

echo "==> Build H5"
cd "${ROOT}/frontend"
if [ ! -d node_modules ]; then
  npm install
fi
npm run build:h5
if [ ! -f "${ROOT}/frontend/dist/build/h5/index.html" ]; then
  echo "missing frontend/dist/build/h5/index.html" >&2
  exit 1
fi

echo "==> Stage to ${REMOTE}:${STAGING}"
ssh "${REMOTE}" "rm -rf '${STAGING}' && mkdir -p '${STAGING}'"
rsync -az \
  --exclude '.git' \
  --exclude 'node_modules' \
  --exclude 'frontend/node_modules' \
  --exclude 'frontend/dist' \
  --exclude 'backend/.venv' \
  --exclude 'backend/.env' \
  --exclude 'backend/data' \
  --exclude '__pycache__' \
  --exclude '.DS_Store' \
  --exclude '_to_delete' \
  "${ROOT}/" "${REMOTE}:${STAGING}/"
rsync -az "${ROOT}/frontend/dist/build/h5/" "${REMOTE}:${STAGING}/frontend/dist/"

if [[ -f "${ROOT}/backend/.env" ]]; then
  echo "==> Upload local backend/.env as bootstrap (not committed)"
  scp "${ROOT}/backend/.env" "${REMOTE}:${STAGING}/backend/.env.localupload"
fi

echo "==> Install into ${REMOTE_DIR}, nginx, pm2"
ssh "${REMOTE}" bash -s <<REMOTE
set -euo pipefail
STAGING='${STAGING}'
REMOTE_DIR='${REMOTE_DIR}'
PORT='${PORT}'
DOMAIN='${DOMAIN}'

sudo mkdir -p "\${REMOTE_DIR}/backend/data" "\${REMOTE_DIR}/frontend/dist"
sudo rsync -a --delete \
  --exclude '.env' \
  --exclude 'backend/.env' \
  --exclude 'backend/.venv' \
  --exclude 'backend/data' \
  --exclude 'node_modules' \
  "\${STAGING}/" "\${REMOTE_DIR}/"
sudo rsync -a --delete "\${STAGING}/frontend/dist/" "\${REMOTE_DIR}/frontend/dist/"

if [[ -f "\${STAGING}/backend/.env.localupload" && ! -f "\${REMOTE_DIR}/backend/.env" ]]; then
  sudo cp "\${STAGING}/backend/.env.localupload" "\${REMOTE_DIR}/backend/.env"
fi
sudo rm -f "\${REMOTE_DIR}/backend/.env.localupload" "\${STAGING}/backend/.env.localupload"
if [[ ! -f "\${REMOTE_DIR}/backend/.env" ]]; then
  sudo cp "\${REMOTE_DIR}/backend/.env.example" "\${REMOTE_DIR}/backend/.env"
fi
sudo chown -R ubuntu:ubuntu "\${REMOTE_DIR}"
chmod 600 "\${REMOTE_DIR}/backend/.env"
# nginx 要能直接读语音文件：放行目录路径（只读），数据库等文件仍是 ubuntu 私有
mkdir -p "\${REMOTE_DIR}/backend/data/audio"
sudo chmod o+x /opt "\${REMOTE_DIR}" "\${REMOTE_DIR}/backend" "\${REMOTE_DIR}/backend/data"
chmod o+rx "\${REMOTE_DIR}/backend/data/audio"

python3 - <<'PY'
from pathlib import Path
import re
p = Path("${REMOTE_DIR}/backend/.env")
t = p.read_text()
updates = {
    "PUBLIC_BASE_URL": "https://${DOMAIN}",
    "CORS_ORIGINS": "https://${DOMAIN}",
}
for key, value in updates.items():
    line = f"{key}={value}"
    if re.search(rf"^{key}=", t, re.M):
        t = re.sub(rf"^{key}=.*$", line, t, count=1, flags=re.M)
    else:
        t = t.rstrip() + "\n" + line + "\n"
p.write_text(t)
print("env public url set")
PY

PY=python3
if command -v python3.12 >/dev/null 2>&1; then
  PY=python3.12
fi
if [[ ! -x "\${REMOTE_DIR}/backend/.venv/bin/python" ]]; then
  "\${PY}" -m venv "\${REMOTE_DIR}/backend/.venv"
fi
"\${REMOTE_DIR}/backend/.venv/bin/pip" install -q -i https://pypi.tuna.tsinghua.edu.cn/simple -r "\${REMOTE_DIR}/backend/requirements.txt"

sudo cp "\${REMOTE_DIR}/deploy/nginx-talktool.conf" /etc/nginx/conf.d/talktool.conf
sudo nginx -t
sudo systemctl reload nginx

pm2 delete talktool >/dev/null 2>&1 || true
pm2 start "\${REMOTE_DIR}/backend/.venv/bin/python" \
  --name talktool \
  --cwd "\${REMOTE_DIR}/backend" \
  -- -m uvicorn app.main:app --host 127.0.0.1 --port "\${PORT}" --proxy-headers
pm2 save

sleep 2
curl -fsS "http://127.0.0.1:\${PORT}/api/health"
echo
curl -fsS -o /dev/null -w "HTTPS %{http_code}\n" --resolve "\${DOMAIN}:443:127.0.0.1" "https://\${DOMAIN}/api/health"
curl -fsS -o /dev/null -w "H5 %{http_code}\n" --resolve "\${DOMAIN}:443:127.0.0.1" "https://\${DOMAIN}/"
rm -rf "\${STAGING}"
REMOTE

echo "==> Done → https://${DOMAIN}"

#!/usr/bin/env bash
set -Eeuo pipefail

[[ ${EUID} -eq 0 ]] || { echo "Run this installer as root." >&2; exit 1; }
required_files=(
  pyproject.toml requirements.lock
  data/special_registrations.json data/ignored_registrations.json
  deploy/lzib-movements.service deploy/lzib-routes-update.service
  deploy/lzib-routes-update.timer deploy/lzib-movements.env.example
)
for required_file in "${required_files[@]}"; do
  [[ -f $required_file ]] || {
    echo "Required project file is missing: $required_file" >&2
    exit 1
  }
done
command -v python3.12 >/dev/null || { echo "Python 3.12 is required." >&2; exit 1; }

APP_USER=lzib-movements
APP_DIR=/opt/lzib-movements
STATE_DIR=/var/lib/lzib-movements
STAGING_DIR=$(mktemp -d /tmp/lzib-movements-install.XXXXXX)
trap 'rm -rf "$STAGING_DIR"' EXIT
id "$APP_USER" >/dev/null 2>&1 || useradd --system --home-dir "$STATE_DIR" --shell /usr/sbin/nologin "$APP_USER"
install -d -o root -g "$APP_USER" -m 0750 "$APP_DIR"
install -d -o "$APP_USER" -g "$APP_USER" -m 0750 "$STATE_DIR"
cp -a . "$STAGING_DIR/source"
rm -rf "$STAGING_DIR/source/.venv" \
  "$STAGING_DIR/source/.pytest_cache" \
  "$STAGING_DIR/source/.mypy_cache" \
  "$STAGING_DIR/source/.ruff_cache"
rm -f "$STAGING_DIR/source/.env"
find "$STAGING_DIR/source" -type d -name __pycache__ -prune -exec rm -rf {} +
find "$STAGING_DIR/source/data" -maxdepth 1 -type f \
  \( -name '*.db' -o -name '*.db-*' -o -name '*.sqlite*' -o -name '*.log' -o -name '*.zip' \) \
  -delete
cp -a "$STAGING_DIR/source/." "$APP_DIR/"
python3.12 -m venv "$APP_DIR/.venv"
"$APP_DIR/.venv/bin/pip" install --disable-pip-version-check -r "$APP_DIR/requirements.lock"
"$APP_DIR/.venv/bin/pip" install --no-deps --no-build-isolation "$APP_DIR"
cp -n data/special_registrations.json "$STATE_DIR/" || true
cp -n data/ignored_registrations.json "$STATE_DIR/" || true
chown "$APP_USER:$APP_USER" "$STATE_DIR"/*.json

if [[ ! -f /etc/lzib-movements.env ]]; then
  install -o root -g "$APP_USER" -m 0640 deploy/lzib-movements.env.example /etc/lzib-movements.env
  echo "Created /etc/lzib-movements.env. Add both webhook URLs, then rerun this script." >&2
  exit 2
fi
chown root:"$APP_USER" /etc/lzib-movements.env
chmod 0640 /etc/lzib-movements.env
install -m 0644 deploy/lzib-movements.service deploy/lzib-routes-update.service \
  deploy/lzib-routes-update.timer /etc/systemd/system/
systemctl daemon-reload
sudo -u "$APP_USER" bash -c \
  'set -a; source /etc/lzib-movements.env; exec /opt/lzib-movements/.venv/bin/python -m lzib_movements update-routes'
sudo -u "$APP_USER" bash -c \
  'set -a; source /etc/lzib-movements.env; exec /opt/lzib-movements/.venv/bin/python -m lzib_movements --check-config'
systemctl enable lzib-routes-update.timer
echo "Validation passed. Services were not started. Run the documented dry run before enabling alerts."

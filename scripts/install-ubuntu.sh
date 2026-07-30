#!/usr/bin/env bash
set -Eeuo pipefail

[[ ${EUID} -eq 0 ]] || { echo "Run this installer as root." >&2; exit 1; }
[[ -f pyproject.toml && -f deploy/lzib-movements.service ]] || {
  echo "Run from a complete LZIB Movements checkout." >&2; exit 1;
}
command -v python3.12 >/dev/null || { echo "Python 3.12 is required." >&2; exit 1; }

APP_USER=lzib-movements
APP_DIR=/opt/lzib-movements
STATE_DIR=/var/lib/lzib-movements
id "$APP_USER" >/dev/null 2>&1 || useradd --system --home-dir "$STATE_DIR" --shell /usr/sbin/nologin "$APP_USER"
install -d -o root -g "$APP_USER" -m 0750 "$APP_DIR"
install -d -o "$APP_USER" -g "$APP_USER" -m 0750 "$STATE_DIR"
cp -a . "$APP_DIR/source.new"
rm -rf "$APP_DIR/source.new/.venv"
cp -a "$APP_DIR/source.new/." "$APP_DIR/"
rm -rf "$APP_DIR/source.new"
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

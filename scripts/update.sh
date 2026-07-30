#!/usr/bin/env bash
set -Eeuo pipefail
[[ ${EUID} -eq 0 ]] || { echo "Run as root." >&2; exit 1; }
APP_DIR=/opt/lzib-movements
was_active=false
systemctl is-active --quiet lzib-movements && was_active=true
systemctl stop lzib-movements || true
backup=$(mktemp -d /opt/lzib-movements-backup.XXXXXX)
cp -a "$APP_DIR/." "$backup/"
rollback() {
  echo "Update validation failed; restoring the previous application." >&2
  rm -rf "$APP_DIR"; mv "$backup" "$APP_DIR"
  $was_active && systemctl start lzib-movements
}
trap rollback ERR
git -C "$APP_DIR" pull --ff-only
"$APP_DIR/.venv/bin/pip" install --disable-pip-version-check -r "$APP_DIR/requirements.lock"
"$APP_DIR/.venv/bin/pip" install --no-deps --no-build-isolation "$APP_DIR"
sudo -u lzib-movements bash -c \
  'set -a; source /etc/lzib-movements.env; exec /opt/lzib-movements/.venv/bin/python -m lzib_movements --check-config'
rm -rf "$backup"
trap - ERR
$was_active && systemctl start lzib-movements
echo "Update validated successfully."

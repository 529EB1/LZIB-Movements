#!/usr/bin/env bash
set -Eeuo pipefail
[[ ${EUID} -eq 0 ]] || { echo "Run as root." >&2; exit 1; }
delete_data=false
[[ ${1:-} == "--delete-data" ]] && delete_data=true
systemctl disable --now lzib-movements.service lzib-routes-update.timer 2>/dev/null || true
rm -f /etc/systemd/system/lzib-movements.service \
  /etc/systemd/system/lzib-routes-update.service /etc/systemd/system/lzib-routes-update.timer
systemctl daemon-reload
rm -rf /opt/lzib-movements
if $delete_data; then
  rm -rf /var/lib/lzib-movements /etc/lzib-movements.env
  userdel lzib-movements 2>/dev/null || true
  echo "Persistent LZIB Movements data was explicitly deleted."
else
  echo "Preserved /var/lib/lzib-movements, /etc/lzib-movements.env, and the service user."
fi

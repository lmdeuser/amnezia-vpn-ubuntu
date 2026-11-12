#!/bin/bash
set -euo pipefail
export TMPDIR=/var/tmp/amnezia-vpn
name=$PACKAGE_NAME
version=$PACKAGE_VERSION
[[ $name == amneziavpn ]]
dpkg -i /input/package.deb
apt-get check
[[ $(dpkg-query -W -f='${Status}' "$name") == 'install ok installed' ]]
desktop-file-validate /usr/share/applications/AmneziaVPN.desktop
if ldd /opt/AmneziaVPN/bin/AmneziaVPN /opt/AmneziaVPN/bin/AmneziaVPN-service | grep -q 'not found'; then
    exit 1
fi
test -f /opt/AmneziaVPN/lib/x86_64-linux-gnu/qt6/plugins/iconengines/libqsvgicon.so
test -f /opt/AmneziaVPN/lib/x86_64-linux-gnu/qt6/plugins/imageformats/libqsvg.so
python3 - <<'PY'
from pathlib import Path
import shlex

parts = shlex.split(Path('/input/client-config.env').read_text())
values = [part.split('=', 1) for part in parts if '=' in part and not part.startswith('export=')]
if len(values) != 8:
    raise SystemExit('Expected eight client configuration values')
binary = Path('/opt/AmneziaVPN/bin/AmneziaVPN').read_bytes()
for name, value in values:
    if name.endswith('PUBLIC_KEY'):
        value = value.replace('\\n', '\n')
    if value.encode() not in binary:
        raise SystemExit(f'Missing client configuration: {name}')
print('PASS: Premium and self-hosted client configuration is embedded')
PY
timeout 10s /opt/AmneziaVPN/bin/AmneziaVPN-service >/var/log/amnezia-service-check.log 2>&1 || code=$?
[[ ${code:-124} == 124 ]]
unset code
runuser -u tester -- xvfb-run -a dbus-run-session -- bash -c '
set -euo pipefail
export HOME=/home/tester
/usr/bin/AmneziaVPN >"$HOME/app.log" 2>&1 &
app=$!
trap "kill $app 2>/dev/null || true" EXIT
for i in $(seq 1 45); do
    kill -0 "$app" || { cat "$HOME/app.log"; exit 1; }
    windows=$(xwininfo -root -tree | python3 /usr/local/bin/window-check.py)
    for window in $windows; do
        if xwininfo -id "$window" | grep -q "Map State: IsViewable"; then
            sleep 5
            kill -0 "$app"
            xwininfo -id "$window" | grep -E "Width:|Height:|Map State:"
            xwininfo -id "$window" | grep -q "Map State: IsViewable"
            exit 0
        fi
    done
    sleep 1
done
cat "$HOME/app.log"
exit 1
'
dpkg -r "$name"
[[ ! -e /usr/bin/AmneziaVPN ]]
test -f /home/tester/.config/AmneziaVPN.ORG/AmneziaVPN.conf
dpkg -i /input/package.deb
apt-get check
echo "PASS: $name $version install / service / GUI / Premium config / remove / reinstall"

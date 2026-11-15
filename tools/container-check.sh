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
svg_icon=/opt/AmneziaVPN/lib/x86_64-linux-gnu/qt6/plugins/iconengines/libqsvgicon.so
svg_image=/opt/AmneziaVPN/lib/x86_64-linux-gnu/qt6/plugins/imageformats/libqsvg.so
test -f "$svg_icon"
test -f "$svg_image"
if ldd /opt/AmneziaVPN/bin/AmneziaVPN /opt/AmneziaVPN/bin/AmneziaVPN-service "$svg_icon" "$svg_image" | grep -q 'not found'; then
    exit 1
fi
[[ $(patchelf --print-rpath "$svg_icon") == '$ORIGIN/../../../' ]]
[[ $(patchelf --print-rpath "$svg_image") == '$ORIGIN/../../../' ]]
shopt -s nullglob
for library in /opt/AmneziaVPN/lib/x86_64-linux-gnu/*.so*; do
    [[ $(patchelf --print-rpath "$library") == '$ORIGIN' ]]
done
shopt -u nullglob
python3 - <<'PY'
import shlex
from pathlib import Path

EXPECTED = {
    "PROD_AGW_PUBLIC_KEY",
    "PROD_S3_ENDPOINT",
    "FALLBACK_S3_ENDPOINT",
    "DEV_AGW_PUBLIC_KEY",
    "DEV_AGW_ENDPOINT",
    "DEV_S3_ENDPOINT",
    "FREE_V2_ENDPOINT",
    "PREM_V1_ENDPOINT",
}

parts = shlex.split(Path("/input/client-config.env").read_text(), comments=True)
values = {}
for part in parts:
    if part == "export":
        continue
    name, separator, value = part.partition("=")
    if separator and name in EXPECTED:
        values[name] = value
if set(values) != EXPECTED or any(not v for v in values.values()):
    raise SystemExit("Expected eight non-empty client configuration values")
binary = Path("/opt/AmneziaVPN/bin/AmneziaVPN").read_bytes()
for name, value in values.items():
    if name.endswith("PUBLIC_KEY"):
        value = value.replace("\\n", "\n")
    if value.encode() not in binary:
        raise SystemExit(f"Missing client configuration: {name}")
print("PASS: Premium and self-hosted client configuration is embedded")
PY
code=0
timeout 10s /opt/AmneziaVPN/bin/AmneziaVPN-service >/var/log/amnezia-service-check.log 2>&1 || code=$?
[[ $code -eq 124 ]]
runuser -u tester -- xvfb-run -a dbus-run-session -- bash -c '
set -euo pipefail
export HOME=/home/tester
/usr/bin/AmneziaVPN >"$HOME/app.log" 2>&1 &
app=$!
trap "kill $app 2>/dev/null || true; wait $app 2>/dev/null || true" EXIT
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

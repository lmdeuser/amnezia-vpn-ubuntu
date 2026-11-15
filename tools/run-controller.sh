#!/bin/bash
set -euo pipefail
umask 077
project=$(cd "$(dirname "$0")/.." && pwd -P)
export TMPDIR="$project/.state/tmp"
mkdir -p "$TMPDIR" "$project/.state/home"
[[ $(findmnt -n -o FSTYPE -T "$TMPDIR") != tmpfs ]]
if [[ -f $project/.state/controller.env ]]; then
    set -a
    source "$project/.state/controller.env"
    set +a
fi
xdg_default=${XDG_CONFIG_HOME:-$HOME/.config}
if [[ -n ${OSC_CONFIG:-} ]]; then
    config=$OSC_CONFIG
elif [[ -r $xdg_default/osc/oscrc ]]; then
    config=$xdg_default/osc/oscrc
else
    config=$HOME/.oscrc
fi
config=$(realpath "$config")
[[ -r $config ]]
client_config=$(realpath "${CLIENT_CONFIG_FILE:-$project/.state/client-config.env}")
[[ -r $client_config ]]
xdg_config=$(realpath -m "${XDG_CONFIG_HOME:-$(dirname "$(dirname "$config")")}")
export HOME="$project/.state/home"
export XDG_CONFIG_HOME="$xdg_config"
export OSC_CONFIG="$config"
export CLIENT_CONFIG_FILE="$client_config"
export AMNEZIA_CLOUD=1
export DOCKER_BUILDKIT=0
export PYTHONUNBUFFERED=1
cd "$project"
if [[ $# -eq 0 ]]; then
    set -- cycle
fi
exec python3 tools/obs_controller.py "$@"

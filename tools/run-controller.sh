#!/bin/bash
set -euo pipefail
project=$(cd "$(dirname "$0")/.." && pwd -P)
export TMPDIR="$project/.state/tmp"
mkdir -p "$TMPDIR" "$project/.state/home"
[[ $(findmnt -n -o FSTYPE -T "$TMPDIR") != tmpfs ]]
if [[ -f $project/.state/controller.env ]]; then
    set -a
    source "$project/.state/controller.env"
    set +a
fi
config=${OSC_CONFIG:-$HOME/.config/osc/oscrc}
[[ -r $config ]]
[[ -r $project/.state/client-config.env ]]
config_dir=$(dirname "$config")
xdg_config=${XDG_CONFIG_HOME:-$(dirname "$config_dir")}
docker_gid=$(stat -c %g /var/run/docker.sock)
exec docker run --rm --name amnezia-vpn-obs-controller \
  --user "$(id -u):$(id -g)" --group-add "$docker_gid" \
  --cpus=0.75 --memory=1g --pids-limit=256 --read-only \
  --volume "$project:$project" --workdir "$project" \
  --volume /var/run/docker.sock:/var/run/docker.sock \
  --volume /usr/bin/docker:/usr/local/bin/docker:ro \
  --volume "$config_dir:$config_dir:ro" \
  --env "HOME=$project/.state/home" \
  --env "XDG_CONFIG_HOME=$xdg_config" \
  --env "OSC_CONFIG=$config" \
  --env "CLIENT_CONFIG_FILE=$project/.state/client-config.env" \
  --env "TMPDIR=$TMPDIR" --env AMNEZIA_CLOUD=1 \
  --env DOCKER_BUILDKIT=0 --env PYTHONUNBUFFERED=1 \
  amnezia-vpn-obs-controller:1

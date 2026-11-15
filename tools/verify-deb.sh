#!/bin/bash
set -euo pipefail
if [[ $# -ne 3 ]]; then
    echo "Usage: $0 <deb-path> <package-name> <package-version>" >&2
    exit 2
fi
project=$(cd "$(dirname "$0")/.." && pwd -P)
export TMPDIR="${TMPDIR:-/var/tmp/amnezia-vpn}"
mkdir -p "$TMPDIR"
[[ $(findmnt -n -o FSTYPE -T "$TMPDIR") != tmpfs ]]
package=$(realpath "$1")
name=$2
version=$3
client_config=$(realpath "${CLIENT_CONFIG_FILE:-$project/.state/client-config.env}")
[[ -r $package ]]
[[ -r $client_config ]]
[[ $(dpkg-deb -f "$package" Package) == "$name" ]]
[[ $(dpkg-deb -f "$package" Version) == "$version" ]]
[[ $(dpkg-deb -f "$package" Architecture) == amd64 ]]
build_limits=()
if [[ ${DOCKER_BUILDKIT:-1} == 0 ]]; then build_limits=(--memory=1g --cpu-period=100000 --cpu-quota=75000); fi
docker build "${build_limits[@]}" --pull --tag amnezia-verifier:26.04 --file "$project/packaging/verifier.Dockerfile" "$project"
docker run --rm --network none --shm-size 512m --cpus=0.75 --memory=1g --pids-limit=256 \
  --mount "type=bind,src=$package,dst=/input/package.deb,readonly" \
  --mount "type=bind,src=$client_config,dst=/input/client-config.env,readonly" \
  --env "PACKAGE_NAME=$name" --env "PACKAGE_VERSION=$version" \
  amnezia-verifier:26.04

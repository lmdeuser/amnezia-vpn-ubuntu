#!/bin/bash
set -euo pipefail
umask 077
project=$(cd "$(dirname "$0")/.." && pwd -P)
mkdir -p "$project/.state"
exec 9>"$project/.state/cron.lock"
flock -n 9 || exit 0
log="$project/.state/controller.log"
if [[ -f $log && $(stat -c %s "$log") -gt 2097152 ]]; then mv -f -- "$log" "$log.previous"; fi
exec "$project/tools/run-controller.sh" >>"$log" 2>&1

#!/usr/bin/env bash
set -euo pipefail
docker info >/dev/null
# Names are deliberately fixed; never operate on the existing bot containers.
for name in cross-max-reactions cross-max-reactions-auth; do
  if docker inspect "$name" >/dev/null 2>&1; then
    if [[ "$(docker inspect -f '{{.State.Running}}' "$name")" == true ]]; then
      docker stop -t 20 "$name" >/dev/null
    fi
    docker rm "$name" >/dev/null
  fi
done
printf '%s\n' 'ROLLBACK_RESULT=reaction containers removed; existing services and volumes preserved'

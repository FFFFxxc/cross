#!/usr/bin/env bash
set -euo pipefail
DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
IMAGE="${MAX_REACTIONS_IMAGE:-cross-max-reactions:20261021.2}"
SERVICE=cross-max-reactions
AUTH=cross-max-reactions-auth
VOLUME=cross-max-reactions-data
COMMON=(--network host --cap-drop ALL --security-opt no-new-privileges:true
  --memory 256m --cpus 0.25 --pids-limit 64 --read-only
  --tmpfs /tmp:rw,noexec,nosuid,size=16m
  --mount "type=volume,source=$VOLUME,target=/data"
  --mount "type=bind,source=$DIR/settings.toml,target=/opt/service/max_reactions/settings.toml,readonly"
  --log-opt max-size=5m --log-opt max-file=2)

running() { [[ "$(docker inspect -f '{{.State.Running}}' "$1" 2>/dev/null || true)" == true ]]; }
exists() { docker inspect "$1" >/dev/null 2>&1; }

case "${1:-status}" in
  build)
    docker build --network host -t "$IMAGE" "$DIR"
    ;;
  auth|auth-bg)
    if running "$SERVICE" || running "$AUTH"; then
      echo 'REACTION_SESSION_IN_USE'; exit 1
    fi
    if exists "$AUTH"; then docker rm "$AUTH" >/dev/null; fi
    if [[ "$1" == auth-bg ]]; then
      docker run -d --name "$AUTH" --no-healthcheck "${COMMON[@]}" "$IMAGE" \
        python -m max_reactions auth
    else
      TTY=(); if [[ -t 0 ]]; then TTY=(-it); fi
      docker run "${TTY[@]}" --name "$AUTH" --no-healthcheck "${COMMON[@]}" "$IMAGE" \
        python -m max_reactions auth
    fi
    ;;
  start|dry-run)
    if running "$AUTH" || exists "$SERVICE"; then
      echo 'REACTION_CONTAINER_ALREADY_EXISTS_OR_AUTH_IN_PROGRESS'; exit 1
    fi
    docker run --rm --no-healthcheck "${COMMON[@]}" "$IMAGE" python -m max_reactions status
    EXTRA=(); if [[ "$1" == dry-run ]]; then EXTRA=(--dry-run); fi
    docker run -d --name "$SERVICE" --restart unless-stopped "${COMMON[@]}" "$IMAGE" \
      python -m max_reactions run "${EXTRA[@]}"
    ;;
  status)
    docker ps -a --filter "name=^/($SERVICE|$AUTH)$" --format '{{.Names}} {{.Status}}'
    docker run --rm --no-healthcheck "${COMMON[@]}" "$IMAGE" python -m max_reactions status
    ;;
  logs)
    docker logs --tail 30 "$SERVICE"
    ;;
  stop)
    for name in "$SERVICE" "$AUTH"; do
      if running "$name"; then docker stop -t 20 "$name"; fi
    done
    ;;
  *) echo 'Usage: manage.sh build|auth|auth-bg|start|dry-run|status|logs|stop'; exit 2 ;;
esac

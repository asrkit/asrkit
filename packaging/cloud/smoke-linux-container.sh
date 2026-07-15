#!/usr/bin/env bash
# 在没有 Python 的最小 Debian 容器中验证 Linux x64 onedir。
set -euo pipefail

if [[ "$(uname -s)" != "Linux" ]]; then
  echo "[error] The clean-container smoke requires a Linux Docker host." >&2
  exit 2
fi
if ! command -v docker >/dev/null 2>&1; then
  echo "[error] Docker is required for the clean-container smoke." >&2
  exit 2
fi
if ! command -v curl >/dev/null 2>&1; then
  echo "[error] curl is required for the clean-container smoke." >&2
  exit 2
fi

runtime_dir="${1:-dist/asrkit-cloud}"
runtime_dir="$(cd "$runtime_dir" && pwd)"
binary="$runtime_dir/asrkit-cloud"
if [[ ! -x "$binary" ]]; then
  echo "[error] Linux runtime executable not found: $binary" >&2
  exit 2
fi

image="${ASRKIT_CLOUD_CLEAN_IMAGE:-debian:bookworm-slim}"
container="asrkit-cloud-clean-${RANDOM}-$$"
token="asrkit-cloud-smoke-${RANDOM}-${RANDOM}-${RANDOM}-${RANDOM}-token"
audio="$(mktemp)"
printf 'not-a-real-wave' >"$audio"

cleanup() {
  docker rm --force "$container" >/dev/null 2>&1 || true
  rm -f "$audio"
}
trap cleanup EXIT

docker run \
  --detach \
  --name "$container" \
  --network host \
  --read-only \
  --tmpfs /data:rw,noexec,nosuid,size=64m \
  --cap-drop ALL \
  --security-opt no-new-privileges \
  --env "ASRKIT_GATEWAY_TOKEN=$token" \
  --volume "$runtime_dir:/runtime:ro" \
  "$image" \
  /bin/sh -c '
    if command -v python >/dev/null 2>&1 || command -v python3 >/dev/null 2>&1; then
      echo "[error] Target image unexpectedly contains Python." >&2
      exit 90
    fi
    /runtime/asrkit-cloud --embedded --parent-pid $$ --data-dir /data/runtime
  ' >/dev/null

ready=""
for _ in $(seq 1 60); do
  ready="$(docker logs "$container" 2>/dev/null | sed -n '/"event":"ready"/p' | head -n 1)"
  if [[ -n "$ready" ]]; then
    break
  fi
  if [[ "$(docker inspect --format '{{.State.Running}}' "$container")" != "true" ]]; then
    docker logs "$container" >&2
    echo "[error] asrkit-cloud exited before becoming ready." >&2
    exit 1
  fi
  sleep 1
done
if [[ -z "$ready" ]]; then
  docker logs "$container" >&2
  echo "[error] Timed out waiting for the ready event." >&2
  exit 1
fi

base_url="$(printf '%s' "$ready" | sed -n 's/.*"base_url":"\([^"]*\)".*/\1/p')"
child_pid="$(printf '%s' "$ready" | sed -n 's/.*"pid":\([0-9][0-9]*\).*/\1/p')"
if [[ -z "$base_url" || -z "$child_pid" ]]; then
  echo "[error] Invalid ready event: $ready" >&2
  exit 1
fi

health="$(curl --fail --silent --show-error "${base_url%/v1}/health")"
printf '%s' "$health" | grep -q '"distribution":"cloud"'

unauthorized="$(curl --silent --output /dev/null --write-out '%{http_code}' "$base_url/models")"
if [[ "$unauthorized" != "401" ]]; then
  echo "[error] Expected unauthenticated /models to return 401, got $unauthorized." >&2
  exit 1
fi

models="$(curl --fail --silent --show-error \
  --header "Authorization: Bearer $token" \
  "$base_url/models")"
printf '%s' "$models" | grep -q '"openai/whisper-1"'
printf '%s' "$models" | grep -q '"dashscope/qwen3-asr-flash"'

transcription_status="$(curl --silent --output /dev/null --write-out '%{http_code}' \
  --header "Authorization: Bearer $token" \
  --form 'model=missing/smoke-model' \
  --form "file=@$audio;type=audio/wav" \
  "$base_url/audio/transcriptions")"
if [[ "$transcription_status" != "404" ]]; then
  echo "[error] Expected the unknown-model transcription to return 404, got $transcription_status." >&2
  exit 1
fi

docker exec "$container" /bin/sh -c "kill -TERM $child_pid"
for _ in $(seq 1 30); do
  if [[ "$(docker inspect --format '{{.State.Running}}' "$container")" != "true" ]]; then
    break
  fi
  sleep 1
done
if [[ "$(docker inspect --format '{{.State.Running}}' "$container")" == "true" ]]; then
  docker logs "$container" >&2
  echo "[error] asrkit-cloud did not stop after SIGTERM." >&2
  exit 1
fi

logs="$(docker logs "$container" 2>&1)"
printf '%s' "$logs" | grep -q '"event":"shutdown","reason":"signal"'
exit_code="$(docker inspect --format '{{.State.ExitCode}}' "$container")"
if [[ "$exit_code" != "0" ]]; then
  printf '%s\n' "$logs" >&2
  echo "[error] Container exited with status $exit_code." >&2
  exit 1
fi

echo "Clean-container smoke passed: $image contains no Python."

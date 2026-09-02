#!/usr/bin/env bash
set -euo pipefail

readonly DEPLOY_ROOT="${DEPLOY_ROOT:-/srv/aik8s}"
readonly RELEASES_DIR="$DEPLOY_ROOT/releases"
readonly INCOMING_DIR="$DEPLOY_ROOT/.incoming"
readonly CURRENT_LINK="$DEPLOY_ROOT/current"
readonly STATE_FILE="$DEPLOY_ROOT/.deployed-revision"
readonly LOCK_FILE="$DEPLOY_ROOT/.deploy.lock"
readonly RELEASE_BASE_URL="${RELEASE_BASE_URL:-https://github.com/runzhliu/aik8s/releases/download/site-production}"

work_dir=""

log() {
  printf '[aik8s-pull-deploy] %s\n' "$*"
}

cleanup() {
  if [[ -n "$work_dir" && "$work_dir" == "$INCOMING_DIR/"* ]]; then
    rm -rf -- "$work_dir"
  fi
}

download() {
  local asset="$1"
  local destination="$2"
  local revision="$3"
  curl --fail --silent --show-error --location \
    --connect-timeout 10 --max-time 300 --retry 3 --retry-delay 2 \
    --header 'Cache-Control: no-cache' \
    --output "$destination" \
    "$RELEASE_BASE_URL/$asset?revision=$revision"
}

health_check() {
  curl --fail --silent --show-error \
    --connect-timeout 5 --max-time 20 --retry 5 --retry-delay 1 \
    --resolve aik8s.run:443:127.0.0.1 \
    --output /dev/null \
    https://aik8s.run/
}

validate_archive_paths() {
  local archive="$1"
  local entry part
  local -a parts

  while IFS= read -r entry; do
    if [[ "$entry" == /* ]]; then
      log "refusing archive with absolute path: $entry"
      return 1
    fi
    IFS='/' read -r -a parts <<< "$entry"
    for part in "${parts[@]}"; do
      if [[ "$part" == ".." ]]; then
        log "refusing archive with parent traversal: $entry"
        return 1
      fi
    done
  done < <(tar --list --gzip --file "$archive")
}

mkdir -p "$RELEASES_DIR" "$INCOMING_DIR"
exec 9>"$LOCK_FILE"
if ! flock --nonblock 9; then
  log "another deployment is running; exiting"
  exit 0
fi

remote_revision="$(curl --fail --silent --show-error --location \
  --connect-timeout 10 --max-time 30 --retry 3 --retry-delay 2 \
  --header 'Cache-Control: no-cache' \
  "$RELEASE_BASE_URL/revision.txt?poll=$(date +%s)" | tr -d '[:space:]')"

if [[ ! "$remote_revision" =~ ^[0-9a-f]{40}$ ]]; then
  log "invalid remote revision: $remote_revision"
  exit 1
fi

deployed_revision=""
if [[ -f "$STATE_FILE" ]]; then
  deployed_revision="$(tr -d '[:space:]' < "$STATE_FILE")"
fi
if [[ "$remote_revision" == "$deployed_revision" ]]; then
  log "revision $remote_revision is already active"
  exit 0
fi

work_dir="$(mktemp --directory "$INCOMING_DIR/$remote_revision.XXXXXX")"
trap cleanup EXIT

archive="$work_dir/aik8s-site.tar.gz"
checksum_file="$work_dir/aik8s-site.tar.gz.sha256"
manifest="$work_dir/manifest.json"

log "downloading revision $remote_revision"
download aik8s-site.tar.gz "$archive" "$remote_revision"
download aik8s-site.tar.gz.sha256 "$checksum_file" "$remote_revision"
download manifest.json "$manifest" "$remote_revision"

expected_checksum="$(awk 'NR == 1 {print $1}' "$checksum_file")"
if [[ ! "$expected_checksum" =~ ^[0-9a-f]{64}$ ]]; then
  log "invalid checksum file"
  exit 1
fi
actual_checksum="$(sha256sum "$archive" | awk '{print $1}')"
if [[ "$actual_checksum" != "$expected_checksum" ]]; then
  log "checksum mismatch for revision $remote_revision"
  exit 1
fi
if ! grep -Fq "\"revision\":\"$remote_revision\"" <(tr -d '[:space:]' < "$manifest"); then
  log "manifest revision does not match $remote_revision"
  exit 1
fi
if ! grep -Fq "\"sha256\":\"$expected_checksum\"" <(tr -d '[:space:]' < "$manifest"); then
  log "manifest checksum does not match the checksum asset"
  exit 1
fi

validate_archive_paths "$archive"

release_dir="$RELEASES_DIR/$remote_revision"
if [[ ! -d "$release_dir" ]]; then
  staged_dir="$work_dir/site"
  mkdir "$staged_dir"
  tar --extract --gzip --file "$archive" --directory "$staged_dir" \
    --no-same-owner --no-same-permissions
  if [[ ! -s "$staged_dir/index.html" ]]; then
    log "artifact does not contain a non-empty index.html"
    exit 1
  fi
  mv "$staged_dir" "$release_dir"
elif [[ ! -s "$release_dir/index.html" ]]; then
  log "existing release directory is incomplete: $release_dir"
  exit 1
fi

previous_target="$(readlink "$CURRENT_LINK" 2>/dev/null || true)"
next_link="$DEPLOY_ROOT/.current-next"
ln --symbolic --force --no-dereference "$release_dir" "$next_link"
mv --force --no-target-directory "$next_link" "$CURRENT_LINK"

if ! health_check; then
  log "health check failed; rolling back"
  if [[ -n "$previous_target" ]]; then
    ln --symbolic --force --no-dereference "$previous_target" "$next_link"
    mv --force --no-target-directory "$next_link" "$CURRENT_LINK"
    health_check || log "rollback completed, but the previous release is unhealthy"
  fi
  exit 1
fi

state_tmp="$DEPLOY_ROOT/.deployed-revision.next"
printf '%s\n' "$remote_revision" > "$state_tmp"
mv --force "$state_tmp" "$STATE_FILE"
log "activated revision $remote_revision"

#!/usr/bin/env bash
set -euo pipefail

mode="dry-run"
origin="http://127.0.0.1:8007"
private_url="https://prsnl.tail625ab9.ts.net"

usage() {
  printf '%s\n' \
    "Usage: $0 [--dry-run | --check | --apply]" \
    "" \
    "Configures Tailscale Serve only. It never enables Funnel or a public listener." \
    "--dry-run  Print the intended private mapping (default)." \
    "--check    Verify local/private health without changing Tailscale state." \
    "--apply    Apply HTTPS :443 -> http://127.0.0.1:8007, then verify it."
}

case "${1:---dry-run}" in
  --dry-run) mode="dry-run" ;;
  --check) mode="check" ;;
  --apply) mode="apply" ;;
  -h|--help) usage; exit 0 ;;
  *) usage >&2; exit 2 ;;
esac

if [[ "$mode" == "dry-run" ]]; then
  printf '%s\n' \
    "No changes made." \
    "Required mapping: HTTPS :443 (tailnet only) -> $origin" \
    "Apply command: tailscale serve --bg --https=443 $origin" \
    "Forbidden: tailscale funnel, Cloudflare routes, 0.0.0.0 API binds."
  exit 0
fi

command -v curl >/dev/null
command -v tailscale >/dev/null

curl --fail --silent --show-error "$origin/health" >/dev/null

if [[ "$mode" == "apply" ]]; then
  tailscale serve --bg --https=443 "$origin"
fi

tailscale serve status
curl --fail --silent --show-error "$private_url/health" >/dev/null

status_code="$(curl --silent --show-error --output /dev/null --write-out '%{http_code}' \
  "$private_url/api/v1/today")"
if [[ "$status_code" != "401" ]]; then
  printf 'Expected unauthenticated API v1 request to return 401; got %s.\n' "$status_code" >&2
  exit 1
fi

printf 'Private API verified at %s; API v1 authentication is enforced.\n' "$private_url"


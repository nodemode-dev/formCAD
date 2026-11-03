#!/usr/bin/env bash
set -euo pipefail

usage() {
  cat <<'EOF'
macos_sign.sh sign DIR        sign every Mach-O under DIR, innermost first, then verify each one
macos_sign.sh notarize FILE   submit a .dmg, .zip or .pkg to the notary service, wait, print the log
macos_sign.sh staple FILE     attach the ticket to a .dmg or .app and validate it
macos_sign.sh verify PATH     strict nested verification of an app or a folder
macos_sign.sh notarize-folder DIR   zip DIR with ditto and notarize the zip (tickets for each nested item)

Secrets come only from the environment:
  APPLE_SIGNING_IDENTITY    Developer ID Application identity (required for sign; "-" means ad hoc)
  APPLE_CERTIFICATE         base64 of the .p12 (optional: imported into a temporary keychain)
  APPLE_CERTIFICATE_PASSWORD
  APPLE_API_KEY, APPLE_API_ISSUER, APPLE_API_KEY_PATH   notary service API key, or
  APPLE_ID, APPLE_PASSWORD, APPLE_TEAM_ID               an Apple ID with an app-specific password
Optional: ENTITLEMENTS (path, default src-tauri/entitlements.plist next to this repo).
EOF
}

say() { printf '[sign] %s\n' "$*"; }
die() { printf '[sign] error: %s\n' "$*" >&2; exit 1; }
root="$(cd "$(dirname "$0")/../.." && pwd)"
keychain=""

cleanup() {
  if [ -n "$keychain" ]; then security delete-keychain "$keychain" >/dev/null 2>&1 || true; fi
}
trap cleanup EXIT

import_certificate() {
  [ -n "${APPLE_CERTIFICATE:-}" ] || return 0
  [ -n "${APPLE_CERTIFICATE_PASSWORD:-}" ] || die "APPLE_CERTIFICATE_PASSWORD is not set"
  local work pass
  work="$(mktemp -d)"
  pass="$(uuidgen)"
  keychain="$work/signing.keychain-db"
  printf '%s' "$APPLE_CERTIFICATE" | base64 --decode > "$work/cert.p12"
  security create-keychain -p "$pass" "$keychain"
  security set-keychain-settings -lut 3600 "$keychain"
  security unlock-keychain -p "$pass" "$keychain"
  security import "$work/cert.p12" -k "$keychain" -P "$APPLE_CERTIFICATE_PASSWORD" -T /usr/bin/codesign -T /usr/bin/security
  security set-key-partition-list -S apple-tool:,apple:,codesign: -s -k "$pass" "$keychain" >/dev/null
  security list-keychains -d user -s "$keychain" $(security list-keychains -d user | tr -d '"')
  rm -f "$work/cert.p12"
}

notary_args() {
  if [ -n "${APPLE_API_KEY:-}" ] && [ -n "${APPLE_API_ISSUER:-}" ] && [ -n "${APPLE_API_KEY_PATH:-}" ]; then
    printf '%s\n' --key "$APPLE_API_KEY_PATH" --key-id "$APPLE_API_KEY" --issuer "$APPLE_API_ISSUER"
  elif [ -n "${APPLE_ID:-}" ] && [ -n "${APPLE_PASSWORD:-}" ] && [ -n "${APPLE_TEAM_ID:-}" ]; then
    printf '%s\n' --apple-id "$APPLE_ID" --password "$APPLE_PASSWORD" --team-id "$APPLE_TEAM_ID"
  else
    die "no notary credentials in the environment (APPLE_API_KEY, APPLE_API_ISSUER, APPLE_API_KEY_PATH or APPLE_ID, APPLE_PASSWORD, APPLE_TEAM_ID)"
  fi
}

sign_tree() {
  local dir="$1" identity="${APPLE_SIGNING_IDENTITY:-}" ent="${ENTITLEMENTS:-$root/src-tauri/entitlements.plist}" f count=0
  [ -d "$dir" ] || die "$dir is not a folder"
  [ -n "$identity" ] || die "APPLE_SIGNING_IDENTITY is not set"
  import_certificate
  local flags=(--force --options runtime)
  if [ "$identity" = "-" ]; then flags+=(--timestamp=none); else flags+=(--timestamp); fi
  [ -f "$ent" ] && flags+=(--entitlements "$ent")
  local files=()
  while IFS= read -r f; do
    if file -b "$f" | grep -Eq 'Mach-O.*(executable|shared library|bundle|dynamically linked)'; then files+=("$f"); fi
  done < <(find "$dir" -type f ! -type l | awk -F/ '{print NF "\t" $0}' | sort -rn | cut -f2-)
  for f in "${files[@]}"; do
    codesign "${flags[@]}" --sign "$identity" "$f"
    count=$((count + 1))
  done
  for f in "${files[@]}"; do codesign --verify --strict "$f" || die "signature check failed: $f"; done
  say "signed and verified $count Mach-O files under $dir"
}

submit() {
  local file="$1" args=()
  while IFS= read -r line; do args+=("$line"); done < <(notary_args)
  xcrun notarytool submit "$file" "${args[@]}" --wait --output-format json | tee "$file.notary.json"
  grep -q '"status" *: *"Accepted"' "$file.notary.json" || {
    local id
    id="$(sed -n 's/.*"id" *: *"\([^"]*\)".*/\1/p' "$file.notary.json" | head -n 1)"
    [ -z "$id" ] || xcrun notarytool log "$id" "${args[@]}" || true
    die "notarization was not accepted for $file"
  }
  say "notarization accepted for $file"
}

cmd="${1:-}"
case "$cmd" in
  sign) sign_tree "${2:?folder}" ;;
  notarize) submit "${2:?file}" ;;
  notarize-folder)
    zipfile="$(mktemp -d)/$(basename "${2:?folder}").zip"
    ditto -c -k --keepParent "$2" "$zipfile"
    submit "$zipfile"
    ;;
  staple)
    xcrun stapler staple "${2:?file}"
    xcrun stapler validate "$2"
    ;;
  verify)
    codesign --verify --deep --strict --verbose=2 "${2:?path}"
    spctl --assess --type execute --verbose=2 "$2" || true
    ;;
  *) usage; exit 2 ;;
esac

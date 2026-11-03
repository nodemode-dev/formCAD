#!/usr/bin/env bash
set -euo pipefail

usage() {
  cat <<'EOF'
linux_appimage_sign.sh sign FILE.AppImage    embed a GPG signature and write FILE.AppImage.asc
linux_appimage_sign.sh verify FILE.AppImage  check the detached signature against the imported key

Secrets come only from the environment:
  APPIMAGE_GPG_PRIVATE_KEY   ASCII-armoured or base64 private key (required for sign)
  APPIMAGE_GPG_KEY_ID        key id or fingerprint to sign with (required)
  APPIMAGETOOL_SIGN_PASSPHRASE   passphrase of the key (required in CI)
The key id and fingerprint are published in the release notes; SHA256SUMS stays the primary check.
EOF
}

say() { printf '[sign] %s\n' "$*"; }
die() { printf '[sign] error: %s\n' "$*" >&2; exit 1; }

home=""
cleanup() { [ -z "$home" ] || rm -rf "$home"; }
trap cleanup EXIT

setup_gpg() {
  home="$(mktemp -d)"
  chmod 700 "$home"
  export GNUPGHOME="$home"
}

import_key() {
  [ -n "${APPIMAGE_GPG_PRIVATE_KEY:-}" ] || die "APPIMAGE_GPG_PRIVATE_KEY is not set"
  [ -n "${APPIMAGE_GPG_KEY_ID:-}" ] || die "APPIMAGE_GPG_KEY_ID is not set"
  if printf '%s' "$APPIMAGE_GPG_PRIVATE_KEY" | grep -q 'BEGIN PGP'; then
    printf '%s\n' "$APPIMAGE_GPG_PRIVATE_KEY" | gpg --batch --import
  else
    printf '%s' "$APPIMAGE_GPG_PRIVATE_KEY" | base64 --decode | gpg --batch --import
  fi
}

cmd="${1:-}"
file="${2:-}"
case "$cmd" in
  sign)
    [ -f "$file" ] || die "$file is not a file"
    setup_gpg
    import_key
    gpg --batch --pinentry-mode loopback --passphrase "${APPIMAGETOOL_SIGN_PASSPHRASE:?APPIMAGETOOL_SIGN_PASSPHRASE is not set}" \
      --local-user "$APPIMAGE_GPG_KEY_ID" --armor --detach-sign --output "$file.asc" "$file"
    if command -v appimagetool >/dev/null 2>&1; then
      work="$(mktemp -d)"
      abs="$(cd "$(dirname "$file")" && pwd)/$(basename "$file")"
      (cd "$work" && "$abs" --appimage-extract >/dev/null)
      SIGN=1 SIGN_KEY="$APPIMAGE_GPG_KEY_ID" APPIMAGETOOL_FORCE_SIGN=1 appimagetool --sign "$work/squashfs-root" "$file.signed"
      mv "$file.signed" "$file"
      rm -rf "$work"
      say "embedded signature written"
    else
      say "appimagetool not found, only the detached signature was written"
    fi
    gpg --batch --verify "$file.asc" "$file"
    say "signed $file with key $APPIMAGE_GPG_KEY_ID"
    ;;
  verify)
    [ -f "$file" ] && [ -f "$file.asc" ] || die "need $file and $file.asc"
    gpg --verify "$file.asc" "$file"
    ;;
  *) usage; exit 2 ;;
esac

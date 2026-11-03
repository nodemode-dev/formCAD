#!/usr/bin/env bash
FORMCAD_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
export FORMCAD_ROOT
fc_say() { printf '[formCAD] %s\n' "$*"; }
fc_die() { printf '[formCAD] error: %s\n' "$*" >&2; exit 1; }
fc_os() {
  case "$(uname -s 2>/dev/null)" in
    Darwin) echo macos ;;
    Linux) echo linux ;;
    MINGW*|MSYS*|CYGWIN*|*_NT-*) echo windows ;;
    *) echo unknown ;;
  esac
}
fc_python() {
  local c
  for c in python3.14 python3.13 python3.12 python3 python; do
    if command -v "$c" >/dev/null 2>&1 && "$c" -c 'import sys; raise SystemExit(0 if sys.version_info >= (3, 12) else 1)' 2>/dev/null; then
      echo "$c"
      return 0
    fi
  done
  return 1
}
fc_venv() {
  local act="$FORMCAD_ROOT/backend/venv/bin/activate"
  [ -f "$act" ] || act="$FORMCAD_ROOT/backend/venv/Scripts/activate"
  [ -f "$act" ] || fc_die "backend venv missing, run ./formCAD install"
  # shellcheck disable=SC1090
  source "$act"
}
fc_kernel_venv() {
  local act="$FORMCAD_ROOT/kernel/venv/bin/activate"
  [ -f "$act" ] || act="$FORMCAD_ROOT/kernel/venv/Scripts/activate"
  [ -f "$act" ] || fc_die "kernel venv missing, run ./formCAD install-kernel"
  # shellcheck disable=SC1090
  source "$act"
}
fc_mesher_venv() {
  local act="$FORMCAD_ROOT/mesher/venv/bin/activate"
  [ -f "$act" ] || act="$FORMCAD_ROOT/mesher/venv/Scripts/activate"
  [ -f "$act" ] || fc_die "mesher venv missing, run ./formCAD install-mesher"
  # shellcheck disable=SC1090
  source "$act"
}
fc_node_ok() {
  command -v node >/dev/null 2>&1 && node -e 'process.exit(Number(process.versions.node.split(".")[0]) >= 22 ? 0 : 1)'
}
fc_native_path() {
  if [ "$(fc_os)" = windows ] && command -v cygpath >/dev/null 2>&1; then cygpath -w "$1"; else printf '%s\n' "$1"; fi
}
fc_target_triple() {
  if [ -n "${FORMCAD_TARGET:-}" ]; then echo "$FORMCAD_TARGET"; return 0; fi
  command -v rustc >/dev/null 2>&1 || return 1
  rustc -vV | awk '/^host:/ {print $2}'
}
fc_exe() { [ "$(fc_os)" = windows ] && echo ".exe" || echo ""; }
fc_version() {
  sed -n "s/^export const VERSION = '\(.*\)';$/\1/p" "$FORMCAD_ROOT/frontend/src/version.ts" 2>/dev/null
}
fc_rust_env() {
  [ -d "$HOME/.cargo/bin" ] && PATH="$HOME/.cargo/bin:$PATH"
  export PATH
  unset RUSTC RUSTC_WORKSPACE_WRAPPER RUSTFLAGS CARGO_ENCODED_RUSTFLAGS CARGO_BUILD_RUSTFLAGS CARGO_BUILD_TARGET CARGO_TARGET_DIR CARGO_BUILD_TARGET_DIR CARGO_BUILD_RUSTC
  export RUSTC_WRAPPER="" CARGO_BUILD_RUSTC_WRAPPER=""
  if command -v rustup >/dev/null 2>&1 && rustup toolchain list 2>/dev/null | grep -q '^stable'; then
    export RUSTUP_TOOLCHAIN="${FORMCAD_RUST_TOOLCHAIN:-stable}"
  fi
}
fc_rust_fresh() {
  local target="${CARGO_TARGET_DIR:-$FORMCAD_ROOT/src-tauri/target}" now
  now="$(rustc -vV 2>/dev/null | tr '\n' ' ')"
  if [ -d "$target/release" ] && [ "$(cat "$target/.formcad-rustc" 2>/dev/null)" != "$now" ]; then
    fc_say "the Rust compiler differs from the one that built the Rust folder; cleaning it"
    ( cd "$FORMCAD_ROOT/src-tauri" && cargo clean )
  fi
  mkdir -p "$target"
  printf '%s' "$now" > "$target/.formcad-rustc"
}

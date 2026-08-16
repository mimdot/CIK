#!/usr/bin/env bash
# Career Intelligence — one command to run the desktop app.
#
#   ./run.sh              build whatever is missing or stale, then launch
#   ./run.sh --rebuild    force everything to be rebuilt first
#   ./run.sh --no-launch  build and install the menu entry, but don't start
#
# Both build steps (the PyInstaller API sidecar, then the app itself) are
# skipped when their output is newer than their sources, so a second run with
# nothing changed goes straight to launching.
#
# It also installs a desktop entry, which is the "one click": after the first
# run, "Career Intelligence" is in the application menu and starts the built
# binary directly, with no build step in the way.
#
# For distributable installers (.deb / .AppImage / .rpm) use the packaging
# path instead: cd dashboard && npm run tauri:build
set -euo pipefail

REPO="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
ENGINE="$REPO/phd_aggregator"
DASH="$REPO/dashboard"
TAURI="$DASH/src-tauri"
APP="$TAURI/target/release/app"

FORCE=0
LAUNCH=1
for arg in "$@"; do
  case "$arg" in
    --rebuild) FORCE=1 ;;
    --no-launch) LAUNCH=0 ;;
    -h|--help) sed -n '2,17p' "${BASH_SOURCE[0]}" | sed 's/^# \{0,1\}//'; exit 0 ;;
    *) echo "unknown option: $arg (try --help)" >&2; exit 2 ;;
  esac
done

need() {
  command -v "$1" >/dev/null 2>&1 || {
    echo "FAIL: '$1' is not installed — $2" >&2
    exit 1
  }
}

# True when $1 is missing, or any file under the remaining paths is newer than
# it. Build caches are pruned: they churn on every run and would otherwise
# report everything as permanently stale.
stale() {
  local target="$1"
  shift
  [ -e "$target" ] || return 0
  [ -n "$(find "$@" \
    \( -name __pycache__ -o -name node_modules -o -name .next -o -name target \) -prune \
    -o -newer "$target" -type f -print -quit 2>/dev/null)" ]
}

need rustc "install Rust from https://rustup.rs"
need cargo "install Rust from https://rustup.rs"
need npm "install Node.js 20+"
need python3 "install Python 3.11+"

# Tauri names external binaries with the host target triple; the bundler strips
# the suffix when it copies them next to the app.
TRIPLE="$(rustc -vV | awk '/^host:/ {print $2}')"
SIDECAR="$TAURI/sidecar/api/cik-api-$TRIPLE"

# --- 1. the FastAPI sidecar ---------------------------------------------------
if [ "$FORCE" = 1 ] || stale "$SIDECAR" \
  "$ENGINE/api" "$ENGINE/core" "$ENGINE/sources" "$ENGINE/cik-api.spec"; then
  echo "== building the API sidecar (PyInstaller — several minutes) =="
  python3 -c 'import PyInstaller' 2>/dev/null || {
    echo "FAIL: PyInstaller is missing — pip install -r $ENGINE/requirements.txt" >&2
    exit 1
  }
  (cd "$ENGINE" && python3 -m PyInstaller --noconfirm cik-api.spec)
  mkdir -p "$(dirname "$SIDECAR")"
  install -m 755 "$ENGINE/dist/cik-api" "$SIDECAR"
else
  echo "== API sidecar up to date =="
fi

# --- 2. the app: dashboard export + Tauri shell -------------------------------
[ -d "$DASH/node_modules" ] || {
  echo "== installing dashboard dependencies =="
  (cd "$DASH" && npm install)
}

# Build through the Tauri CLI, never plain `cargo build --release`.
#
# `cargo build` produces a binary that launches, opens its window, starts the
# sidecar — and renders NOTHING. A pure white screen: the frontend is not in
# it. Only the CLI runs the beforeBuildCommand and hands the asset embedding
# the export it expects, so `cargo build` alone yields a shell with no UI, and
# nothing in the build output says so. Verified both ways here, by screenshot.
#
# `--no-bundle` stops after the binary and skips the installer targets
# (.deb/.AppImage/.rpm), which take minutes and are a packaging concern, not
# something you need in order to run the app.
# Two staleness questions, not one. The binary's own timestamp does not settle
# it: a bare `cargo build` in this directory refreshes the binary WITHOUT
# rebuilding the frontend, so the shell can be newer than every source file
# while the UI inside it is old. `out/index.html` is the frontend's own output,
# so checking it against the frontend sources catches exactly that case — which
# is not hypothetical, it happened here and shipped a stale UI.
FRONTEND_SRC=("$DASH/app" "$DASH/components" "$DASH/lib" "$DASH/hooks"
  "$DASH/types" "$DASH/package.json" "$DASH/next.config.ts")
if [ "$FORCE" = 1 ] \
  || stale "$APP" "$TAURI/src" "$TAURI/Cargo.toml" "$TAURI/tauri.conf.json" \
       "${FRONTEND_SRC[@]}" \
  || stale "$DASH/out/index.html" "${FRONTEND_SRC[@]}"; then
  echo "== building the app (dashboard + desktop shell) =="
  (cd "$DASH" && TAURI=true npx tauri build --no-bundle)
  install -m 755 "$SIDECAR" "$TAURI/target/release/cik-api"
else
  echo "== app up to date =="
fi

# --- 4. the menu entry (the "one click") --------------------------------------
APPS="${XDG_DATA_HOME:-$HOME/.local/share}/applications"
mkdir -p "$APPS"
cat >"$APPS/career-intelligence.desktop" <<EOF
[Desktop Entry]
Type=Application
Version=1.0
Name=Career Intelligence
Comment=PhD and research opportunity aggregator
Exec="$APP"
Icon=$TAURI/icons/128x128.png
Terminal=false
Categories=Education;
StartupWMClass=app
EOF
update-desktop-database "$APPS" 2>/dev/null || true
echo "== menu entry installed: $APPS/career-intelligence.desktop =="

[ "$LAUNCH" = 1 ] || exit 0

# The shell kills the sidecar when its window closes, but that handler never
# runs if the shell is signalled instead (Ctrl-C in this terminal), which would
# leave the API orphaned on the port. Clean up after ourselves either way.
trap 'pkill -f "$TAURI/target/release/cik-api" 2>/dev/null || true' EXIT INT TERM

echo "== starting Career Intelligence =="
"$APP"

#!/usr/bin/env bash
# Astra — delete regenerable build output.
#
#   ./scripts/clean.sh              free the big three (cargo target,
#                                   PyInstaller build+dist, staged sidecars)
#   ./scripts/clean.sh --all        also drop node_modules and the HTTP cache
#   ./scripts/clean.sh --dry-run    print what it would free, delete nothing
#
# Everything here is produced by run.sh / run.ps1 / tauri build and comes back
# on the next build. Nothing here is tracked by git.
#
# It never touches data you cannot regenerate:
#   astra/astra.db          your opportunities and profile
#   astra/applicant.yaml    your applicant details
#   .env                    your keys
#   astra/.seen_positions.json, astra/reza results/, exported CSV/JSON/HTML
set -euo pipefail

REPO="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"

ALL=0
DRY=0
for arg in "$@"; do
  case "$arg" in
    --all) ALL=1 ;;
    --dry-run|-n) DRY=1 ;;
    -h|--help) sed -n '2,18p' "${BASH_SOURCE[0]}" | sed 's/^# \{0,1\}//'; exit 0 ;;
    *) echo "unknown option: $arg (try --help)" >&2; exit 2 ;;
  esac
done

TARGETS=(
  "dashboard/src-tauri/target"          # cargo, the single biggest item
  "dashboard/src-tauri/sidecar/api"     # staged PyInstaller sidecars
  "astra/build"                         # PyInstaller work dir
  "astra/dist"                          # PyInstaller output
  "dashboard/.next"
  "dashboard/out"
  "dashboard/.swc"
  "dashboard/tsconfig.tsbuildinfo"
  "dashboard/src-tauri/gen"             # tauri-generated schemas/icons
)
if [ "$ALL" = 1 ]; then
  TARGETS+=(
    "dashboard/node_modules"            # npm install restores it
    "astra/.http_cache.sqlite"
    "astra/.http_cache.sqlite-journal"
    "astra/.http_cache.sqlite-wal"
    "astra/.http_cache.sqlite-shm"
  )
fi

total_kb=0
for rel in "${TARGETS[@]}"; do
  path="$REPO/$rel"
  [ -e "$path" ] || continue
  kb=$(du -sk "$path" 2>/dev/null | cut -f1)
  total_kb=$((total_kb + kb))
  human=$(du -sh "$path" 2>/dev/null | cut -f1)
  if [ "$DRY" = 1 ]; then
    printf '  would free %8s  %s\n' "$human" "$rel"
  else
    printf '  removing   %8s  %s\n' "$human" "$rel"
    rm -rf -- "$path"
  fi
done

# Python bytecode caches, wherever they landed.
n=0
while IFS= read -r -d '' d; do
  kb=$(du -sk "$d" 2>/dev/null | cut -f1)
  total_kb=$((total_kb + kb))
  [ "$DRY" = 1 ] || rm -rf -- "$d"
  n=$((n + 1))
done < <(find "$REPO/astra" -type d -name __pycache__ -print0 2>/dev/null)
if [ "$n" -gt 0 ]; then
  [ "$DRY" = 1 ] && echo "  would remove $n __pycache__ directories" \
                 || echo "  removed $n __pycache__ directories"
fi

human_total=$(awk -v k="$total_kb" 'BEGIN{
  if (k >= 1048576) printf "%.2f GB", k/1048576;
  else if (k >= 1024) printf "%.1f MB", k/1024;
  else printf "%d KB", k }')

echo
if [ "$DRY" = 1 ]; then
  echo "would free $human_total in total. Run without --dry-run to do it."
else
  echo "freed $human_total. Next build restores everything."
fi
[ "$ALL" = 1 ] || echo "Add --all to also drop node_modules and the HTTP cache."

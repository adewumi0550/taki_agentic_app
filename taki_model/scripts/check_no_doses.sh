#!/usr/bin/env bash
# Fails if any tracked file contains something that looks like a pesticide
# dose, mixing ratio, or a pre-harvest / re-entry interval.
#
# TAKI must never emit an agrochemical rate. Rates are legally registered
# per-country, per-crop, per-product and they change; a rate hardcoded in a
# repo is a rate that goes out of date silently and poisons someone. The
# model is allowed to say a treatment exists and to name the placeholder
# <DOSE_FROM_REGISTRY>; the number itself comes from the live registry at
# serving time, never from here.
#
# Exit 0 = clean. Exit 1 = a dose-shaped string is present.
set -uo pipefail
cd "$(git rev-parse --show-toplevel)"

# This script necessarily contains the patterns it searches for, so it
# excludes itself. Anything else tracked by git is fair game.
SELF="taki_model/scripts/check_no_doses.sh"

# Each pattern is a number (or the placeholder-less remains of one) bound to
# a unit that only ever appears in a dose or an interval.
PATTERNS=(
  '[0-9][0-9.,]*[[:space:]]*(ml|mL|cc)[[:space:]]*(/|per[[:space:]]+)[[:space:]]*(l|L|litre|liter|gal)'
  '[0-9][0-9.,]*[[:space:]]*(g|kg|gram|grams)[[:space:]]*(/|per[[:space:]]+)[[:space:]]*(l|L|litre|liter)'
  '[0-9][0-9.,]*[[:space:]]*(kg|g|l|L|ml|mL|litre|liter)[[:space:]]*(/|per[[:space:]]+)[[:space:]]*(ha|hectare|acre)'
  '[0-9][0-9.,]*[[:space:]]*(days?|kwanaki|kwana)[[:space:]]+(before[[:space:]]+harvest|pre-?harvest)'
  '(days?|kwanaki)[[:space:]]+before[[:space:]]+harvest'
  '(pre-?harvest|re-?entry)[[:space:]]+interval[[:space:]]*(of|:|=)?[[:space:]]*[0-9]'
  '[0-9][0-9.,]*[[:space:]]*(sachets?|caps?fuls?|tablespoons?|teaspoons?)[[:space:]]*(/|per[[:space:]]+)'
)

files=$(git ls-files 2>/dev/null | grep -v -x -F "$SELF")
if [ -z "$files" ]; then
  echo "check_no_doses: no tracked files yet (nothing to scan)."
  exit 0
fi

fail=0
for p in "${PATTERNS[@]}"; do
  # -I skips binaries, -n gives line numbers, -E extended regex, -i case-insensitive
  if hits=$(echo "$files" | xargs grep -InEi -- "$p" 2>/dev/null); then
    if [ -n "$hits" ]; then
      echo "DOSE GUARD FAILED - pattern: $p"
      echo "$hits" | sed 's/^/    /'
      echo
      fail=1
    fi
  fi
done

if [ "$fail" -ne 0 ]; then
  cat >&2 <<'MSG'
--------------------------------------------------------------------------
A dose, mixing ratio or interval is present in a tracked file.
Replace the number with <DOSE_FROM_REGISTRY> and leave a comment saying why.
Rates are registered per country/crop/product and change; this repo must
never be the source of one.
--------------------------------------------------------------------------
MSG
  exit 1
fi

echo "check_no_doses: clean - no dose, ratio or interval found in tracked files."

#!/usr/bin/env bash
# Sort a flat folder of downloaded files into the right directory structure.
#
#   bash organise.sh                 # tidy the current directory in place
#   bash organise.sh ~/inky-apps     # tidy somewhere else
#
# Browsers save everything flat, but this project has files in three places:
# the top level, inkyapps/, and inkyapps/apps/. Copying a flat folder over
# with rsync therefore puts modules where Python will never find them.
#
# Safe to run repeatedly. It only moves files it recognises, and it works out
# where the two identically-named __init__.py files belong by looking inside
# them rather than trusting the filename.

set -euo pipefail
cd "${1:-.}"
echo "Organising $(pwd)"

mkdir -p inkyapps/apps

# Files that belong in inkyapps/
PACKAGE="buttons.py display.py fids.py geo.py layout.py tracker.py weather.py"
# Files that belong in inkyapps/apps/
APPS="apod.py base.py clock.py home.py planes.py"
# Everything else that's a top-level script stays where it is:
#   config.py doctor.py fidsmatch.py keys.py keys.example.py preview.py
#   run.py selftest.py serve.py

moved=0

for f in $PACKAGE; do
  if [ -f "$f" ]; then mv -f "$f" inkyapps/; echo "  inkyapps/$f"; moved=$((moved+1)); fi
done

for f in $APPS; do
  if [ -f "$f" ]; then mv -f "$f" inkyapps/apps/; echo "  inkyapps/apps/$f"; moved=$((moved+1)); fi
done

# There are two __init__.py files. Tell them apart by content: the apps one
# defines REGISTRY, the package one is just a docstring.
place_init() {
  local src="$1"
  [ -f "$src" ] || return 0
  if grep -q "REGISTRY" "$src"; then
    mv -f "$src" inkyapps/apps/__init__.py
    echo "  inkyapps/apps/__init__.py"
  else
    mv -f "$src" inkyapps/__init__.py
    echo "  inkyapps/__init__.py"
  fi
  moved=$((moved+1))
}

place_init "__init__.py"
# Browsers rename duplicates: __init__(1).py, __init__ (1).py, __init__-2.py...
for f in __init__*.py; do
  case "$f" in
    __init__.py) continue ;;
    *) [ -f "$f" ] && place_init "$f" ;;
  esac
done

# Some downloads arrive with their full original path preserved.
if [ -d mnt ]; then
  while IFS= read -r f; do
    base=$(basename "$f")
    case "$base" in
      __init__.py) place_init "$f" ;;
      *) if echo "$APPS" | grep -qw "$base"; then mv -f "$f" inkyapps/apps/
         elif echo "$PACKAGE" | grep -qw "$base"; then mv -f "$f" inkyapps/
         else mv -f "$f" .; fi
         echo "  rescued $base"; moved=$((moved+1)) ;;
    esac
  done < <(find mnt -type f -name '*.py')
  rm -rf mnt
  echo "  removed stray mnt/ tree"
fi

# Previews are illustrations, not part of the project.
rm -f preview-*.png selftest.png
find . -name __pycache__ -prune -exec rm -rf {} + 2>/dev/null || true

echo
echo "Moved $moved file(s). Resulting tree:"
find . -name '*.py' | sort | sed 's/^/  /'
echo
echo "Now run:  python doctor.py"

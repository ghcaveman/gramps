#!/usr/bin/env bash
# -------------------------------------------------------------------------
#
# check_banner.sh
#
# Checks that every changed *.py file contains the required GPL banner at the
# top of the file.
#
# Usage:
#   ./check_banner.sh            # will generate changed_files.txt if missing
#   CHANGED_FILE=path/to/file    # optional env var to override the list file
#
# Exit codes:
#   0 – all files have the correct banner
#   1 – at least one file is missing or has a different banner
#
# -------------------------------------------------------------------------

# ---- Configuration -------------------------------------------------------
CHANGED_FILE="${CHANGED_FILE:-changed_files.txt}"
BANNER_FILE="banner_template.txt"
BANNER_TMP=$(mktemp)

error() {
    echo "ERROR: $*" >&2
}

# ---- Step 1: (Re)generate the list of changed *.py files -----------------
# We always refresh the list so that newly added files (e.g., dummy.py) are
# included even if they were not present the last time the script ran.
echo "Generating $CHANGED_FILE …"
git diff --name-only functionality_base...HEAD \
    | grep -E '\.py$' > "$CHANGED_FILE"
# Inform about any untracked Python files (they are not included in the check)
UNTRACKED=$(git ls-files --others --exclude-standard | grep -E '\.py$' || true)
if [[ -n "$UNTRACKED" ]]; then
    echo "Note: the following untracked Python files are present but will not be checked:"
    echo "$UNTRACKED"
fi

if [[ ! -s "$CHANGED_FILE" ]]; then
    echo "No changed Python files to check."
    rm -f "$BANNER_TMP"
    exit 0
fi

# ---- Step 2: Load the banner template ------------------------------------
sed -e ':a' -e 'N' -e '$!ba' -e 's/\n\+$//' "$BANNER_FILE" > "$BANNER_TMP"

# ---- Step 3: Verify each changed file ------------------------------------
FAIL=0

while IFS= read -r pyfile; do
    [[ -z "$pyfile" ]] && continue
    if [[ ! -f "$pyfile" ]]; then
        error "File listed in $CHANGED_FILE does not exist: $pyfile"
        FAIL=1
        continue
    fi
    banner_line_count=$(wc -l < "$BANNER_TMP")
    head -n "$banner_line_count" "$pyfile" > "$pyfile.tmp.banner"
    if ! cmp -s "$BANNER_TMP" "$pyfile.tmp.banner"; then
        echo "Banner mismatch in: $pyfile"
        echo "---- Expected banner (first $banner_line_count lines) ----"
        cat "$BANNER_TMP"
        echo "---- Actual header in $pyfile ----"
        cat "$pyfile.tmp.banner"
        echo "----------------------------------------------------------"
        FAIL=1
    fi
    rm -f "$pyfile.tmp.banner"
done < "$CHANGED_FILE"

rm -f "$BANNER_TMP"

if [[ $FAIL -eq 0 ]]; then
    echo "All changed Python files contain the correct banner."
    exit 0
else
    echo "One or more files have an incorrect or missing banner."
    exit 1
fi

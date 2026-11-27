#!/usr/bin/env bash
# -------------------------------------------------------------------------
#
# check_banner.bash
#
# Checks that every *.py file changed on the branch starts with the Gramps
# GPL banner in banner_template.txt.
#
# The copyright line in the template is a placeholder: a file passes with any
# copyright line(s) there ("# Copyright (C) <years>  <name>"), one or more,
# including indented continuation lines. Everything else must match the
# template exactly. A leading "#!" line or coding line is allowed. CRLF and LF
# files both pass.
#
# Usage:
#   ./check_banner.bash [BASE]
#     BASE  branch or ref to compare against (default: functionality_base).
#           A bare branch name is looked up as origin/BASE if that exists.
#   BASE_BRANCH=gramps60 ./check_banner.bash     # same, via the environment
#   CHANGED_FILE=list.txt ./check_banner.bash    # where to write the file list
#   BANNER_FILE=path/to/banner_template.txt      # default: next to this script,
#                                                # else the current folder
#
# Exit codes:
#   0 - all files have the banner
#   1 - at least one file is missing it or has a different one
#   2 - usage or setup error
#
# -------------------------------------------------------------------------

error() {
    echo "ERROR: $*" >&2
}

usage() {
    sed -n '/^# Usage:/,/^# Exit codes:/p' "$0" | sed -e 's/^# \{0,1\}//' -e '$d'
}

# ---- Arguments -----------------------------------------------------------
case "${1:-}" in
    -h|--help) usage; exit 0 ;;
esac
if [[ $# -gt 1 ]]; then
    usage >&2
    exit 2
fi
BASE="${1:-${BASE_BRANCH:-functionality_base}}"

# Prefer the remote-tracking branch for a bare name, as the feature branches
# are compared against what is on origin.
if [[ "$BASE" != */* ]] && git rev-parse --verify -q "origin/$BASE" >/dev/null; then
    BASE="origin/$BASE"
fi
if ! git rev-parse --verify -q "$BASE" >/dev/null; then
    error "Base '$BASE' not found. Fetch it, or pass the branch to compare against."
    exit 2
fi

SCRIPT_DIR=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
if [[ -z "${BANNER_FILE:-}" ]]; then
    if [[ -f "$SCRIPT_DIR/banner_template.txt" ]]; then
        BANNER_FILE="$SCRIPT_DIR/banner_template.txt"
    else
        BANNER_FILE="banner_template.txt"
    fi
fi
if [[ ! -f "$BANNER_FILE" ]]; then
    error "Banner template not found: $BANNER_FILE"
    exit 2
fi

CHANGED_FILE="${CHANGED_FILE:-changed_files.txt}"
# Remember whether the list existed before we started so we can clean up.
INITIAL_EXISTS=0
[[ -f "$CHANGED_FILE" ]] && INITIAL_EXISTS=1

cleanup() {
    if [[ $INITIAL_EXISTS -eq 0 ]]; then
        rm -f "$CHANGED_FILE"
    fi
}
trap cleanup EXIT

# ---- Step 1: list the changed *.py files ---------------------------------
# Added, copied, modified and renamed files; deleted ones have nothing to check.
echo "Comparing against $BASE ..."
git diff --name-only --diff-filter=ACMR "$BASE...HEAD" \
    | grep -E '\.py$' > "$CHANGED_FILE"

UNTRACKED=$(git ls-files --others --exclude-standard | grep -E '\.py$' || true)
if [[ -n "$UNTRACKED" ]]; then
    echo "Note: these untracked Python files are not checked:"
    echo "$UNTRACKED"
fi

if [[ ! -s "$CHANGED_FILE" ]]; then
    echo "No changed Python files to check."
    exit 0
fi

# ---- Step 2: check each file ---------------------------------------------
# Prints nothing and exits 0 when the banner matches; otherwise prints the
# first difference and exits 1.
check_one() {
    awk -v tpl="$BANNER_FILE" '
        function trim(s) { sub(/\r$/, "", s); sub(/[ \t]+$/, "", s); return s }
        function is_copyright(s) { return s ~ /^#[ \t]*Copyright[ \t]+(\([Cc]\)|©)/ }
        BEGIN {
            n = 0
            while ((getline line < tpl) > 0) t[++n] = trim(line)
            while (n > 0 && t[n] == "") n--          # ignore trailing blank lines
        }
        { f[++m] = trim($0) }
        NR >= 200 { exit }
        END {
            i = 1
            if (f[i] ~ /^#!/) i++
            if (f[i] ~ /^#.*coding[:=]/) i++
            for (k = 1; k <= n; k++) {
                if (is_copyright(t[k])) {
                    if (!is_copyright(f[i])) {
                        printf "line %d: expected a copyright line, found \"%s\"\n", i, f[i]
                        exit 1
                    }
                    i++
                    # more copyright lines, or indented continuations of one
                    while (i <= m && (is_copyright(f[i]) || f[i] ~ /^#[ \t][ \t][ \t][ \t]+[^ \t]/)) i++
                    continue
                }
                if (i > m || f[i] != t[k]) {
                    printf "line %d: expected \"%s\", found \"%s\"\n", i, t[k], (i > m ? "<end of file>" : f[i])
                    exit 1
                }
                i++
            }
        }
    ' "$1"
}

FAIL=0
HEADER_PRINTED=0
while IFS= read -r pyfile; do
    [[ -z "$pyfile" ]] && continue
    if [[ ! -f "$pyfile" ]]; then
        error "File listed in $CHANGED_FILE does not exist: $pyfile"
        FAIL=1
        continue
    fi
    if ! detail=$(check_one "$pyfile"); then
        if [[ $HEADER_PRINTED -eq 0 ]]; then
            echo "Files missing the GPL banner:"
            HEADER_PRINTED=1
        fi
        echo "  $pyfile  ($detail)"
        FAIL=1
    fi
done < "$CHANGED_FILE"

if [[ $FAIL -eq 0 ]]; then
    echo "All changed Python files contain the banner."
    exit 0
else
    echo "One or more files have an incorrect or missing banner."
    exit 1
fi

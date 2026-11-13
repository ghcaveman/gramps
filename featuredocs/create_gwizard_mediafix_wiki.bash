#!/usr/bin/env bash

# ---------------------------------------------------------------------------
# build_gwizard_mediafix_wiki.bash
# ---------------------------------------------------------------------------
# Helper script that runs the full documentation pipeline for the
# "gwizard_mediafix" feature.
#
# It performs the two stages defined by featuredocs/build_feature_docs.py:
#   1) --prepare – generate the AI prompt and starter README (if not already
#      present).
#   2) --build   – convert the README to MediaWiki, prepend/append the
#      standard header/footer, and run the image‑audit checker.
#
# The script also ensures that the audit output is captured in a side‑car
# text file (gwizard_mediafix_image_audit.txt) – this behaviour is added by
# the patched build_feature_docs.py.
#
# Usage:
#   ./featuredocs/build_gwizard_mediafix_wiki.bash
#
# You can adjust the parent branch if you need a different diff base.
# ---------------------------------------------------------------------------

set -euo pipefail

# Feature slug – must match the name used throughout the docs.
FEATURE="gwizard_mediafix"

# Parent branch for the isolated git diff.  Adjust if you work off a different
# base (e.g. a release branch).
PARENT_BRANCH="functionality_base"

# Resolve the repository root (the directory that contains the top‑level
# "gramps" folder).  This script lives in "featuredocs/", so the repo root is
# the parent of the script's directory.
REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

# ---- changed_files.txt lifecycle (mirrors check_banner.bash) --------------
# Allow the list file location to be overridden via the environment, e.g.
#   CHANGED_FILE=/tmp/my_changed_files.txt ./build_gwizard_mediafix_wiki.bash
CHANGED_FILE="${CHANGED_FILE:-changed_files.txt}"

# Remember whether the list file existed before we started so we can clean up
# a file that *this* script generated (and leave a pre‑existing one untouched).
INITIAL_EXISTS=0
if [[ -f "$CHANGED_FILE" ]]; then
    INITIAL_EXISTS=1
fi

# Always (re)generate the list of changed files so the --prepare step operates
# on the current diff against the parent branch, even for newly added files.
# Include added (A), copied (C), modified (M), etc. between the base branch
# and HEAD (check_banner.bash uses the same origin/<branch>...HEAD form).
echo "Generating $CHANGED_FILE …"
git diff --name-only origin/"$PARENT_BRANCH"...HEAD > "$CHANGED_FILE"

# Clean up changed_files.txt on exit if this script created it.  An EXIT trap
# (rather than inline cleanup) guarantees removal even if a later step fails
# under ``set -e``, matching check_banner.bash's intent of not leaving a
# generated list file behind.
cleanup_changed_files() {
    if [[ $INITIAL_EXISTS -eq 0 ]]; then
        rm -f "$CHANGED_FILE"
    fi
}
trap cleanup_changed_files EXIT

# Run the preparation step – this will create the AI prompt and a starter
# README if they do not already exist.  The changed file list is passed
# explicitly so the --prepare step uses the freshly generated list.
python "$REPO_ROOT/featuredocs/build_feature_docs.py" \
    "$FEATURE" \
    --parent "$PARENT_BRANCH" \
    --filelist "$CHANGED_FILE" \
    --prepare

# Run the build step – this generates the MediaWiki file and runs the image
# audit.  The audit output is saved to "gwizard_mediafix_image_audit.txt" by the
# patched Python script.
python "$REPO_ROOT/featuredocs/build_feature_docs.py" \
    "$FEATURE" \
    --parent "$PARENT_BRANCH" \
    --build

echo "All steps completed for feature '$FEATURE'."

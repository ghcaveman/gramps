#!/usr/bin/env bash

# ---------------------------------------------------------------------------
# create_gwizard_mediafix_wiki.bash -- wiki build script for GWizard Media Fix
# ---------------------------------------------------------------------------
# Made from featuredocs/create_example_wiki.bash (copied in from
# gramps_devutil); only the three values below are specific to this feature.
#
# Runs the full documentation pipeline in featuredocs/build_feature_docs.py:
#   1) --prepare  writes featuredocs/gwizard_mediafix_prompt.txt for your AI
#                 assistant, and a starter featuredocs/README_gwizard_mediafix.md
#                 if there isn't one yet.
#   2) --build    converts README_gwizard_mediafix.md to
#                 gwizard_mediafix.mediawiki, adds the standard header/footer,
#                 and audits the screenshots (the audit is also saved to
#                 gwizard_mediafix_image_audit.txt).
#
# Usage, from the repo root:
#   ./featuredocs/create_gwizard_mediafix_wiki.bash
# Then paste gwizard_mediafix_prompt.txt into your AI assistant, save its
# answer as README_gwizard_mediafix.md, take the screenshots it asks for, and
# run the script again to rebuild the .mediawiki page.
# ---------------------------------------------------------------------------

set -euo pipefail

# ---- Feature values ------------------------------------------------------
# Feature slug. It names every generated file (README_<slug>.md,
# <slug>_prompt.txt, <slug>.mediawiki, <slug>_image_audit.txt) and the
# screenshots (images/<slug>-<short-name>.png).
FEATURE="gwizard_mediafix"

# Name shown in the wiki page's infobox and intro.
PLUGIN_DISPLAY_NAME="GWizard Media Fix"

# Branch the feature was started from. Only changes made since this branch
# are documented.
PARENT_BRANCH="gwizard_filemerge"
# ---------------------------------------------------------------------------

# Resolve the repository root (the directory that contains the top‑level
# "gramps" folder).  This script lives in "featuredocs/", so the repo root is
# the parent of the script's directory.
REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

# ---- changed_files.txt lifecycle (mirrors check_banner.bash) --------------
# Allow the list file location to be overridden via the environment, e.g.
#   CHANGED_FILE=/tmp/my_changed_files.txt ./featuredocs/create_gwizard_mediafix_wiki.bash
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
# audit.  The audit output is saved to "<slug>_image_audit.txt" by the
# patched Python script.
python "$REPO_ROOT/featuredocs/build_feature_docs.py" \
    "$FEATURE" \
    --plugin-display-name "$PLUGIN_DISPLAY_NAME" \
    --parent "$PARENT_BRANCH" \
    --build

echo "All steps completed for feature '$FEATURE'."

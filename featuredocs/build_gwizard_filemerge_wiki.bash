#!/usr/bin/env bash

# ---------------------------------------------------------------------------
# build_gwizard_filemerge_wiki.bash
# ---------------------------------------------------------------------------
# Helper script that runs the full documentation pipeline for the
# "gwizard_filemerge" feature.
#
# It performs the two stages defined by featuredocs/build_feature_docs.py:
#   1) --prepare – generate the AI prompt and starter README (if not already
#      present).
#   2) --build   – convert the README to MediaWiki, prepend/append the
#      standard header/footer, and run the image‑audit checker.
#
# The script also ensures that the audit output is captured in a side‑car
# text file (gwizard_filemerge_image_audit.txt) – this behaviour is added by
# the patched build_feature_docs.py.
#
# Usage:
#   ./featuredocs/build_gwizard_filemerge_wiki.bash
#
# You can adjust the parent branch if you need a different diff base.
# ---------------------------------------------------------------------------

set -euo pipefail

# Feature slug – must match the name used throughout the docs.
FEATURE="gwizard_filemerge"

# Parent branch for the isolated git diff.  Adjust if you work off a different
# base (e.g. a release branch).
PARENT_BRANCH="functionality_base"

# Resolve the repository root (the directory that contains the top‑level
# "gramps" folder).  This script lives in "featuredocs/", so the repo root is
# the parent of the script's directory.
REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

# Run the preparation step – this will create the AI prompt and a starter
# README if they do not already exist.
python "$REPO_ROOT/featuredocs/build_feature_docs.py" \
    "$FEATURE" \
    --parent "$PARENT_BRANCH" \
    --prepare

# Run the build step – this generates the MediaWiki file and runs the image
# audit.  The audit output is saved to "gwizard_filemerge_image_audit.txt" by the
# patched Python script.
python "$REPO_ROOT/featuredocs/build_feature_docs.py" \
    "$FEATURE" \
    --parent "$PARENT_BRANCH" \
    --build

echo "All steps completed for feature '$FEATURE'."

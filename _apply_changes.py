#!/usr/bin/env python3
"""Apply all gw_repomergedialog.py changes from the git HEAD version."""

import os

filepath = os.path.join(
    os.path.dirname(os.path.abspath(__file__)),
    "gramps",
    "plugins",
    "tool",
    "gw_repomergedialog.py",
)

with open(filepath, "r", encoding="utf-8") as f:
    content = f.read()

print("Loaded:", len(content), "chars")
assert "class RepoMergeDialog" in content
print("OK - file loaded successfully")

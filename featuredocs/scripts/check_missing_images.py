#!/usr/bin/env python3
"""
check_missing_images.py - Audit Gramps feature docs for missing screenshots.

Scans a .mediawiki or .md file for image references ([[File:...]] and ![...](...))
and verifies that each referenced image exists in the local images directory.

Usage:
  1. Audit a specific file (defaults to checking ../images relative to this script):
       python3 featuredocs/scripts/check_missing_images.py featuredocs/MyFeature.mediawiki

  2. Audit a Markdown file:
       python3 featuredocs/scripts/check_missing_images.py featuredocs/README_MyFeature.md

  3. Specify a custom images folder:
       python3 featuredocs/scripts/check_missing_images.py featuredocs/MyFeature.mediawiki --images-dir path/to/images

Exit Codes:
  0 - All referenced images exist (or no images referenced).
  1 - One or more referenced images are missing, or input file was not found.
"""

import argparse
import re
import sys
from pathlib import Path

MEDIAWIKI_LAYOUT_KEYWORDS = {
    "thumb",
    "thumbnail",
    "frame",
    "frameless",
    "border",
    "right",
    "left",
    "center",
    "none",
    "baseline",
    "middle",
    "sub",
    "super",
    "text-top",
    "text-bottom",
    "top",
    "bottom",
}


def extract_mediawiki_images(text: str) -> list[tuple[str, str]]:
    """Return list of (filename, caption) from [[File:...]] tags."""
    matches = re.findall(
        r"\[\[File:([^|\]]+)(?:\|([^\]]*))?\]\]", text, flags=re.IGNORECASE
    )
    results = []
    for filename, params in matches:
        clean_name = Path(filename.strip()).name
        caption = "(No caption provided)"
        if params:
            parts = [p.strip() for p in params.split("|") if p.strip()]
            caption_parts = [
                p
                for p in parts
                if p.lower() not in MEDIAWIKI_LAYOUT_KEYWORDS
                and not re.match(r"^\d+px$", p.lower())
                and not p.lower().startswith(("link=", "alt=", "class="))
            ]
            if caption_parts:
                caption = caption_parts[-1]
        results.append((clean_name, caption))
    return results


def extract_markdown_images(text: str) -> list[tuple[str, str]]:
    """Return list of (filename, caption) from ![caption](path/to/file.png) tags."""
    matches = re.findall(r"!\[([^\]]*)\]\(([^)]+)\)", text)
    results = []
    for caption, raw_path in matches:
        # Strip optional title text inside quotes: ![alt](img.png "Title")
        path_only = raw_path.strip().split()[0].strip("\"'")
        clean_name = Path(path_only).name
        clean_caption = caption.strip() or "(No caption provided)"
        results.append((clean_name, clean_caption))
    return results


def audit_images(doc_path: Path, images_dir: Path) -> int:
    text = doc_path.read_text(encoding="utf-8")

    # Collect from both syntaxes so mixed drafts are caught cleanly
    raw_items = extract_mediawiki_images(text) + extract_markdown_images(text)

    if not raw_items:
        print(f"Image Audit ({doc_path.name}): No image references found.")
        return 0

    seen = set()
    unique_items = []
    for fname, caption in raw_items:
        if fname not in seen:
            seen.add(fname)
            unique_items.append((fname, caption))

    missing_count = 0
    print(f"\nImage Audit for: {doc_path}")
    print(f"Checking folder: {images_dir.resolve()}")
    print("-" * 68)

    for fname, caption in unique_items:
        target = images_dir / fname
        if target.is_file():
            status = "[EXISTS] "
        else:
            status = "[MISSING]"
            missing_count += 1
        print(f"  {status} {fname}")
        print(f"             Capture: {caption}")

    print("-" * 68)
    print(
        f"Summary: {len(unique_items) - missing_count}/{len(unique_items)} present, {missing_count} missing.\n"
    )
    return missing_count


def main() -> None:
    # Default images directory is featuredocs/images (one level up from featuredocs/scripts/)
    default_images_dir = Path(__file__).resolve().parent.parent / "images"

    parser = argparse.ArgumentParser(
        description="Verify that all images referenced in a Gramps doc file exist locally."
    )
    parser.add_argument(
        "doc_file",
        type=Path,
        help="Path to the .mediawiki or .md file to audit",
    )
    parser.add_argument(
        "--images-dir",
        type=Path,
        default=default_images_dir,
        help=f"Directory containing screenshots (default: {default_images_dir})",
    )

    args = parser.parse_args()

    if not args.doc_file.is_file():
        print(f"Error: Document not found: {args.doc_file}", file=sys.stderr)
        sys.exit(1)

    missing = audit_images(args.doc_file, args.images_dir)
    sys.exit(1 if missing > 0 else 0)


if __name__ == "__main__":
    main()

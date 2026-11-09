#!/usr/bin/env python3

#
# Gramps - a GTK+/GNOME based genealogy program
#
# Copyright (C) 2026  Kevin White
#
# This program is free software; you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation; either version 2 of the License, or
# (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License along
# with this program; if not, write to the Free Software Foundation, Inc.,
# 51 Franklin Street, Fifth Floor, Boston, MA 02110-1301 USA.
#

import argparse
import re
import sys
from pathlib import Path


def md_to_mediawiki(md_text: str) -> str:
    lines = md_text.splitlines()
    out = []
    in_code_block = False

    for line in lines:
        # Handle fenced code blocks
        if line.strip().startswith("```"):
            lang = line.strip().lstrip("`").strip()
            if not in_code_block:
                in_code_block = True
                out.append(f'<syntaxhighlight lang="{lang or "text"}">')
            else:
                in_code_block = False
                out.append("</syntaxhighlight>")
            continue

        if in_code_block:
            out.append(line)
            continue

        # Convert Headings (# -> =, ## -> ==, etc.)
        heading_match = re.match(r"^(#{1,6})\s+(.*)$", line)
        if heading_match:
            level = "=" * len(heading_match.group(1))
            out.append(f"{level} {heading_match.group(2).strip()} {level}")
            continue

        # Convert Images: ![Caption](images/foo.png) -> [[File:foo.png|thumb|Caption]]
        line = re.sub(
            r"!\[([^\]]*)\]\((?:[^)/]+/)*([^)]+)\)",
            r"[[File:\2|thumb|\1]]",
            line,
        )

        # Convert Links: [Text](https://url) -> [https://url Text]
        line = re.sub(r"\[([^\]]+)\]\((https?://[^)]+)\)", r"[\2 \1]", line)

        # Convert Bold (**text**) and Italic (*text*)
        line = re.sub(r"\*\*(.+?)\*\*", r"'''\1'''", line)
        line = re.sub(r"(?<!\*)\*(?!\*)(.+?)(?<!\*)\*(?!\*)", r"''\1''", line)

        # Convert Inline Code (`code`)
        line = re.sub(r"`([^`]+)`", r"<code>\1</code>", line)

        # Convert Ordered Lists (1. item -> # item)
        line = re.sub(r"^\s*\d+\.\s+", "# ", line)

        # Convert Unordered Lists (- item or * item -> * item)
        line = re.sub(r"^\s*[-*]\s+", "* ", line)

        out.append(line)

    return "\n".join(out)


def print_screenshot_checklist(mediawiki_text: str, image_dir: Path) -> int:
    # Matches [[File:filename.png|opt1|opt2|Caption text]]
    file_tags = re.findall(r"\[\[File:([^|\]]+)(?:\|([^\]]*))?\]\]", mediawiki_text)

    if not file_tags:
        print("\nScreenshot Checklist: No [[File:...]] tags found.")
        return 0

    # Deduplicate while preserving order
    seen = set()
    unique_files = []
    for filename, params in file_tags:
        clean_name = filename.strip()
        if clean_name in seen:
            continue
        seen.add(clean_name)

        # Extract the caption (usually the last non-keyword pipe-separated parameter)
        caption = "(No caption provided)"
        if params:
            parts = [p.strip() for p in params.split("|") if p.strip()]
            keywords = {
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
            caption_parts = [
                p
                for p in parts
                if p.lower() not in keywords and not re.match(r"^\d+px$", p.lower())
            ]
            if caption_parts:
                caption = caption_parts[-1]

        unique_files.append((clean_name, caption))

    missing_count = 0
    print(
        f"\nScreenshot Checklist ({len(unique_files)} image(s) referenced in {image_dir}):"
    )
    print("-" * 65)
    for fname, caption in unique_files:
        exists = (image_dir / fname).is_file()
        if exists:
            status = "[EXISTS] "
        else:
            status = "[MISSING]"
            missing_count += 1
        print(f"  {status} {fname}")
        print(f"             Capture: {caption}")
    print("-" * 65)
    return missing_count


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Convert Gramps feature Markdown docs to MediaWiki and audit screenshots."
    )
    parser.add_argument(
        "input_file",
        type=Path,
        help="Path to input .md file (or existing .mediawiki file when using --check-only)",
    )
    parser.add_argument(
        "--check-only",
        action="store_true",
        help="Audit an existing .mediawiki file for missing screenshots without writing changes",
    )
    parser.add_argument(
        "--header",
        type=Path,
        help="Optional MediaWiki header template file to prepend",
    )
    parser.add_argument(
        "--footer",
        type=Path,
        help="Optional MediaWiki footer template file to append",
    )
    parser.add_argument(
        "--images-dir",
        type=Path,
        help="Directory containing local screenshots (defaults to <input_dir>/images)",
    )

    args = parser.parse_args()

    if not args.input_file.is_file():
        print(f"Error: File not found: {args.input_file}", file=sys.stderr)
        sys.exit(1)

    image_dir = (
        args.images_dir if args.images_dir else (args.input_file.parent / "images")
    )

    if args.check_only:
        mediawiki_text = args.input_file.read_text(encoding="utf-8")
        missing = print_screenshot_checklist(mediawiki_text, image_dir)
        sys.exit(1 if missing > 0 else 0)

    header = args.header.read_text(encoding="utf-8") + "\n" if args.header else ""
    footer = "\n" + args.footer.read_text(encoding="utf-8") if args.footer else ""

    converted = md_to_mediawiki(args.input_file.read_text(encoding="utf-8"))
    final_mediawiki = header + converted + footer

    out_path = args.input_file.with_suffix(".mediawiki")
    out_path.write_text(final_mediawiki, encoding="utf-8")
    print(f"Generated: {out_path}")

    print_screenshot_checklist(final_mediawiki, image_dir)


if __name__ == "__main__":
    main()

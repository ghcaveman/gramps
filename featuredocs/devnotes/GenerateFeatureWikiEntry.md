To get an AI to generate accurate, Gramps-compliant documentation for a stacked feature branch, **your script should feed the AI only the isolated `git diff` against the parent branch along with the `.gpr.py` registration metadata and a strict MediaWiki/Markdown structural template**.

Because you use stacked feature branches, comparing against `main` or `master` would confuse the AI with changes from parent branches. Isolating the exact branch delta ensures the AI documents only what that specific feature introduces.

### 1. Gather Context Programmatically (Shell / Python Script)
Before calling an LLM API (or dumping context to a prompt file for an AI assistant), your script should extract three clean inputs:

* **The Branch Diff (Isolated to the Feature):** Run `git diff <parent-branch>...HEAD` so the AI sees only the code, UI strings, and options added in the current branch.
* **The `.gpr.py` File:** Pass the full registration file so the AI extracts exact plugin IDs, menu categories, and target Gramps versions.
* **UI Labels & Options:** Filter or highlight `_("...")` translatable strings and `Menu` / `Option` definitions in the diff, as these map directly to what users see in the Gramps GUI.

```bash
#!/usr/bin/env bash
PARENT_BRANCH="${1:-maintenance/gramps61}"
FEATURE_NAME=$(git rev-parse --abbrev-ref HEAD | sed 's/[^a-zA-Z0-9_-]/-/g')
OUT_DIR="docs/wiki-drafts/${FEATURE_NAME}"
mkdir -p "${OUT_DIR}/images"

# Extract only the changes introduced on this feature branch
git diff "${PARENT_BRANCH}...HEAD" -- "*.py" > "/tmp/${FEATURE_NAME}.diff"
```

### 2. Structure the System Prompt for Gramps Conventions
Gramps Wiki pages follow a consistent, practical layout for end-users (genealogists, not developers). Instruct the AI to follow these rules:

* **Audience & Tone:** Write for end-users using Gramps terminology (e.g., *Gramplet*, *Quickview*, *Category View*, *Active Person*, *Filter*, *Gedcom*). Avoid explaining internal Python classes unless it is a developer tool.
* **Required Sections:**
  1. **Overview / Purpose:** What genealogical problem this feature solves.
  2. **Prerequisites:** Any external Python libraries or Gramps version requirements.
  3. **Usage:** Step-by-step instructions starting from the exact Gramps menu path (e.g., *Reports -> Text Reports -> ...* or *Add a Gramplet*).
  4. **Options / Configuration:** A bulleted breakdown matching every GUI option/checkbox found in the diff.
  5. **Screenshot Placeholders:** Instruct the AI to insert explicit image placeholders using your collision-proof naming convention (e.g., `![[File:MyPlugin-${FEATURE_NAME}-options.png|thumb|Options dialog]]`) wherever a visual aid helps.
* **Anti-Hallucination Constraint:** Tell the AI: *"Only document UI controls, menu paths, and behaviors explicitly present in the provided `.gpr.py` and `git diff`. If a menu location is inherited from a parent branch and not visible in the diff, mark it as `[VERIFY MENU PATH]`."*

### 3. Example Prompt Builder Script
You can add this block to your script to generate a ready-to-use prompt file (or pipe it directly to a CLI tool like `llm`, `claude`, or a Python API script):

```bash
cat <<EOF > "/tmp/${FEATURE_NAME}_prompt.txt"
You are a technical documentation writer for the Gramps Genealogy Software Wiki.
Generate a complete, ready-to-paste MediaWiki page for the feature branch '${FEATURE_NAME}'.

### Rules:
1. Output ONLY valid MediaWiki markup (do NOT use Markdown syntax like #, **, or \`\`\`).
2. Wrap the page in the exact Gramps Wiki template structure provided below.
3. Base all UI labels, menu paths, and options strictly on the provided .gpr.py metadata and git diff.
4. Format screenshots as: [[File:${FEATURE_NAME}-<short-name>.png|thumb|Caption describing what to capture]]

### Required MediaWiki Template:
{{Third-party plugin}}
{{Languages|Addon:<PluginName>}}

{| class="wikitable" style="float:right; margin-left: 1em; width: 280px;"
! colspan="2" style="background:#e8eef5; text-align:center;" | <Plugin Display Name>
|-

| '''Addon ID''' || <code><plugin_id></code>
|-

| '''Type''' || <Gramplet / Report / Tool / View>
|-

| '''Status''' || {{Stable_branch}}
|-

| '''Target Version''' || Gramps 6.0 / 6.1
|-

| '''Source Code''' || {{github_url|<PluginDirectory>}}
|}

'''<Plugin Display Name>''' is a third-party [[Addons|addon]] that <one-sentence summary>.

== Usage ==
...

== Configure Options ==
...

== Prerequisites ==
...

[[Category:Addons]]
[[Category:Plugins]]

### Plugin Metadata (.gpr.py):
$(find . -name "*.gpr.py" -exec cat {} +)

### Feature Code Diff:
$(cat "/tmp/${FEATURE_NAME}.diff")
EOF

echo "Prompt generated at /tmp/${FEATURE_NAME}_prompt.txt"
```

### 4. Post-Processing for Stacked Branches
* **Keep `PARENT_BRANCH` Dynamic:** Pass the parent branch name as an argument to your script (`./gen_wiki_prompt.sh feature/base-ui`) so stacked branches only generate documentation for their incremental additions.
* **Screenshot Checklist:** Have the script parse the generated Markdown for `images/${FEATURE_NAME}-*.png` and print a checklist in your terminal reminding you which screenshots to capture in Gramps before converting to MediaWiki.

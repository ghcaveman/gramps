GoatGramps Changes
==================

This file lists the features in the `goatgramps/core` branch that are
**not** in Gramps `master`. It is maintained by hand and is the authoritative
answer to "what makes this fork different?".

The per-commit history is not useful for this purpose: the development
history contains work-in-progress commits (`Reverted last change`,
`Attempt 1 for pipeline fix`, `First trial, non-working`), so features are
grouped here by *what they do* rather than by commit.

Do **not** record these changes in `NEWS`. That file is generated from commit
messages by scripts and is overwritten by upstream on nearly every rebase
(upstream has modified it 166 times).


User-visible features
---------------------

* **Thumbnails in chart reports.** The ancestor, descendant and pedigree
  charts can render a small portrait for each person. Portraits are scaled to
  fit a fixed box rather than being placed at their native size, and an
  optional mask (SVG) can be applied to give them a rounded or oval shape.
  See the *Thumbnails* section of the report options.

* **Age at death and marriage duration in tree charts.** The descendant and
  ancestor charts show `d. 1975 (age 75)` beside a deceased person, and how
  long each marriage lasted (`m. 1925  (50 yrs)`). The marriage span is shown
  for every union that has ended, including the second and later marriages of
  a remarried partner. Both are controlled by a *Show age* option, which
  defaults to off and can be reverted to the old behaviour in Configure.

* **Instant chart updates.** Chart and report option boxes now apply their
  changes immediately instead of waiting for the dialog to close. A Configure
  option is provided to retain the previous on-close behaviour, and newlines
  are prevented from being entered into the boxes.

* **LDS-style GEDCOM extensions.** `libgedcom.py` parses a set of extra tags
  used by some third-party GEDCOM producers, including `_PREF`, `_PAREN`,
  `_ITALIC`, `_NAME`, `_PLAC_DEFN`, `_EVENT_DEFN` and the related definition
  record tags. Test data files exercising these tags are included.

* **GEDCOM import warnings.** Warnings for suppressed or unrecognised tags
  are reported once per distinct tag rather than once per occurrence, the
  message width has been adjusted, and all "ignored" flags are handled the
  same way. Several legacy import errors that previously aborted an import
  are now ignored, and the "Line ignored" message carries the line number.

* **FamilySearch fixes.** Persist FamilySearch ID links independently of the
  editor, avoid committing live editor edits, and fix the live-person Compare
  bug and the Open Person in FamilySearch button enable/disable state.
  *Merged from contributor dsblank (PR #2475).*

* **GWizard Media Fix tool.** A media maintenance tool that works on both
  the media records and the files on disk. It reports on media health, finds
  missing files and suggests matches, fixes broken or duplicate media
  references, consolidates scattered files into the base media folder as
  relative paths, renames files from a template (surname, given name, year,
  document type and so on), removes stale GEDCOM import notes, and can undo
  the last set of file moves. Each step previews its changes before applying
  them, and **Accept all hints** runs every step in one pass. See
  `featuredocs/ToolComparison.md` for how it compares with the built-in
  Media Manager.

* **GWizard Citation Fix tool.** A set of review steps for cleaning up
  repositories, sources, citations and citation notes: unpacking source and
  citation text that has several fields run together, consolidating and
  linking repositories, merging near-duplicate sources, tidying citation
  pages, dates and confidence, adding citation quality attributes, and
  linking media to citations. It can also write a citation analysis report,
  and **Accept all hints** runs every step without stopping to review. See
  `featuredocs/README_gwizard_citationfix.md`.

* **Link Citation Media checks the Media Fix rules.** Citation Fix relies on
  Media Fix. Before linking media to citations, it checks that each media
  item passes the Media Fix rules and lists any that do not, so they can be
  fixed in Media Fix first. This replaces the earlier media lock, which
  could never be set, and locking has been removed from both tools.

* **GWizard File Merge tool.** Compare another genealogy file (GEDCOM,
  Gramps XML or any other supported import format) side by side with the
  open Family Tree and merge it person by person. Likely matches are
  suggested, and each differing field can be taken or left with its own
  arrow button. Names, nickname and call name, events, families, children,
  alternate names, attributes, addresses, notes, web links, media and
  sources can all be compared. **Add as New** copies an unmatched person in
  and links them to relatives already in the tree. Before anything is
  written, notes, media, citations, sources and repositories the merge
  would leave dangling are offered for import, and the whole merge is
  applied as one transaction. A **GWizard File Merge (Alt)** variant puts
  the match settings at the top and lists only the most similar people in
  the tree, closest first. See `featuredocs/README_gwizard_filemerge.md`.

* **GWizard WikiTree Merge tool.** Search WikiTree for a person's profile
  and ancestors and merge the results into the Family Tree through the
  File Merge compare and merge windows. Merged data is given a shared
  WikiTree source and a dated citation, and the person keeps their
  WikiTree ID and profile link. It installs as an addon that depends on
  GWizard File Merge.

* **GWizard NARA Merge tool.** Search the U.S. National Archives (NARA)
  Catalog for records about a person, by name, married name, birth and
  death year and city, keywords or NAID, filtered by material type and
  online availability. Each result has a match score against the target
  person. **Merge...** opens the record in the File Merge window, next to
  what the person already has, to choose which citation and images to
  copy. Chosen images can be downloaded into a `NARA/<NAID>/` folder under
  the base media folder, and NARA's machine-read page text is kept as a
  Transcript note on each image. Needs a NARA API key in the
  `NARA_API_KEY` environment variable.

* **Multi-Archive Record Scan.** Checks every person in the Family Tree
  against each installed GWizard record source (WikiTree, NARA, ...),
  shows a progress meter, and counts likely matches at three match levels
  (given/middle/surname/birth, given/surname/birth, and given/surname
  above a score threshold). A merge window can be opened straight from a
  match. Record sources register themselves, so new archives can be added
  without changing the scan.

* **Extra columns in the main views.** New columns, which can be turned on
  in Configure View:
  * People: Confidence, Citation Count and Media Count.
  * Families: Number of Children, Event Count, Citation Count, Media Count
    and Confidence.
  * Events: Confidence, Citation Count and Media Count.
  * Sources: Repository.
  * Citations (list and tree): Media Count.

  Citation counts and Confidence include citations on names and events.
  Confidence is the highest level found among them. A new column starts
  hidden, next to the column that precedes it, even when a view's column
  layout was saved before the column existed. The column tab of Configure
  View also has a **Reset to Defaults** button, which restores the default
  columns, order and widths.

* **Platform button order in dialogs.** Glade and managed-window dialogs
  follow the GTK `gtk-alternative-button-order` setting, so buttons such as
  OK and Cancel appear in the order the platform expects. Assistants place
  Back and Next in the expected order too. Rows of buttons outside dialogs
  are left as they were.


Build and packaging
-------------------

* **Windows AIO build fixed.** The NSIS script now reserves its Unicode
  plugin DLLs from `Plugins\amd64-unicode` instead of `Plugins\unicode`.
  Recent NSIS releases stopped installing them to the old path, which caused
  the build to abort. This matches the fix on the upstream `aio-test` branch.

* **Check and Repair bugfix** if an image has an MD5 hash, it is kept rather than set to an empty string.

* **`create_env.bash`** at the repository root sets up a development
  environment.

* **Python packaging.** bsddb files are included in the AIO build again, and
  a pure-Python PyPI wheel installer replaces the previous pip invocation.


Tests and continuous integration
--------------------------------

* **Draw report tests.** A new `displayage_test.py` in
  `gramps/plugins/drawreport/test/` covers the age and marriage-span
  formatting. It builds a family tree in an in-memory SQLite database and
  renders both charts to disk, asserting on the resulting SVG.

  The accompanying `test/__init__.py` is required: without it
  `unittest discover` skips the directory entirely and the tests never run.

* **CI test artifacts.** The Gramps CI workflow uploads
  `test/data/tree_report_age_output/` as a `test-generated-data` artifact for
  14 days, so the generated charts can be downloaded and inspected after a
  run. The upload step uses `if: always()`, so the artifact is produced even
  when the suite fails.


Other fixes
-----------

* **XML export no longer leaks a file handle.** `GrampsXmlWriter.write()` and
  `write_handle()` closed their output file only on the success path, so an
  exception mid-write left the file open. On Windows this prevented the file
  from being deleted. Both now use `try/finally`. This is a latent upstream
  bug and is a candidate for an upstream contribution.


Tracking conventions
--------------------

* Each feature gets one bullet. Say what the user can now do, not which
  function changed.
* Add the bullet when the feature is merged, not while it is in progress.
* If a feature is reverted from this branch, delete its bullet.
* Commit messages on this branch must still follow the AGENTS.md format,
  because the CommitLog generation scripts parse them.

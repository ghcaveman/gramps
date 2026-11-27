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
  * An image preview beside each row shows the file the row would use, with
    the region of each person or event attached to it outlined, so a match
    or merge can be checked before it is accepted.
  * MD5 checksums are filled in automatically after each step, as Media
    Verify does. Find missing media uses them to recognise a file that has
    been renamed or moved, and the report lists files whose content has
    changed and offers to update their checksums.
  * Media whose description names someone who is not attached to it (for
    example "Murrow" against "Morrow") are listed, marked as a probable
    spelling variant or a different person, and the description can be
    corrected to the attached person's name. Alternate names count as a
    match.
  * The base media path can be set from Find missing media with a folder
    button. Records whose files already resolve keep pointing at them when
    the path changes, and **Accept all hints** explains what it skipped if
    no base media path is set.

* **GWizard Citation Fix tool.** A set of review steps for cleaning up
  repositories, sources, citations and citation notes: unpacking source and
  citation text that has several fields run together, consolidating and
  linking repositories, merging near-duplicate sources, tidying citation
  pages, dates and confidence, adding citation quality attributes, and
  linking media to citations. It can also write a citation analysis report,
  and **Accept all hints** runs every step without stopping to review.
  Sources with no repository or no citations are flagged for review by
  linking them to a Quarantine repository, and a repository that becomes a
  duplicate of a gold-standard one (such as "The National Archives and
  Records Administration (NARA)") is merged into it. See
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
  the tree, closest first. Media paths in the incoming file are read
  relative to where that file came from and recorded relative to the
  family tree's base media path, and a picture already in the tree under
  another path or name is recognised by its MD5 checksum, so it is not
  added twice. See `featuredocs/README_gwizard_filemerge.md`.

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
  * **Getting a key.** NARA issues keys free of charge by email. Send your
    name and the email address the key should be tied to to
    `Catalog_API@nara.gov` and ask for a read-only Catalog API v2 key
    (read-only is all this tool needs). Each key is limited to 10,000
    requests a month. Keep the key private: do not commit it to a
    repository, and if it is ever published, email the same address to
    have it replaced.
  * **Setting the key.** Gramps reads `NARA_API_KEY` from its environment
    when it starts, so set the variable and then restart Gramps.
    * Windows: run `setx NARA_API_KEY "your-key"` in a Command Prompt, or
      add it as a user variable under *System Properties > Environment
      Variables*. Programs started afterwards (including Gramps from the
      Start menu) see it. For one session from an MSYS2 or Git Bash shell,
      `export NARA_API_KEY="your-key"` and start Gramps from that shell.
    * Linux: add `export NARA_API_KEY="your-key"` to `~/.profile` (or your
      shell's start-up file) and log in again, or export it in a terminal
      and start Gramps from there.
    * macOS: export it in `~/.zprofile` for Gramps started from a terminal.
      For Gramps started from the Dock or Finder, run
      `launchctl setenv NARA_API_KEY "your-key"` (repeat after each
      restart of the Mac).
  * **Checking the key.** When the tool opens it makes one small catalog
    request to test the key. If the variable is missing it asks you to set
    it and restart Gramps; if NARA rejects the key it says so. The
    Multi-Archive Record Scan skips NARA while no key is set.

* **GWizard FamilySearch Merge tool.** Search the FamilySearch Family
  Tree for a person, by first, middle and last name, gender, birth and
  death year and place, or FamilySearch ID or profile URL, with a check box
  beside each search term to leave it out without clearing it. Results are
  listed best match first, and a profile looked up by its ID, or the one
  the person is already linked to, counts as a 100% match. **Compare /
  Merge...** loads the profile, with spouses, notes and sources, into the
  File Merge compare and merge window. Merged data is cited to a shared
  FamilySearch repository and "FamilySearch Family Tree" source, with one
  dated citation per profile, and the person keeps the FamilySearch ID
  (`_FSFTID` attribute) and a link to the profile; merging the same profile
  again adds nothing twice. Searching needs a FamilySearch sign-in: in the
  Family Trees menu choose *FamilySearch Sign in...*. It installs as an
  addon that depends on GWizard File Merge and GWizard Media Fix.

* **Multi-Archive Record Scan.** Lists every person in the Family Tree
  with a group of columns for each installed GWizard record source
  (WikiTree, NARA, FamilySearch, ...), and searches those sources for
  each person. Its menu entry appears once at least one record-source
  addon is installed. Record sources register themselves, so new archives
  can be added without changing the scan.
  * **Scanning.** A **Scan** button per source and **Scan All** search
    every person in scope, with a progress meter that can be cancelled.
    *People* chooses the scope: everyone, the active person only, or a
    person filter (the list always shows everyone). A source that cannot
    be used, such as NARA without an API key, has its button greyed out
    with the reason in its tooltip, and NARA shows how many of its monthly
    requests have been used.
  * **Match columns.** By default each source counts its likely matches at
    three match levels (given/middle/surname/birth, given/surname/birth,
    and given/surname); a record counts when it scores at least the *Match
    threshold* (70% unless changed), and changing the threshold rescores
    without searching again. A source can show its own columns instead:
    NARA shows a single Match column and sends one query per person. A
    *Linked* column shows the record a person is already linked to (for
    example their WikiTree or FamilySearch ID), which is looked up rather
    than searched, and a *Cited* column shows the records the person
    already cites (NARA NAIDs), which count as already found. Hovering
    over a cell shows its best matches, or why that level cannot be
    compared (no birth year, no middle name, ...).
  * **Check boxes.** *Reuse saved results* (on by default) skips people
    already scanned and unchanged since, so a scan does not spend requests
    again; uncheck it to search everyone again. Results are kept between
    sessions in the Gramps user folder, one file per Family Tree, and can
    be forgotten for one person and source from the right-click menu.
    *Show only people with matches* hides everyone else. *Show:* has one
    check box per record source, all on; unchecking one hides its columns
    and leaves it out of **Scan All**, the match filter, the summary, the
    merge choices and the CSV export, while keeping its saved results.
  * **Acting on a match.** Double-click a source's cell, or use **Open
    Merge...**, to open that source's merge window for the person; the
    right-click menu lists the matches to choose from. **Open Search...**
    opens the source's own search window for the person, and **Export
    CSV...** saves the list with its scores.

* **Multi-Archive Citation Scan.** The Multi-Archive Record Scan seen
  from the citations' side. Every citation in the Family Tree is checked
  for missing or poor data (no page, no date, no image or a missing image
  file, a page that is cut off or just repeats the source, a source title
  that is a web address or file name, a source with no repository or
  author, low confidence, ...), and the problems add up to a *Work* score
  from 0 to 100. Citations are listed worst first with the person they
  are about, the source, page, date, confidence, images and what each
  needs. Its menu entry appears once at least one record-source addon is
  installed, and record sources can add their own citation checks.
  * **Finding better records.** The **Scan** buttons and **Scan All**
    search the installed record sources for the people the worst
    citations are about, and each source's *Confidence* column shows how
    well the best record found fits the citation: the person's match
    score, moved up or down by how well the record's title and years fit
    the citation. A record the citation already cites is shown as
    *cited*. Searches share saved results with the Multi-Archive Record
    Scan, so a person searched in either window costs no second request.
  * **Options.** *Work at least* (20 unless changed) sets which citations
    count, and *Hide the rest* hides the others. *Confidence threshold*
    sets which records are offered. *Citations* chooses all citations or
    the active person's, and *Only with records found* hides citations
    with no record. *New people per scan* (25 unless changed, 0 for no
    limit) caps how many unsearched people one scan click searches, so it
    does not use up a monthly request allowance such as NARA's; people
    with saved results are always included. *Reuse saved results* and the
    per-source *Show:* check boxes work as in the Multi-Archive Record
    Scan.
  * **Acting on a citation.** **Edit Citation...** opens the citation
    editor, **Open Record...** opens a found record in that source's
    merge window or a cited record directly, **Open Search...** opens a
    source's search window for the citation's person, the right-click
    menu offers the same, and **Export CSV...** saves the list.

* **GWizard tools in a fixed menu order.** Under Tools > Family Tree
  Processing the GWizard tools are listed together, in the order they are
  meant to be used: GWizard File Merge, GWizard File Merge (Alt), GWizard
  Media Fix, GWizard Citation Fix, GWizard WikiTree Merge, GWizard NARA
  Merge, GWizard FamilySearch Merge, then Multi-Archive Record Scan.

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

* **Windows installer and programs are branded GoatGramps.** For SignPath
  code signing, the installer and the `.exe` files report GoatGramps as the
  product name and publisher, with a four-part version of
  `6.1.0.<GOATGRAMPS_RELEASE>`, and the About box shows `AIO64-6.1.0+gg.N`.
  The install folder, registry keys and uninstall entry deliberately stay
  the same as Gramps, because the two cannot be installed side by side.
  Files: `aio/grampsaio64.nsi.template`, `aio/setup.py`, `aio/build.sh`.

* **SignPath code signing policy.** `CODE_SIGNING_POLICY.md`, a GoatGramps
  section at the top of `README.md`, and release notes from
  `deploy-releases.yml` that describe GoatGramps and link to the policy.

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

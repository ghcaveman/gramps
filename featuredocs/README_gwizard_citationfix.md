## Overview

The **GWizard citation fix** tool helps genealogists clean up and standardise citation data across the entire Family Tree. It analyses sources, repositories, citations, citations' notes, and attached media, then presents hints you can review before applying: unpack mixed source and citation titles, create missing repositories, consolidate duplicate repositories, fix source links, clean citation details, assign Genealogical Proof Standard (GPS) attributes, link documentary media to citations, and clean up citation notes. Every step runs inside a single transaction, so it can be reversed with **Edit > Undo**. The tool can also generate a citation analysis report (`CitationFixReport.txt`) and display it in a report window.

## Usage

1. Open Gramps, load your Family Tree, then open **Tools > Family Tree Processing > GWizard citation fix**.
   The "GWizard citation fix" dialog opens.
2. Click one of the buttons below to run a step. Most steps open a review dialog listing hints you can inspect and correct before applying them.
3. Applied changes are grouped in one transaction per step: choose **Edit > Undo** to reverse the most recent step.
4. When you are finished, click **Close** to leave the dialog.

Buttons in screen order:

- **Generate report** — writes a citation analysis report to a text file you choose.
- **Unpack Conflated Source** — separates mixed source titles and extracts repository details.
- **Repository Consolidate** — merges duplicate repositories against gold-standard names.
- **Fix Repositories** — links orphan sources to repositories and creates missing ones.
- **Fix Sources** — merges near-duplicate sources and quarantines non-sources.
- **Unpack Conflated Citation** — extracts dates and URLs from volume/page fields and notes.
- **Fix Citations** — cleans page, date, and confidence values on citations.
- **Citation Attributes** — assigns GPS quality attributes and confidence ratings.
- **Link Citation Media** — links documentary media from galleries and sources to citations.
- **Fix Notes** — removes import debris and bare-URL notes.
- **Accept all hints** — runs all nine steps automatically, one transaction per step.

### Generate report

1. Click **Generate report**. The "Save Citation Fix Report" file chooser opens.
   ![Save the citation analysis report as a text file](images/gwizard_citationfix-generate-report-save.png)
2. Choose the folder and file name (the default is `CitationFixReport.txt`), then click **Save**.
3. The report is written. A "Report Generated" message confirms the location, and the "GWizard citation fix report" window opens automatically showing the report text.
   ![Citation analysis report window](images/gwizard_citationfix-generate-report.png)
4. Click **Close** to leave the report window and return to the main dialog.

### Unpack Conflated Source

1. Click **Unpack Conflated Source**. The "Unpack Conflated Source" review dialog opens.
   ![Review hints that unpack mixed source titles](images/gwizard_citationfix-unpack-conflated-source.png)
2. Review each hint row and correct any values that need editing.
3. Click **Apply** to apply the accepted hints as one transaction, or **Close** to return to the main dialog without changes. A message confirms what was applied, or that there was nothing to apply.

### Repository Consolidate

1. Click **Repository Consolidate**. The "Repository Consolidate" review dialog opens.
   ![Review duplicate repositories to consolidate](images/gwizard_citationfix-repository-consolidate.png)
2. For each problem repository, pick the target repository from the combo boxes.
3. Click **Apply** to merge the chosen repositories as one transaction, or **Close** to return to the main dialog without changes.

### Fix Repositories

1. Click **Fix Repositories**. The "Fix Repositories" review dialog opens.
   ![Review repository links for sources](images/gwizard_citationfix-fix-repositories.png)
2. Review each suggested repository link and correct anything that needs editing.
3. Click **Apply** to apply the accepted links as one transaction, or **Close** to return to the main dialog without changes.

### Fix Sources

1. Click **Fix Sources**. The "Fix Sources" review dialog opens.
   ![Review near-duplicate sources to merge](images/gwizard_citationfix-fix-sources.png)
2. Review each merge hint and confirm or correct the pairs.
3. Click **Apply** to merge the accepted near-duplicate sources as one transaction, or **Close** to return to the main dialog without changes.

### Unpack Conflated Citation

1. Click **Unpack Conflated Citation**. The "Unpack Conflated Citation" review dialog opens.
   ![Review citation text to unpack dates and URLs](images/gwizard_citationfix-unpack-conflated-citation.png)
2. Review each hint row showing dates and URLs extracted from volume/page fields or notes.
3. Click **Apply** to unpack the accepted citations as one transaction, or **Close** to return to the main dialog without changes.

### Fix Citations

1. Click **Fix Citations**. The "Fix Citations" review dialog opens.
   ![Review citation page, date, and confidence fixes](images/gwizard_citationfix-fix-citations.png)
2. Review each suggested fix for page, date, and confidence values.
3. Click **Apply** to apply the accepted fixes as one transaction, or **Close** to return to the main dialog without changes.

### Citation Attributes

1. Click **Citation Attributes**. The "Citation Attributes" review dialog opens.
   ![Review GPS attribute assignments for citations](images/gwizard_citationfix-citation-attributes.png)
2. Review the suggested Genealogical Proof Standard attributes: source type, information type, evidence type, and QUAY confidence.
3. Click **Apply** to assign the accepted attributes as one transaction, or **Close** to return to the main dialog without changes.

### Link Citation Media

1. Click **Link Citation Media**. The "Link Citation Media" dialog opens.
   ![Review media-to-citation link proposals in the Link Inspector](images/gwizard_citationfix-link-citation-media.png)
2. Review each row in the grid; click **Inspect** to show a row in the Link Inspector pane with its thumbnail and compatibility score.
3. Confirm the links you want, then click **Apply** to link the accepted media to citations as one transaction, or **Close** to return to the main dialog without changes.

### Fix Notes

1. Click **Fix Notes**. The "Fix Notes" review dialog opens.
   ![Review citation notes to clean](images/gwizard_citationfix-fix-notes.png)
2. Review each note flagged as import debris or as a bare web address.
3. Click **Apply** to remove the accepted notes as one transaction, or **Close** to return to the main dialog without changes.

### Accept all hints

1. Click **Accept all hints**. The "Accept all hints" confirmation dialog opens and lists the nine steps that will run automatically.
   ![Confirm running all nine citation fix steps](images/gwizard_citationfix-accept-all-hints.png)
2. Click **Accept all** to run every step in order: unpack sources, consolidate repositories, fix repositories, fix sources, unpack citations, fix citations, citation attributes, link citation media, and fix notes. Each step runs as one transaction.
3. When all steps finish, the "Accept All Hints Complete" window opens showing what changed and listing anything that still needs human review.
   ![Accept All Hints results window](images/gwizard_citationfix-accept-all-hints-complete.png)
4. Click **Close** to return to the main dialog. Use **Edit > Undo** to reverse any step, one at a time.

## Configure Options

- No tool-level configuration. `GWizardCitationFixOptions` defines no checkboxes, fields, or other settings; all behaviour is driven by the buttons on the main window.
- Each step dialog carries its own controls — typically **Apply** to apply the accepted hints as one transaction, and **Close** to return to the main dialog.

## Features

- Analyses the whole Family Tree: sources, repositories, citations, citations' notes, and attached media.
- Nine review steps: Unpack Conflated Source, Repository Consolidate, Fix Repositories, Fix Sources, Unpack Conflated Citation, Fix Citations, Citation Attributes, Link Citation Media, and Fix Notes.
- Generates a citation analysis report saved to `CitationFixReport.txt` (or a file name and location you choose) and shows it in the "GWizard citation fix report" window.
- Review before you apply: every step shows a hint grid you can edit, then applies accepted hints as a single transaction reversible with **Edit > Undo** (one undo per step, up to nine steps).
- **Accept all hints** runs all nine steps automatically and reports the changes made plus any items still needing human intervention.
- **Link Citation Media** scores media/citation pairs (document category compatibility, chronological year matching) and shows thumbnails and scores in the Link Inspector pane, then links accepted scans to citations, detaching them from Person or Event galleries where needed.
- **Citation Attributes** assigns Genealogical Proof Standard quality attributes and QUAY confidence ratings to citations.

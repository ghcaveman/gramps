# Repository, Source, Citation, and URL Policy in Gramps & GWizard

**Author:** Devin (AI Engineering Assistant)  
**Date:** November 12, 2026  
**Context:** Feature Branch `gwizard_citationfix` (parent: `gwizard_mediafix`)  
**References:**
- Gramps Discourse Topic #10191: *Citation Question* (https://gramps.discourse.group/t/citation-question/10191/5)
- `GeminiRepositorySourcesCitationDescription.txt`
- `HandlingSourceCitationsWithUrls_GoogleAI.txt`
- `CitationAttributes_GoogleAi.md`
- `MediaArrangementInAGedcomFile.md`

---

## 1. Overview of the Problem

When genealogists import or manually create source citations from online platforms (such as FamilySearch or Ancestry) referring to archival collections (such as the U.S. Federal Census), two recurring architectural disputes arise:

1. **Hierarchy Division:** What is the *Repository*, what is the *Source*, and what is the *Citation*? Specifically, where does "FamilySearch" go versus where does the "U.S. Census" go?
2. **URL Placement:** Where should the record permalink / URL (e.g., an ARK identifier or web address) be placed in Gramps so that it is genealogically sound, cleanly presented, and survives GEDCOM round-trip export without data loss?

---

## 2. Structural Hierarchy: FamilySearch vs. U.S. Census

### A. The Competing Views

1. **The Archival Purist View (e.g., Philip Wharram on Discourse):**
   - **Repository:** National Archives and Records Administration (NARA).
   - **Source:** 1930 United States Federal Census.
   - **FamilySearch / Ancestry:** Viewed strictly as a publisher or commercial distributor, not a repository.
   - *Limitation:* Does not reflect the modern reality of digital research. Researchers consult digitized scans, indexes, and transcriptions created or hosted by online platforms, which may include transcription errors, image variations, or digital artifacts not present on physical microfilm.

2. **The Modern Practical / Evidence Explained Consensus (e.g., Dave Scheipers on Discourse, Elizabeth Shown Mills):**
   - In modern evidence analysis, a researcher cites **where the record was actually examined**.
   - **Repository:** The digital or physical repository where the researcher accessed the record (**FamilySearch** or **Ancestry.com**).
   - **Source:** The overarching collection title (**1930 United States Federal Census**).
   - **Source Publication Info:** Cites the original government or archival publisher (*Washington, D.C.: National Archives and Records Administration (NARA), microfilm publication T626*).
   - **Citation:** Pinpoints the exact person, sheet, line, and enumeration district within that census.

### B. Standard Mapping in Gramps

| Gramps Object | Field | Value / Content | Notes |
| :--- | :--- | :--- | :--- |
| **Repository** | Name | `FamilySearch` (or `Ancestry.com`) | Golden repository name |
| | Type | `Web site` | Built-in Gramps Repository Type |
| | Internet | `https://www.familysearch.org` | Primary repository URL |
| **Source** | Title | `United States Census, 1930` | Master collection / record set |
| | Author | `United States Bureau of the Census` (or NARA) | Creator of the work |
| | Pub Info | `Washington, D.C.: National Archives and Records Administration (NARA), microfilm publication T626` | Original archival publication details |
| | Repository Ref | Link to `FamilySearch` | Associated repository |
| **Citation** | Vol/Page | `Illinois, Cook County, Chicago, Ward 12, ED 16-432, Sheet 4B, household 92, line 14, John Smith` | Specific archival coordinates (largest to smallest) |
| | Date | Census enumeration date (e.g., `15 Apr 1930`) | Date of record |
| | Confidence | `Very High` (3) / `High` (2) | Reliability assessment |
| **Media Object** | Path / File | Scan file path or image URL (`1 FILE ...`) | Attached to the Citation Gallery tab or Census Event |

---

## 3. Where Does the URL Go?

### A. The GEDCOM Standard Constraint

- **GEDCOM 5.5 / 5.5.1 / 5.5.5:** There is **no native `WWW` or URL tag** under a Source Citation (`SOUR`). The `WWW` tag is only officially permitted under `REPO` (Repository), `SUBM` (Submitter), and `EVEN` (Event).
- **GEDCOM 7.0:** Added official support for `WWW` under citations (`3 WWW https://...`), but standard desktop genealogy software (including Gramps core) defaults to GEDCOM 5.5.1 export.
- **Critical Gramps Quirk:** Gramps' GEDCOM 5.5.1 exporter **drops Citation Attributes completely**. Any URL stored in a custom Citation Attribute (`SrcAttribute`) is stripped on export.

### B. Evaluation of the Four Storage Options

1. **Option 1: Citation Note (Recommended for Archival Purity & GEDCOM Compatibility)**
   - **Storage:** Create an attached Note of type `Citation` or `Source text` containing the URL.
   - **GEDCOM Export:** Exports cleanly to standard `3 NOTE https://...`.
   - **Pros:** Keeps the `Volume/Page` field clean of ephemeral web links; 100% data preservation across all GEDCOM tools; fully searchable.
   - **Cons:** In some printed/book reports, notes appear separately from inline citation text.

2. **Option 2: Appended to Citation `Volume/Page` (Recommended for Web Trees & WikiTree)**
   - **Storage:** `Sheet 4B, line 14, https://www.familysearch.org/ark:/61903/1:1:...`
   - **GEDCOM Export:** Exports directly to `3 PAGE ...`.
   - **Pros:** Survived 100% across all import/export systems; web platforms like WikiTree and webtrees parse URLs inside `PAGE` into clickable links.
   - **Cons:** Pollutes the archival citation text; susceptible to link rot.

3. **Option 3: Citation Attribute (Not Recommended for GEDCOM Round-Trips)**
   - **Storage:** Key `URL`, Value `https://...`.
   - **GEDCOM Export:** **LOST ON EXPORT** in Gramps 5.5.1.
   - **Pros:** Clean, structured key-value pair for internal Gramps scripts.
   - **Cons:** Total data loss when exporting to standard GEDCOM files.

4. **Option 4: Attached Media Object (Best for Actual Image Scans)**
   - **Storage:** Media Object attached to the Citation's Gallery tab.
   - **GEDCOM Export:** Exports as `2 OBJE @M1@` pointing to `0 @M1@ OBJE` with `1 FILE ...`.
   - **Pros:** Directly ties the visual proof to the citation.
   - **Cons:** Requires a media record per image.

---

## 4. Architectural Rules for `gwizard_citationfix`

To ensure consistency across GWizard dialogs (`gw_unpacksourcesdialog`, `gw_unpackcitationsdialog`, `gw_citationsfixdialog`, and `gw_repoconsolidatedialog`):

1. **Source & Repository Separation:**
   - Source titles containing repository names or web domains (e.g., `"Ancestry.com; 1900 US Census; Roll 123"`) must be unpacked:
     - **Repository:** Extracted to the golden repository (`Ancestry.com` or `FamilySearch`).
     - **Source Title:** Cleaned to the collection title (`1900 US Census`).
     - **Citation Page / Note:** Receives specific roll/page fragments.
2. **URL Handling Policy:**
   - **When Volume/Page contains both archival coordinates and a URL:** Unpack the citation by keeping the archival reference (e.g., `Sheet 4B, line 14`) in `Volume/Page` and moving the URL into a **Citation Note**.
   - **When Volume/Page is blank and only a bare URL exists:** Allowing the bare URL in `Volume/Page` (or in a Citation Note) ensures the user retains access to the record until archival coordinates are entered.
   - **Never store URLs exclusively in Citation Attributes** due to GEDCOM export loss.

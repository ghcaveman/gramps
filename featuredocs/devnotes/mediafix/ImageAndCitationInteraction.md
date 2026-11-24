# Image and Citation Interaction & Development Plan

This document outlines:
1. Heuristics and UX patterns to prevent or investigate attaching images to the wrong source/citation.
2. A comprehensive, phased development plan to integrate media linking and validation into `gwizard_citationfix` building on top of `gwizard_mediafix`.

---

## Part 1: Preventing and Investigating Attaching Images to the Wrong Source

When linking media files to sources or citations, users and automated tools risk attaching an image to the wrong record (e.g., attaching a 1940 census image to an 1880 census citation, or attaching a death certificate to a marriage source).

Because `gwizard_mediafix` standardizes filenames (e.g., `{ref_id}_{surname}_{given}_{doc_type}_{year}`) and inspects media metadata, structured data is available to compare against the target Citation and Source.

### 1. Discordance Heuristics (Automated Mismatch Detection)
A **Compatibility Scoring Heuristic** evaluates pairs of Media objects and Citations/Sources:

* **Chronological Discrepancy (Year/Date Mismatch):**
  * *Signal:* The media filename, description, or image date indicates a year (e.g., `1940_Census_...jpg` or date `1940`), but the Citation’s date, Source title, or associated Event date is substantially different (e.g., `1910 Census` or `Birth 1872`).
  * *Threshold:* Any date difference > 1 year for specific events (e.g., Census, Birth, Death) triggers a warning flag.
* **Document Type vs. Source Category Incompatibility:**
  * *Signal:* Contrast the image's detected `doc_type` against the Source title or Citation page:
    * Image: `Marriage_Certificate`, Source: `U.S. Federal Census` ➔ **Severe Conflict**.
    * Image: `Tombstone / Headstone`, Source: `Birth Index` ➔ **Severe Conflict**.
    * Image: `Military_Draft_Card`, Source: `Parish Baptismal Register` ➔ **Severe Conflict**.
  * *Action:* Keyword classification dictionary (e.g., census, birth, death, marriage, military, probate, land/deed, directory).
* **Surname & Family Cluster Mismatch:**
  * *Signal:* The media filename or description mentions a specific surname (e.g., `Johnson_1920.jpg`), but the Citation is attached to a Person or Family with surname `Kowalski`, with no maternal or spousal relation.
* **Volume / Page / Sheet Discordance:**
  * *Signal:* The Citation specifies `Sheet 14B, ED 22-10`, while the media file or description reads `Sheet 02A, ED 22-04`.
* **Cross-Source Multi-Use Detection (Document vs. Portrait):**
  * While portraits can be linked across multiple life events or personal galleries, **documentary evidence is exclusive to specific events**:
    * If a media object classified as a document/certificate is linked to two completely unrelated Sources or non-contemporary Events (e.g., a Source in 1860 in Virginia and a Source in 1920 in California), flag it immediately as a suspect shared reference.

### 2. Investigative UX Patterns (Guiding the User)
Instead of silent automatic linking, provide clear investigative tools:

* **Traffic-Light Confidence Indicator in the UI:**
  * 🟢 **High Confidence (Safe to Auto-Link):** Year, surname, document type, and event match cleanly.
  * 🟡 **Ambiguous (Requires Inspection):** Partial match (e.g., surname matches, but multiple citations exist for that year; or year matches, but no surname is in the filename).
  * 🔴 **Suspect Link (Needs Review):** High discrepancy score between the current/suggested media and the Citation/Source.
* **Side-by-Side Review & Thumbnail Inspection:**
  * In the preview table, selecting a row displays a small GTK preview thumbnail of the image on the right, alongside the Citation details (`Source`, `Page`, `Date`, `Associated People/Events`) and the image details (`Filename`, `MIME`, `Description`, `Detected Year/Type`).
  * Prompts the user: *"Are you sure? Image year (1930) differs from Source year (1920)."*
* **"Suspect Media Links" Audit in Citation Report:**
  * Expand `gwizardcitationreport.py` to add a new section: **"Auditing Existing Media-Source Attachments"**:
    * Lists any media objects currently attached to Citations or Sources where the heuristic detects a conflict.

---

## Part 2: Phased Development Plan

```
Phase 1: Tagging & Locking in gwizard_mediafix
   │
   ▼
Phase 2: Compatibility Engine & Mismatch Detection Core
   │
   ▼
Phase 3: "Link Citation Media" Dialog in gwizard_citationfix
   │
   ▼
Phase 4: Report Expansion & "Accept All Hints" Pipeline
   │
   ▼
Phase 5: Unit Tests, Formatting, and User Documentation
```

### Phase 1: Tagging and Locking in `gwizard_mediafix` (The Anchor)
* **Objective:** Give media objects a persistent mark indicating they have been verified/consolidated by `gwizard_mediafix`, and optionally allow a user lock.
* **Tasks:**
  1. Define standard Gramps tags:
     - `Tag("GWizard: MediaFixed", color="#2E8B57")` (SeaGreen)
     - `Tag("GWizard: Locked", color="#B22222")` (Firebrick)
  2. In `gwizardmediafix.py`, after a media record is repaired or consolidated:
     - Add the `GWizard: MediaFixed` tag to the `Media` object.
  3. Ensure that when any tool (or future run) encounters a media object tagged `GWizard: Locked`, it skips modifying its path, description, or reference links.

### Phase 2: Media-Citation Analysis & Repair Engine
* **Objective:** Create the analysis engine to evaluate media-to-citation relationships and detect conflicts.
* **Tasks:**
  1. Add a shared utility/service (e.g., in `gwizardcitationrepairengine.py` or `gw_citation_media_engine.py`):
     - `extract_media_identity(media)`: Extracts tokens (doc_type, year, surname, given, sheet/page) from media path, description, and date.
     - `extract_citation_identity(db, citation)`: Extracts tokens from Citation page, Source title, Source type, and attached Event/Person.
     - `compute_citation_media_compatibility(media_id, citation_id) -> tuple[int, list[str]]`: Computes a match score (0-100) and returns a list of matching or conflicting reasons (e.g., `["Year match: 1940", "Type conflict: Census vs Tombstone"]`).
  2. Implement scanner routines:
     - **Promote from Person/Event:** Finds media attached to Person/Event galleries that are documentary evidence and match an existing Citation on that Person/Event.
     - **Unpack from Source:** Finds media attached to Sources with multiple citations, matching specific pages.
     - **Link Orphan Media:** Finds unlinked media whose filename tokens match citations with no current media references.
     - **Audit Existing Links:** Detects citations currently referencing media where compatibility is below acceptable thresholds.

### Phase 3: "Link Citation Media" UI Dialog in `gwizard_citationfix`
* **Objective:** Add the interactive user interface to review, investigate, and apply media linkages.
* **Tasks:**
  1. Add the **`Link Citation Media`** button in `gwizardcitationfix.py` between `Citation Attributes` and `Fix Notes`.
  2. Create `GWLinkCitationMediaDialog` (extending the preview pattern used in `RepoConsolidateDialog` and `ConsolidateMediaLocationDialog`):
     - TreeView columns:
       - Status / Icon (🟢 / 🟡 / 🔴)
       - Citation (Source Title + Page/Volume)
       - Candidate Media (Filename / Description)
       - Proposed Action (`Promote from Person`, `Unpack from Source`, `Link Unlinked`, `Resolve Mismatch`)
       - Conflict / Match Details
     - Side/Bottom Preview Pane:
       - Thumbnail of selected image.
       - Detailed comparison of Source metadata vs. Image metadata.
     - Action buttons:
       - `Apply Selected`
       - `Select All Safe (🟢)`
       - `Ignore`

### Phase 4: Integration into Citation Report & "Accept All Hints"
* **Objective:** Make media relationship issues visible in reports and safely automated.
* **Tasks:**
  1. In `gwizardcitationreport.py`:
     - Add stats for:
       - Citations with / without media
       - Documents residing in Person galleries that belong on Citations
       - Suspect attachments (potential mismatches between Media and Source)
  2. In `cb_auto_all` ("Accept all hints"):
     - Include the `Link Citation Media` step with safe thresholding:
       - Only auto-apply matches with **High Confidence (🟢, score >= 90)** and zero conflicting keywords.
       - Flag any ambiguous or suspect matches for manual review.

### Phase 5: Verification, Tests & Documentation
* **Objective:** Ensure robustness, zero regressions, and clear documentation.
* **Tasks:**
  1. **Unit Tests:**
     - Create `gw_citation_media_test.py` covering:
       - Compatibility scoring (matching and mismatch detection).
       - Person gallery promotion to citation.
       - Source-level media unpacking.
       - Respecting the `GWizard: Locked` tag.
  2. **Type Checking & Linting:**
     - Run `mypy` and `black .` according to project rules.
  3. **Documentation:**
     - Update `featuredocs/README_gwizard_citationfix.md` and `.mediawiki` documentation detailing the new button, the heuristic checks, and the thumbnail verification workflow.

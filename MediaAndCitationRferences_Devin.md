# Media and Citation Relationships & Architecture in Gramps and GEDCOM

## 1. Relationships of Repositories, Sources, Citations, Notes, and Media

In both the **GEDCOM standard** (see `MediaArrangementInAGedcomFile.md`) and the **Gramps object model**, genealogical evidence follows a strict hierarchy:

```
Repository (Archive / Library / Website)
    │
    ▼ holds
Source (Master Collection / Publication / Roll)
    │
    ▼ cited by
Citation (Specific Entry: Page, Sheet, Household, Line)
    │
    ├──▶ Media Objects (Scans, Documents, Photos, Certificates)
    └──▶ Notes (Transcriptions, Research Notes, Import Debris)
```

### Object Characteristics in Gramps Core (`gramps/gen/lib/`):

| Object Type | In Gramps Core (`gen/lib/`) | Can Have Media? (`MediaBase`) | Can Have Notes? (`NoteBase`) | Role & Standard Practice |
| :--- | :--- | :---: | :---: | :--- |
| **Repository** | `PrimaryObject` | **No** | **Yes** | Holds physical/digital custody metadata (addresses, URLs, notes). Does not take direct media attachments. |
| **Source** | `PrimaryObject` | **Yes** | **Yes** | Overarching collection (e.g., *1940 US Federal Census*). Media attached here should only be macro-level items (e.g., book title page, finding aid), **not** individual person/family record scans. |
| **Citation** | `PrimaryObject` | **Yes** | **Yes** | Specific page/line evidence (e.g., *ED 16-100, Sheet 12A*). **This is the primary home for documentary evidence scans.** |
| **Media (`OBJE`)** | `PrimaryObject` | Self | **Yes** | File record on disk with checksum, MIME type, description, date, attributes, and tags. Citations can also attach back to media. |
| **Note** | `BasicPrimaryObject`| **No** | Self | Text transcriptions, citations notes, or import commentary. Cannot attach media. |

---

## 2. Comparing Individuals, Families, and Events with Citations for Media

In Gramps, `Person`, `Family`, and `Event` all inherit from `MediaBase` (each has a `media_list` / Gallery). However, attaching document images directly to them vs. to Citations has major consequences:

### 1. Individual (`INDI`) Gallery
- **Intended Use:** Personal portraits and biographical photos.
- **The Problem:** Many users and GEDCOM importers dump document images (e.g., a census scan or death certificate) directly into the Person's gallery. If a census page lists 8 household members, this either attaches the media 8 separate times to 8 individuals or clutters each person's portrait gallery with document scans.

### 2. Family (`FAM`) Gallery
- **Intended Use:** Couple/family portraits.
- **The Problem:** Often used as a shortcut for marriage certificates, bypassing the `Marriage` event or the Citation entirely.

### 3. Event (`EVEN`) Gallery
- **Intended Use:** Photos of the event itself (e.g., a photo of a tombstone on a `Burial` event, or a church photo on a `Baptism` event).
- **Limitations:** While attaching a certificate to an event is better than attaching it to a person, an event is an occurrence. If multiple people share facts supported by the same document, placing the media on the event still misses facts like name variants, ages, or residences derived from the same document.

### 4. Citation (`SOUR` + `PAGE`) — The Recommended Architecture
- **Why Citation-Level Media is Best:**
  - A document image (e.g., `1940_Census_ED16-100_Sheet12A.jpg`) is the direct **evidence** for a citation.
  - By attaching the media to the **Citation**, any Person, Family, or Event that cites that record automatically references the underlying image without duplicating the media object or cluttering personal portrait galleries.
  - It allows 10 family members to share 1 Census Citation which holds 1 Media reference to 1 clean file on disk.

---

## 3. Populating and Fixing Images Post-`gwizard_mediafix`

Now that `gwizard_mediafix` has resolved missing files, consolidated folder paths, deduplicated file pointers, and applied standardized names (e.g., `{ref_id}_{surname}_{doc_type}_{year}`):

### Key Issues Found in Typical Databases:
1. **Document scans trapped in Person/Family galleries** instead of attached to Citations.
2. **Citations lacking Media** even though matching media records exist in the database.
3. **Media attached at the Source level** (e.g., 50 census sheets attached to a single Source record instead of their corresponding Citations).
4. **Orphan Media** floating without links to citations or events.

### Recommended Strategy to Populate / Fix:
A multi-stage promotion/linking engine:

1. **Promote Media from Person/Event to Citation:**
   - When a Person or Event has a Citation (e.g., to a "1930 Census" source) AND that same Person or Event has a Media object in their gallery with a matching description or filename keywords (e.g., contains "Census", "1930", or matches surname/date):
     - Offer to **attach the Media to the Citation**.
     - Offer an option to **remove the document from the Person's portrait gallery** (leaving portrait photos intact).
2. **Unpack Media Attached to Master Sources:**
   - For Sources that have multiple Media attachments, match each media item's title/page with the Citations under that Source, moving or copying the media link down to the specific Citation.
3. **Match Orphan / Unlinked Media to Citations:**
   - Use the standardized filenames created by `gwizard_mediafix` (which often have `{surname}_{doc_type}_{year}`) to suggest matches for Citations that have matching Page/Date/Source fields and currently have zero media references (`len(cit.get_media_list()) == 0`).

---

## 4. Proposed Button Placement in `gwizard_citationfix`

Adding a button to the `gwizard_citationfix` dialog fits logically into the data-cleaning flow:

```
[ Generate report ]
[ Unpack Conflated Source ]
[ Repository Consolidate ]
[ Fix Repositories ]
[ Fix Sources ]
[ Unpack Conflated Citation ]
[ Fix Citations ]
[ Citation Attributes ]
▶ [ Link Citation Media ]   <-- PROPOSED BUTTON
[ Fix Notes ]
[ Accept all hints ]
```

### Why This Exact Position?
- **Prerequisite Cleanliness:** Matching media to citations works best *after* Sources and Citations have been unpacked, deduplicated, and given standard volume/page fields.
- **Before Notes:** Notes often hold transcription text or import debris related to media; cleaning up media links first makes subsequent note cleanup more accurate.
- **Preview Table Pattern:** Following the existing wizard architecture, clicking this button opens a review dialog showing:
  `Citation (Source + Page) | Candidate Media (Path/Title) | Match Source (Person Gallery / Source / Match Heuristic) | Proposed Action [Link / Move / Ignore]`

---

## 5. Locking or Flagging Fixed Images in `gwizard_mediafix`

Gramps provides native mechanisms to tag, attribute, or flag media objects without modifying the database schema or serialization formats.

### Option A: Gramps Native Tags (`TagBase`) — Recommended
Every primary object in Gramps (including `Media`) inherits from `TagBase` (`media.add_tag(...)`, `media.get_tag_list()`).
- **How it works:** When `gwizard_mediafix` processes or consolidates a media record, it attaches a tag—for example, **`MediaFixed`** or **`GWizard: Cleaned`** (with a dedicated color such as green or light blue).
- **Advantages:**
  1. **User Visibility:** The user immediately sees the tag and color indicator in the standard Gramps Media view.
  2. **Native Filtering:** Users and plugins can filter for `Media with tag MediaFixed` or `Media without tag MediaFixed` using standard Gramps quick filters.
  3. **Zero Risk:** Does not alter serialization or database schema; completely persistent and standard.
  4. **Downstream Checks:** In `gwizard_citationfix`, the tool can inspect `media.get_tag_list()` to instantly know if the media file has been verified/consolidated or is still unverified.

### Option B: Gramps Media Attributes (`AttributeBase`)
`Media` also inherits from `AttributeBase` (`media.add_attribute(...)`).
- **How it works:** Add a custom attribute such as `Type: "GWizardStatus"`, `Value: "Verified"`.
- **Advantages:** Invisible in casual UI (doesn't add clutter to user's personal tag list), but fully preserved in the database.
- **Trade-off:** Less visible at a glance than a Tag.

### Option C: Application-Level "Lock" Concept
Gramps does not have a native record-locking mechanism (records are locked only briefly during database transactions to prevent write collisions). However, attaching a **`Locked`** tag (or `GWizard: Locked` tag) can serve as an application-level lock that both `gwizard_mediafix` and `gwizard_citationfix` respect before modifying file paths, titles, or links.

---

## Summary Action Plan
1. **Tagging / Locking:** Use **Gramps Tags** (`MediaFixed` / `GWizard: Cleaned`) in `gwizard_mediafix` to flag and lock verified media.
2. **Dialog Integration:** In `gwizard_citationfix`, add a **`Link Citation Media`** (or **`Fix Citation Media`**) button between **Citation Attributes** and **Fix Notes**.
3. **Data Repair:** Provide an interactive review table allowing users to promote document images from Person galleries and master Sources down into specific Citations, and match orphan media to media-less citations based on date, surname, and source type.

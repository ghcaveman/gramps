# Media Arrangement, Citations, and URL Handling in GEDCOM

In genealogy software and the **GEDCOM** standard, multi-person records like a census or marriage certificate are handled by separating the **Source** (the historical document), the **Citation** (the specific piece of evidence pointing to a fact), the **Media Object / OBJE** (the image file), and **Links** to individuals, families, or events.

Crucially, **standard GEDCOM files do not embed actual image binaries** (like JPEGs or PNGs) inside the `.ged` text file; they only store a file path or URL pointing to where the image lives on your computer or server. (Note: GEDCOM 7 introduced *GEDZIP* packages to bundle media files together, support varies by software).

---

## Part 1: How Records and Images Are Structured

### 1. The Global Media Object (`OBJE`)
An image (e.g., `1940_Census_Page_12.jpg`) is defined once as a **Global Media Record** at the root level of the GEDCOM file (Level `0 @M1@ OBJE`).
* It contains the file path, title, and format (`FORM`).
* Because it is a global object, you do **not** upload or duplicate the image file for every single family member. You reference `@M1@` across multiple places.

### 2. The Source (`SOUR`)
The master document or archive record (e.g., *"1940 U.S. Federal Census, Cook County, Illinois, Population Schedule"*) is stored as a **Global Source Record** (Level `0 @S1@ SOUR`).
* It describes *what* the document is, where the archive is (`REPO`), and general publication details.

### 3. Citations (`SOUR` pointer + Page/Item details)
A citation connects a specific person, family, or event to the master Source (`@S1@`), often specifying the exact line, household number, or page.

---

### How They Attach to Individuals, Families, and Events

Depending on your genealogy software (such as Gramps, Ancestry, Family Historian, or RootsMagic), attaching an image to a multi-person record works through specific associations:

* **To an Event (Recommended Genealogical Standard):**
  * You attach the citation and the media object (`OBJE`) directly to a specific *event* rather than just floating it on a person profile.
  * *Example (Census):* You create a `CENS` (Census) event for **John Doe**, **Jane Doe**, and **Little Timmy Doe**. You attach the 1940 Census image and source citation to each of their respective `1 CENS` event blocks.
  * In GEDCOM, this looks like a sub-tag under the event:
    ```gedcom
    1 CENS
    2 DATE 15 APR 1940
    2 PLAC Chicago, Cook, Illinois
    2 SOUR @S1@
    3 PAGE Supervisor District 4, Enumeration District 16-100, sheet 12A
    2 OBJE @M1@
    ```
* **To a Family (`FAM`):**
  * For records that apply to a couple as a unit—such as a **Marriage License** (`MARR`)—the citation and image are attached to the Family record (`0 @F1@ FAM`) or the `1 MARR` family event. Both husband and wife point to that family event, meaning the image/citation is automatically shared by both partners without duplicating the media file.
* **To an Individual (`INDI`):**
  * You can attach a media object directly to an individual record as a portrait or general gallery item (e.g., a profile photo), or link the global `OBJE` `@M1@` as a sub-record under multiple individual nodes.
* **Global / Re-use Strategy:**
  * To re-use a single census image or marriage record across 5 different family members in the same household:
    1. Keep the image file saved once in your local media folder.
    2. Define it once as `0 @M1@ OBJE`.
    3. Link `@M1@` (and the corresponding `SOUR` citation) to each individual's relevant event (`BIRT`, `CENS`, `DEAT`) or to the shared `FAM` event.
    4. When exporting to GEDCOM, the file will output multiple `2 OBJE @M1@` or `1 OBJE @M1@` pointers referencing the single master `@M1@` definition rather than embedding the image multiple times.

---

## Part 2: Where Image & Citation URLs Are Stored in GEDCOM 5.5.1 / 5.5.5

In **GEDCOM 5.5.1** and **GEDCOM 5.5.5**, there is a structural asymmetry in how the official specification handles URLs:

* **Media Objects (`OBJE`):** Have a dedicated **`FILE`** tag that officially accepts either a local file path or a web URL.
* **Source Citations (`SOUR`):** **Do not have an official URL or `WWW` tag** in GEDCOM 5.5.1 or 5.5.5. The `WWW` tag was added in 5.5.1 *only* for **Repositories (`REPO`)**, **Submitters (`SUBM`)**, and **Event Details (`EVEN`)**.

Because of this missing tag on source citations, every genealogy software package has invented its own workaround—using either standard text fields (`PAGE`, `NOTE`, `TEXT`) or proprietary underscore tags (`_WEB`, `_URL`, `_LINK`)—when exporting a GEDCOM 5.5.1 file.

### 1. Where Image / Media URLs Are Stored (`OBJE`)

Across almost all genealogy platforms, if an image is hosted online (or exported from a cloud tree), its URL is placed inside the **`FILE`** sub-tag of the `OBJE` record.

| Software / Platform | Media URL Location in GEDCOM 5.5.1 | Behavior & Notes |
| :--- | :--- | :--- |
| **Ancestry.com** | `1 OBJE` -> `2 FILE https://...` | Exports inline `OBJE` blocks (not root `0 @M1@ OBJE`) with temporary/authenticated Ancestry media cache URLs. External programs usually cannot download them without logging in. |
| **MyHeritage (Web)** | `1 OBJE` -> `2 FILE https://...` | Exports direct URLs to MyHeritage's media servers (`mhcache.com` / `myheritageimages.com`) inside `2 FILE`. |
| **MyHeritage (FTB Desktop)** | `0 @M1@ OBJE` -> `1 FILE C:\...` | Exports local file paths rather than web URLs. |
| **RootsMagic (8–11)** | `0 @M1@ OBJE` -> `1 FILE ...` | Exports local file paths in `1 FILE`. If a URL is attached via **WebTags**, it exports under a custom `_WEB` block. |
| **Family Tree Maker (FTM)** | `0 @M1@ OBJE` -> `1 FILE ...` | Exports local file paths in `1 FILE`. Does not natively store web URLs as media files. |
| **Gramps** | `0 @M1@ OBJE` -> `1 FILE ...` | Exports whatever path or URL is stored in the Media Object's path field into `1 FILE`. |
| **Family Historian (6/7/8)** | `0 @M1@ OBJE` -> `1 FILE ...` | Exports local file paths in `1 FILE`. |
| **Legacy Family Tree** | `0 @M1@ OBJE` -> `1 FILE ...` | Exports local file paths in `1 FILE`. |
| **webtrees** | `0 @M1@ OBJE` -> `1 FILE https://...` | Supports both relative local paths and full `http`/`https` URLs inside `1 FILE`. |

### 2. Where Source & Citation URLs Are Stored (`SOUR`)

Because GEDCOM 5.5.1/5.5.5 forbids `2 WWW` or `3 WWW` inside `SOUR` records and citations, software vendors handle source/citation URLs in different ways during export:

* **RootsMagic (Versions 7, 8, 9, 10, 11):**
  * *Standard Export ("Extra details" unchecked):* WebTags are **dropped completely** unless the URL was manually typed into the Citation `Page` or `Research Note` fields.
  * *Enhanced Export ("Extra details" checked):* Exports WebTags attached to Master Sources or Citations using custom underscore tags:
    ```gedcom
    2 SOUR @S1@
    3 PAGE Sheet 12A
    3 _WEB
    4 _URL https://www.familysearch.org/ark:/...
    4 _NAME FamilySearch Record Link
    ```
* **Family Tree Maker (FTM 2017 / 2019 / 2024):**
  * Places the citation URL from its "Web Address" field inside the **`3 PAGE`** tag (often appended to the citation detail) or inside a custom **`3 _LINK`** / **`3 _URL`** tag depending on the export destination chosen, while Master Source URLs are often appended to `1 TITL` or `1 PUBL` (Publication) of `0 @S1@ SOUR`.
* **Ancestry.com (Web Tree Export):**
  * Does **not** put citation URLs in `3 PAGE`. Instead, it attaches proprietary record identifiers (`_APID`) to the citation so Ancestry/FTM/RootsMagic can reconstruct the URL internally:
    ```gedcom
    2 SOUR @S12345@
    3 PAGE Year: 1940; Census Place: Chicago, Cook, Illinois; Roll: m-t0627-00921; Page: 12A
    3 _APID 1,2442::142589312
    ```
  * *Note:* The `_APID` value (`1,<DatabaseID>::<RecordID>`) maps to `https://www.ancestry.com/discoveryui-content/view/<RecordID>:<DatabaseID>`.
* **MyHeritage (Online & Family Tree Builder):**
  * Stores source/record URLs inside the **`3 DATA` -> `4 TEXT`** substructure of the citation or inside a **`3 NOTE`** tag attached to the citation, formatted as plain text or HTML anchor tags (`<a href="...">`).
* **Legacy Family Tree (9 / 10):**
  * Writes Master Source URLs into **`1 WWW`** (technically non-standard in 5.5.1 under `0 @S1@ SOUR`, though widely tolerated) or appends them to **`1 PUBL`**. Citation-level URLs are placed in **`3 NOTE`** or **`3 DATA` -> `4 TEXT`**.
* **Gramps:**
  * Does not have a native URL field on Citations (only on Repositories/Internet tabs). On GEDCOM 5.5.1 export, Gramps **drops Citation Attributes** and exports Citation Notes into **`3 NOTE`** (or `0 @N1@ NOTE` pointers). Any URL typed into the `Volume/Page` field exports directly to **`3 PAGE`**.
* **Family Historian (6 / 7 / 8):**
  * Preserves custom tags like **`3 _URL`** or **`3 _WEB`** on citations by default. In "Strict GEDCOM 5.5.1" export mode, converts those fields into structured **`3 NOTE`** lines.
* **Heredis:**
  * Places Source/Citation URLs into the **`3 NOTE`** block of the citation or appends them to the **`1 PUBL`** (Publication) tag of the Master Source `0 @S1@ SOUR`.
* **webtrees:**
  * Expects citation URLs inside **`3 PAGE`** or inside **`3 NOTE`** / **`3 DATA` -> `4 TEXT`**, automatically converting `http://` and `https://` strings into clickable hyperlinks. Uses standard **`1 WWW`** on Repositories (`0 @R1@ REPO`).
* **The Master Genealogist (TMG) & Clooz:**
  * **TMG:** Exports citation URLs stored in *Citation Detail* into **`3 PAGE`**, and URLs stored in *Citation Memo* into **`3 NOTE`** (or `3 DATA.TEXT`).
  * **Clooz:** Exports document/citation URLs into **`3 NOTE`** or **`3 PAGE`** under the `SOUR` citation block.

### Summary Comparison Table: GEDCOM 5.5.1 Citation URL Export

| Software Package | Primary Tag for Citation URL | Secondary / Fallback Tag | Custom / Proprietary Tag? |
| :--- | :--- | :--- | :--- |
| **RootsMagic** | `3 _WEB` -> `4 _URL` | Dropped if "Extra details" unchecked | Yes (`_WEB`, `_URL`) |
| **Family Tree Maker** | `3 PAGE` (appended) or `3 _LINK` | `1 PUBL` (for Master Source) | Yes (`_LINK` / `_URL`) |
| **Ancestry.com** | `3 _APID` (ID lookup, not full URL) | None | Yes (`_APID`) |
| **MyHeritage** | `3 DATA` -> `4 TEXT` | `3 NOTE` | No (uses standard text/note tags) |
| **Legacy Family Tree** | `3 NOTE` or `3 DATA` -> `4 TEXT` | `1 WWW` (on Master `SOUR`) | Semi-standard (`1 WWW` on `SOUR`) |
| **Gramps** | `3 NOTE` (if placed in Citation Note) | `3 PAGE` (if placed in Vol/Page) | No (drops Citation Attributes) |
| **Family Historian** | `3 _URL` / `3 _WEB` | `3 NOTE` (in Strict GEDCOM mode) | Yes (`_URL`) |
| **Heredis** | `3 NOTE` | `1 PUBL` (on Master `SOUR`) | No |
| **webtrees** | `3 PAGE` or `3 NOTE` | `1 WWW` (on `REPO` only) | No (strict 5.5.1 / 5.5.5) |

### What Changed in GEDCOM 5.5.5 vs. GEDCOM 7.0?
* **GEDCOM 5.5.5 (2019):** Strictly kept the 5.5.1 grammar rules. It **still prohibits `WWW` inside `SOUR` citations**, forcing users and software to put citation URLs inside `3 PAGE` or `3 NOTE`.
* **GEDCOM 7.0 (2021):** Resolved this issue by allowing the **`WWW`** tag directly inside **`SOUR` records** and **`SOUR` citations** (`3 WWW https://...`), eliminating the need for custom `_URL` or `_WEB` tags going forward.

---

## Part 3: Gramps GEDCOM Import & Round-Trip Export Behavior

Gramps has a strict, zero-data-loss philosophy for GEDCOM imports, meaning it rarely deletes unrecognized custom tags—instead, it shunts them into **Notes** or **Attributes** so information is preserved. However, because Gramps' internal data model for **Citations** and **Media** lacks dedicated "URL" fields, how Gramps imports—and subsequently re-exports—those URLs depends entirely on which tag the originating software used.

### 1. How Gramps Imports URLs (By Tag & Source Software)

#### A. Media Object URLs (`OBJE` -> `FILE https://...`)
* **Originating Software:** Ancestry.com, MyHeritage Web, WikiTree, webtrees.
* **Where Gramps Imports It:** Gramps copies the exact `https://...` string straight into the **Path** field of the Gramps **Media Object**.
* **How Gramps Handles It:** Gramps treats the Path field strictly as a local filesystem path. It will **not** automatically download the image, and the Media viewer will show a "missing file" icon unless you manually download the file and update the path.

#### B. Standard Citation Text Tags (`3 PAGE` and `3 NOTE` / `3 DATA.TEXT`)
* **Originating Software:** Family Tree Maker (appended to `PAGE`), MyHeritage, Legacy Family Tree, Heredis, webtrees, TMG, Clooz.
* **Where Gramps Imports It:**
  * URLs inside `3 PAGE` import directly into the Citation's **Volume/Page** text box.
  * URLs inside `3 NOTE` or `3 DATA` -> `4 TEXT` import as a **Note** (type: *Citation* or *Source text*) attached to the Gramps Citation.

#### C. Non-Standard `WWW` Tags on Sources (`1 WWW` or `3 WWW`)
* **Originating Software:** Legacy Family Tree (uses `1 WWW` on Master `SOUR` records), GEDCOM 7.0 exports (`3 WWW`).
* **Where Gramps Imports It:**
  * If `1 WWW` is on a **Repository (`REPO`)**, Gramps imports it properly into the Repository's **Internet** tab (its native URL object).
  * If `1 WWW` or `3 WWW` is on a **Source** or **Citation**, Gramps' core 5.5.1 importer (`libgedcom.py`) does not recognize `WWW` there. It catches the line and dumps it into an attached Note of type **"GEDCOM import"** (e.g., `1 WWW https://...`) so the text is preserved.

#### D. Proprietary Underscore Tags (`_WEB`, `_URL`, `_LINK`, `_APID`, `_WLNK`)
* **Originating Software:** RootsMagic (`_WEB` / `_URL`), Family Tree Maker (`_LINK` / `_URL`), Family Historian (`_URL`), Ancestry (`_APID` / `_WLNK`).
* **Where Gramps Imports It:**
  * **`_APID` (Ancestry):** Gramps imports `_APID` as a **Citation Attribute** named `_APID` with the value `1,2442::142589312` (not a clickable URL).
  * **`_WEB` / `_URL` / `_LINK` (RootsMagic, FTM, Family Historian):** Because these are unrecognized custom tags inside a citation block, Gramps captures the raw GEDCOM lines and puts them into a **"GEDCOM import" Note** attached to that Citation or Source. *(Note: Using the third-party **GEDCOM Extensions** addon in Gramps allows mapping some custom tags to Attributes instead).*
  * **`_WLNK` (Ancestry Web Links on People):** Gramps imports these as custom **Events** on the person, with the URL stored in a Note or Attribute.

### 2. Round-Trip Survival: What Happens When Gramps Re-Exports to GEDCOM?

If you import a GEDCOM from another program into Gramps and then export a new GEDCOM 5.5.1 file from Gramps, **survival depends on where the URL landed inside Gramps**:

| Where the URL Landed in Gramps | Survives Gramps GEDCOM Export? | How It Exports & Destination Software Behavior |
| :--- | :--- | :--- |
| **Media Object `Path` field** (`https://...`) | **Yes (100%)** | Exports back out verbatim as `1 FILE https://...`. Any software that reads web URLs in `FILE` (like webtrees or MyHeritage) will read it again. |
| **Citation `Volume/Page` field** | **Yes (100%)** | Exports verbatim as `3 PAGE ...`. This is the **safest round-trip location**; nearly every genealogy program imports `3 PAGE` intact. |
| **Citation `Note` (including `"GEDCOM import"` notes)** | **Yes (with formatting changes)** | Exports as `3 NOTE ...` (or `3 NOTE @N1@` pointing to a `0 @N1@ NOTE` record). However, proprietary tags like `3 _WEB` / `4 _URL` are now **plain text inside a Note**, so RootsMagic or FTM will **not** recognize them as native WebTags/Web Addresses anymore—they will just show up as text in the Citation Notes. |
| **Repository `Internet` tab** | **Yes (100%)** | Exports as `1 WWW https://...` under `0 @R1@ REPO`. |
| **Citation `Attributes` (e.g., Ancestry `_APID`)** | **NO — LOST ON EXPORT** | **Critical Warning:** Gramps' GEDCOM 5.5.1 exporter **does not export Citation Attributes**. Any Ancestry `_APID` or custom attribute stored on a Gramps Citation is **completely stripped out** when Gramps exports a new GEDCOM. |

### 3. Summary Recommendations for Using Gramps as a Hub

1. **Expect Ancestry `_APID` links to be lost on re-export:** Because Gramps stores `_APID` in Citation Attributes and drops Citation Attributes during GEDCOM export, Ancestry record links will not survive a Gramps round-trip unless copied into a Note or the Volume/Page field beforehand.
2. **RootsMagic/FTM custom links become plain-text Notes:** Gramps saves them from deletion by putting them into `"GEDCOM import"` Notes, so you can still read and copy-paste the URL, but they lose their structured "WebTag" status when sent back out to other programs.
3. **Best practice if you plan to export from Gramps later:** Keep citation URLs in the **Volume/Page** field or in a standard **Citation Note**—both are guaranteed to export cleanly in GEDCOM 5.5.1.

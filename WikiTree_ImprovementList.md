# WikiTree Data Interface: Improvement Opportunities for Gramps

This document details opportunities for expanding the WikiTree data interface and GWizard merge workflow in Gramps (`gwizard_wikitree_merge` branch) to import additional data elements into the Gramps database.

---

## 1. Current State (What Is Imported Now)

In `WikiTreeGWizard._load()` (`gramps/gen/gwizard/gwizardwikitree.py`):

- **Names:** First name, middle name, birth/current surname, title prefix, suffix, nicknames. Adds an alternate name if `LastNameCurrent` differs from `LastNameBirth`.
- **Gender:** Mapped to `Person.MALE`, `Person.FEMALE`, or `Person.UNKNOWN`.
- **Attributes & URLs:** Stores `WikiTree ID` attribute and canonical profile URL (`https://www.wikitree.com/wiki/<ID>`).
- **Birth & Death Events:** Date (parsed via `dateparser.parse()`) and place (flat `Place` string).
- **Primary Photo:** Fetches `PhotoData` and creates a `Media` object pointing to `https://www.wikitree.com{path}`, but attaches it as a `MediaRef` to the *Citation* rather than directly to the `Person`.
- **Bio Note:** Dumps the entire raw wikitext / markdown into a single general `Note`.
- **Spouses:** Creates `Family` objects and marriage events when both partners exist in the batch.
- **Parent-Child Relationships (Implemented in 2A):** Links parents and children into `Family` structures using `ChildRef`, mapping WikiTree `DataStatus` confidence (DNA confirmation, sources confirmation, adoption, foster, stepchild).

---

## 2. Opportunities for Bringing Additional Data Elements into Gramps

### A. Parent-Child Relationships & Pedigree Certainty (`ChildRef`) [COMPLETED]
* **Implemented:**
  * Request `Father`, `Mother`, and `DataStatus` from the WikiTree API in `_DEFAULT_FIELDS`.
  * Extract nested `Parents` and `Children` dictionaries to populate relatives into `source_db`.
  * Support `include_relatives=True` to fetch full profiles for spouses and children in batch via `client.get_people()`.
  * Construct `Family` objects linking father and mother, and link child to the parental family via `ChildRef`.
  * Map WikiTree `DataStatus` to `ChildRefType` (`BIRTH`, `ADOPTED`, `FOSTER`, `STEPCHILD`).
  * Attach DNA / source confirmation notes (`"20"` = DNA confirmed, `"10"` = confirmed with sources) to `ChildRef`.
  * Maintain bidirectionality: `parent.family_handle_list` and `child.parent_family_handle_list`.

### B. Date Modifiers and Certainty (`Date` object) [COMPLETED]
* **Implemented:**
  * Added `BirthDateDecade` and `DeathDateDecade` to `_DEFAULT_FIELDS`.
  * Added `WikiTreeGWizard.wikitree_date_to_gramps(value, status, decade)`:
    * Preserves unknown month/day zeros (e.g. `1706-00-00` stays year 1706 without defaulting to Jan 1st).
    * Maps WikiTree certainty status to Gramps date modifiers & qualities:
      * `"guess"` / `"estimated"` &rarr; `Date.MOD_ABOUT` (`abt`), `Date.QUAL_ESTIMATED`
      * `"before"` &rarr; `Date.MOD_BEFORE` (`bef`)
      * `"after"` &rarr; `Date.MOD_AFTER` (`aft`)
      * `"certain"` &rarr; `Date.MOD_NONE`, `Date.QUAL_NONE`
    * Supports decade fallbacks (e.g. `"1700s"` &rarr; `Date.MOD_RANGE` 1700 to 1709) when full dates are missing.
  * Applied `wikitree_date_to_gramps` across Birth, Death, and Marriage events.
  * Set retrieval date on citations via `Today()`.
  * Added comprehensive unit test coverage for date parsing, certainty modifiers, and decades.

### C. Extraction of Sources & Citations from the Bio Text (`<ref>` and `== Sources ==`) [COMPLETED]
* **Implemented:**
  * Added `WikiTreeGWizard.parse_bio_sources(bio_text)`:
    * Parses inline `<ref>` tags, named tags (`<ref name="...">`), and self-closing reuse tags (`<ref name="..." />`).
    * Parses the `== Sources ==` / `== References ==` / `== Bibliography ==` section bibliography list (`* ...`).
    * Extracts surrounding text context to determine event associations (birth, death, burial).
  * Added `WikiTreeGWizard.clean_source_text(raw_text)`:
    * Normalizes external citation strings, resolves wiki links, and strips markup.
  * Added `WikiTreeGWizard.extract_source_title(cleaned_text)`:
    * Generates concise, meaningful titles for `Source` records.
  * Added `WikiTreeGWizard.clean_bio_text(bio_text)`:
    * Strips inline `<ref>` tags, wikitext templates, categories, and bibliography blocks, yielding a clean narrative note in Gramps.
  * Source & Citation generation in `_load`:
    * Creates deduplicated `Source` objects linked to the shared repository with publication URLs.
    * Creates `Citation` objects with page numbers and full citation `Note` records.
    * Links citations to the person, and automatically attaches birth/death citations to their respective `Birth` and `Death` events based on text context.
  * Added unit test coverage for source parsing, narrative cleaning, and event citation attachment.

### D. Categories as Gramps `Tag`s and `Attribute`s
* **Current Gap:** WikiTree profiles feature categories (returned in the `Categories` API array or `[[Category:...]]` in bio), which are currently ignored.
* **Opportunity:**
  * **Cemeteries & Burials:** Categories like `Category: Christ Church Burial Ground, Philadelphia, Pennsylvania` can automatically create a `Burial` event with the cemetery place and citation.
  * **Projects & Historical Service:** Categories such as `Signers of the United States Declaration of Independence`, `1776 Project`, `NSDAR Patriot Ancestors`, or `US Civil War` can be imported as color-coded Gramps **Tags**.
  * **Occupations:** Categories like `Printers`, `Scientists`, `US Postmasters General` can be added as Gramps `Occupation` events or attributes.
  * **One-Name Studies & DNA Studies:** E.g., `Franklin Name Study` &rarr; Gramps Tag.

### E. Structured Templates / Stickers [COMPLETED]
* **Implemented:**
  * Added `Templates` to `_DEFAULT_FIELDS` to retrieve structured template objects from the WikiTree REST API.
  * Added `WikiTreeGWizard.parse_bio_templates(bio_text)`:
    * Parses templates/stickers (`{{Name|param1|param2=val}}`) from wikitext biography when the `Templates` field is not pre-populated.
  * Added `WikiTreeGWizard.process_templates(person, templates, source_db, trans)`:
    * **Find A Grave (`FindAGrave`):** Generates `Attribute("Find A Grave ID")` and `Url("https://www.findagrave.com/memorial/<ID>")` of type `WEB_SEARCH`.
    * **Occupation (`Occupation`):** Generates `Event(OCCUPATION)` with cleaned description and adds an `Attribute("Occupation")`.
    * **Succession / Public Office (`Succession`):** Generates `Event(ELECTED)` with office title and parsed date span, plus `Attribute("Public Office")`.
    * **Society Ancestor (`Society Ancestor`, `DAR`, `SAR`):** Generates `Attribute("Society Ancestor")` (e.g. `DAR: A041702`).
    * **Military Service (`1776 Sticker`, `Military`, `Civil War`):** Generates `Event(MILITARY_SERV)` with unit/rank details.
    * **Notability (`Notability`):** Generates `Attribute("Notability")`.
    * **Project / Ancestor Stickers:** Generates `Attribute("Project / Sticker")` for recognized heritage stickers (Mayflower, Huguenot, Puritan, etc.).
  * Added unit test coverage for template parsing from bio wikitext, processing structured template objects, and attribute/URL/event creation.

### F. Additional Name Elements (`LastNameOther`, `RealName`) [COMPLETED]
* **Implemented:**
  * Added `MiddleInitial` and `ColloquialName` to `_DEFAULT_FIELDS`.
  * Name Type classification:
    * Primary birth name assigned `NameType.BIRTH`.
    * Current married surname assigned `NameType.MARRIED` as an alternate name when distinct from birth surname.
  * `LastNameOther` aliases:
    * Parses delimited aliases and previous married names from `LastNameOther` into alternate `Name` objects of type `NameType.AKA`.
  * `RealName` / `ColloquialName` preferred/call names:
    * Populates `name_obj.set_call_name(real_name)`.
    * Populates `name_obj.set_nick_name(real_name)` when no nickname is specified.
    * Generates an alternate `Name` of type `NameType.AKA` when `real_name` differs from the formal given name.
  * `MiddleInitial` fallback:
    * Automatically applies `MiddleInitial` when `MiddleName` is empty.
  * Added unit test coverage for `RealName`, `LastNameOther` aliases, married names, and `MiddleInitial` handling.

### G. Additional Events & Vital Status [COMPLETED]
* **Implemented:**
  * Added `IsLiving` and `Privacy` to `_DEFAULT_FIELDS`.
  * **Living Status & Privacy:**
    * When `IsLiving` is 1, attaches a `Living Status: Living` Attribute, and ensures no premature death event is attached.
    * When `IsLiving` is 0 and no specific death date or location exists on WikiTree, creates an empty `DEATH` event so Gramps recognizes the individual as deceased.
    * When WikiTree privacy level is private (`Privacy < 50` or `Privacy_IsPrivate` is True), sets `person.set_privacy(True)`.
  * **Marriage End / Divorce:**
    * Maps `MarriageEndDate` on spouse records to an `EventType.DIVORCE` event on the `Family` with date and certainty modifier.
  * **Burial Events:**
    * Detects cemetery categories (e.g. `Christ Church Burial Ground`, `Granary Burying Ground`, etc.) from profile `Categories` or wikitext bio, and creates an `EventType.BURIAL` event with the cemetery place and citation.
  * Added unit test coverage for living status, privacy, deceased fallback, divorce events, and burial events.

### H. Media & Gallery Improvements [COMPLETED]
* **Implemented:**
  * **Person Media Attachment:** Attached primary photo directly to `Person` (`person.add_media_reference(p_mref)`), so it serves as the person's avatar in Gramps, while continuing to link it to the Citation for provenance.
  * **Dynamic MIME Type Detection:** Replaced hardcoded `"image/jpeg"` with `mimetypes.guess_type` supporting JPEG, PNG, GIF, and WebP images.
  * **Metadata & Dimensions:** Populates original file name, description, and stores `orig_width` x `orig_height` as a `Dimensions` Attribute on the `Media` object.
  * **Filename Fallback:** When `PhotoData` dictionary is omitted but `Photo` file string is provided, automatically constructs the canonical WikiTree image URL.
  * **Bio Gallery Extraction:** Scans wikitext bio for `[[Image:filename|caption]]` or `[[File:...]]` tags and extracts additional photos into the person's gallery with cleaned captions.
  * **Deduplication:** Maintained `media_cache` across profiles to avoid duplicate media records for shared images.
  * Added unit test coverage for direct person media attachment, dimensions attribute, MIME type detection, filename fallback, and bio gallery extraction.

### I. Hierarchical Place Parsing [COMPLETED]
* **Implemented:**
  * Added `WikiTreeGWizard.determine_place_type(name, level_from_top, total_levels)`:
    * Categorizes geographic tokens into `PlaceType.COUNTRY`, `PlaceType.STATE`, `PlaceType.COUNTY`, `PlaceType.CITY`, `PlaceType.BUILDING`, `PlaceType.PARISH`, `PlaceType.TOWN`, etc., based on hierarchy depth and keywords (Cemetery, Parish, County, Township, Colony, etc.).
  * Upgraded `get_or_create_place` in `WikiTreeGWizard._load`:
    * Splits comma-separated WikiTree place strings into individual tokens.
    * Builds hierarchical `Place` records from right to left (top level down to locality).
    * Links enclosing places with `PlaceRef` objects.
    * Sets clean leaf place names (`get_name().get_value()`) while preserving the full location title (`get_title()`).
    * Reuses common enclosing places (e.g. County, State, Country) via cache.
  * Enhanced `GedGWizard._apply`'s `copy_place`:
    * Recursively copies or reuses enclosing parent `PlaceRef`s when transferring places to the target database.
  * Added unit test coverage for place type inference, multi-level place hierarchy linking, and enclosing place sharing.

### J. Drift & Synchronization Metadata [COMPLETED]
* **Implemented:**
  * Added `Touched`, `Manager`, and `Created` to `_DEFAULT_FIELDS`.
  * Added `WikiTreeGWizard.format_wikitree_timestamp(ts)`:
    * Formats WikiTree timestamps (`YYYYMMDDHHMMSS`) into ISO `YYYY-MM-DD HH:MM:SS`.
  * Added `WikiTreeGWizard.check_profile_drift(target_person, remote_touched)`:
    * Compares local person's `WikiTree Touched` attribute with the remote WikiTree profile timestamp to detect if remote changes have occurred since last sync.
  * In `_load`:
    * Attaches `WikiTree Touched` and `WikiTree Manager` Attributes to the person.
    * Records `Last Modified` timestamp and `Profile Manager ID` in the primary Citation note.
  * In `_apply`:
    * Synchronizes `WikiTree Touched` and `WikiTree Manager` attributes onto the target person during merge.
  * Added unit test coverage for timestamp formatting, drift calculation, citation note metadata, and merge attribute synchronization.

---

## 3. Immediate Code Fixes Applied

1. **Import Path Fix:**
   - Updated `from .gwizard` / `from ..gwizard` to `gwizard_base` in `gwizardwikitree.py` and `gwizardwikitree_test.py`.
2. **Item 2A Implementation:**
   - Implemented parent-child and family relationship loading with `ChildRef`, `ChildRefType` mapping, DNA confirmation notes, and bidirectionally maintained family handle lists.
   - Added unit tests covering parent-child linking, DNA confidence, adopted/stepchild status, and nested dictionary extraction.

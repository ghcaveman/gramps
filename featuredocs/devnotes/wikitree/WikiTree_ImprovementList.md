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

---

## 2. Opportunities for Bringing Additional Data Elements into Gramps

### A. Parent-Child Relationships & Pedigree Certainty (`ChildRef`)
* **Current Gap:** While `Spouses` are linked into `Family` objects, **children are never linked** to families via `ChildRef` (even though `ChildRef` is imported in `gwizardwikitree.py`).
* **Opportunity:**
  * The WikiTree API provides `Father`, `Mother`, `Parents`, and `Children` in the person payload.
  * When parents or children are retrieved (especially during multi-generation ancestor crawls), link children to their parental `Family` using `ChildRef`.
  * **Relationship Type & Confidence:** WikiTree's `DataStatus` indicates parentage confidence:
    * `"20"` = DNA confirmed
    * `"10"` = Confirmed with sources
    * `"uncertain"` / non-biological / adopted
  * These map directly to `ChildRef.frel` / `ChildRef.mrel` (e.g. `ChildRef.REL_BIRTH`, `ChildRef.REL_ADOPTED`, `ChildRef.REL_STEPCHILD`).

### B. Date Modifiers and Certainty (`Date` object)
* **Current Gap:** `gwizardwikitree.py` parses date strings with `dateparser.parse()`, completely discarding `BirthDateStatus` and `DeathDateStatus` (even though both fields are requested in `_DEFAULT_FIELDS`).
* **Opportunity:**
  * A helper already exists in `gwizardwikitreeprovenance.py` (`wikitree_date_to_gramps()`) that maps WikiTree certainty flags to Gramps `Date` modifiers:
    * `"guess"` &rarr; `Date.MOD_ABOUT` (`abt`)
    * `"before"` &rarr; `Date.MOD_BEFORE` (`bef`)
    * `"after"` &rarr; `Date.MOD_AFTER` (`aft`)
    * `"certain"` &rarr; `Date.QUAL_CERTAIN`
  * Using this helper in `gwizardwikitree.py` preserves vital genealogical uncertainty across birth, death, and marriage events.
  * WikiTree also returns `BirthDateDecade` and `DeathDateDecade` (e.g. `"1700s"`), which can serve as fallback approximate date spans when full dates are missing.

### C. Extraction of Sources & Citations from the Bio Text (`<ref>` and `== Sources ==`)
* **Current Gap:** The biography currently imports as an unparsed wikitext dump filled with inline `<ref>` tags and Wiki formatting.
* **Opportunity:**
  * WikiTree profiles adhere to standard wikitext referencing:
    * `<ref>Source text or URL</ref>`
    * `<ref name="...">Source text</ref>`
    * `== Sources ==` containing a bulleted bibliography (`* Author, Title...`)
  * These can be parsed to generate structured Gramps `Source` and `Citation` records linked to the person or specific events (birth, death, marriage).
  * Stripping `<ref>` tags from the biography leaves a clean narrative note in Gramps.

### D. Categories as Gramps `Tag`s and `Attribute`s
* **Current Gap:** WikiTree profiles feature categories (returned in the `Categories` API array or `[[Category:...]]` in bio), which are currently ignored.
* **Opportunity:**
  * **Cemeteries & Burials:** Categories like `Category: Christ Church Burial Ground, Philadelphia, Pennsylvania` can automatically create a `Burial` event with the cemetery place and citation.
  * **Projects & Historical Service:** Categories such as `Signers of the United States Declaration of Independence`, `1776 Project`, `NSDAR Patriot Ancestors`, or `US Civil War` can be imported as color-coded Gramps **Tags**.
  * **Occupations:** Categories like `Printers`, `Scientists`, `US Postmasters General` can be added as Gramps `Occupation` events or attributes.
  * **One-Name Studies & DNA Studies:** E.g., `Franklin Name Study` &rarr; Gramps Tag.

### E. Structured Templates / Stickers
* **Current Gap:** WikiTree profiles include structured templates (returned under `Templates` in the API), currently lost in the raw text.
* **Opportunity:**
  * `{{FindAGrave|364}}` &rarr; Direct Find A Grave Memorial URL link (`UrlType.WEB_SEARCH`), burial citation, or `FindAGrave ID` attribute.
  * `{{Occupation |text=...}}` &rarr; Gramps `Occupation` event with description.
  * `{{Society Ancestor|society=DAR|ancestor=A041702}}` &rarr; Society membership attribute / citation.
  * `{{Succession|position1=...|years1=...}}` &rarr; Noble / public office attributes or historical events.

### F. Additional Name Elements (`LastNameOther`, `RealName`)
* **Current Gap:** Only `LastNameBirth` and `LastNameCurrent` are mapped.
* **Opportunity:**
  * `LastNameOther`: Contains previous married names, maiden aliases, or Anglicized variants. Each can be added as an alternate `Name` object.
  * `RealName` / `ColloquialName`: Often holds the preferred/call name or nickname, mapping to `Name.set_call_name()` or `Name.set_nick_name()`.
  * `MiddleInitial`: Useful fallback if `MiddleName` is empty.

### G. Additional Events & Vital Status
* **Marriage End / Divorce:**
  * WikiTree returns `MarriageEndDate` and data status on spouse records. This can generate a `Divorce` or `Annulment` event on the `Family`.
* **Living Status & Privacy:**
  * `IsLiving`: 0 or 1. Can be used with `person.set_privacy()` or to populate Gramps living status rules.

### H. Media & Gallery Improvements
* **Current Gap:** The primary photo is linked only to the `Citation`.
* **Opportunity:**
  * Attach the profile image directly to `Person` using `person.add_media_reference(mref)`, and set it as the primary avatar (`person.set_primary_media(media_h)`).
  * Use caption / title metadata from `PhotoData` (orig dimensions, file name, description).

### I. Hierarchical Place Parsing
* **Current Gap:** Places like `"Boston, Suffolk, Massachusetts Bay Colony"` create a single flat `Place` object.
* **Opportunity:**
  * Parse comma-separated parts into hierarchical enclosing places (Locality &rarr; County &rarr; State &rarr; Country) or match existing places already structured in the user's database.

### J. Drift & Synchronization Metadata
* **Opportunity:**
  * WikiTree provides `Touched` (timestamp of last modification) and `Manager` ID.
  * Storing `WikiTree Touched` or retrieval date on the citation enables future sync checks to detect if a profile has been updated on WikiTree since the last merge.

---

## 3. Code Fix Applied

The broken import resulting from the recent `gwizard.py` &rarr; `gwizard_base.py` rename has been fixed:
* In `gramps/gen/gwizard/gwizardwikitree.py` (line 78) and `gramps/gen/gwizard/test/gwizardwikitree_test.py` (line 116):
  ```python
  from .gwizard_base import is_wikitree_id, extract_wikitree_id, get_wikitree_id
  ```
All 16 unit tests in `gramps.gen.gwizard.test.gwizardwikitree_test` now pass.

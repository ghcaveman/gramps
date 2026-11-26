I now have a complete picture of all differences between the two files. Here is the detailed comparison:

---

## Comparison: `White-Pittaluga_LegacyImport_Backup_2026-10-16_AfterGoatFix.ged` vs `AfterMerge.ged`

The two files are nearly identical (both ~23.5K lines). The only actual data changes involve **one person: Martha Eizabeth Baldwin (@I500374@)**, plus some administrative header changes and new source/note/repository records appended at the end.

---

### 1. Administrative / Header Changes (lines 3, 6, 8)

| Field | Before | After |
|-------|--------|-------|
| GEDCOM version | `2 VERS AIO64-6.1.0+gg.1` | `2 VERS 6.1.0-beta2` |
| Export time | `2 TIME 06:17:07` | `2 TIME 09:35:46` |
| File path | `C:\Users\gocav\Documents\FamilyTree\...` | `C:\gramps_dev\gramps_gwizard_wikitreemerge_plugin\AfterMerge.ged` |

---

### 2. DATA REPLACED — Martha Eizabeth Baldwin (@I500374@)

This is the person you updated. Here is what changed on her record:

#### Name (typo fix)
- `1 NAME Martha Eizabeth /Baldwin/` → `1 NAME Martha Elizabeth /Baldwin/`
- `2 GIVN Martha Eizabeth` → `2 GIVN Martha Elizabeth`

#### Birth event
| Field | Before | After |
|-------|--------|-------|
| Date | `2 DATE 1813` | **unchanged** (`2 DATE 1813`) |
| Place | `2 PLAC Tennessee, United States` | `2 PLAC Powell Valley, Claiborne, Tennessee, United States` |
| Source | `2 SOUR @S00071@` (FamilySearch Family Tree) | `2 SOUR @S00000@` (WikiTree - Baldwin-15771) |
| Source page | `entry for Sarah Ann Cameron, person ID 9QX7-B5K` | `WikiTree: Baldwin-15771` |
| *New* | *(none)* | `3 DATA / 4 DATE 24 NOV 2026` + `3 NOTE @N00006@` |

#### Death event
| Field | Before | After |
|-------|--------|-------|
| Date | `2 DATE 4 FEB 1873` | `2 DATE 1873` *(day/month removed — less precise)* |
| Place | `2 PLAC Nodaway, Missouri, United States` | **removed entirely** |
| Source | `2 SOUR @S00071@` | `2 SOUR @S00000@` (WikiTree) |
| Source page | `entry for Sarah Ann Cameron, person ID 9QX7-B5K` | `WikiTree: Baldwin-15771` |
| *New* | *(none)* | `3 DATA / 4 DATE 24 NOV 2026` + `3 NOTE @N00006@` |

#### New FACT records added to Martha's record
```
1 FACT Baldwin-15771
  2 TYPE WikiTree ID
1 FACT 2022-08-28 16:16:59
  2 TYPE WikiTree Touched
```

#### New source citations on Martha's record
```
1 SOUR @S00000@
  2 PAGE WikiTree: Baldwin-15771
  2 DATA
    3 DATE 24 NOV 2026
    2 NOTE @N00006@
1 SOUR @S00001@
  2 DATA
    3 DATE 24 NOV 2026
    2 NOTE @N00007@
1 WWW https://www.wikitree.com/wiki/Baldwin-15771
1 NOTE @N00042@
```

#### Change record updated
- `CHAN` date/time changed from `12 JUL 2026 13:54:00` → `24 NOV 2026 09:31:21`

---

### 3. DATA APPENDED (new records at end of file)

These are brand-new records that did not exist in the "Before" file:

#### New Source Records
| ID | Title |
|----|-------|
| `@S00000@` | WikiTree - Baldwin-15771 |
| `@S00001@` | Unsourced family tree handed down to Alan Crowe |

(Note: Sources `@S00002@` through `@S00071@` also appear at the end of the AfterMerge file — many appear to be existing sources that were re-serialized/appended rather than newly created.)

#### New Repository Record
| ID | Name |
|----|------|
| `@R00001@` | WikiTree (Free Family Tree) |

#### New Note Records
| ID | Content |
|----|---------|
| `@N00006@` | `NOTE URL: https://www.wikitree.com/wiki/Baldwin-15771` + `CONT Last Modified: 2022-08-28 16:16:59` |
| `@N00007@` | `NOTE Unsourced family tree handed down to Alan Crowe.` |
| `@N00042@` | `NOTE Biography:` + `Martha was born in 1813. She was the daughter of Andrew Baldwin and Polly Munkers. She passed away in 1873.` |

---

### 4. Media File Path Changes (lines 23529, 23536)

Two media `FILE` paths were converted from Windows backslash to forward-slash notation:

- `c:\users\public\pictures\familytree\I00450_Fuller_Harry_Jay-Census-1910.jpg` → `c:/users/public/pictures/familytree/I00450_Fuller_Harry_Jay-Census-1910.jpg`
- `c:\users\public\pictures\familytree\I00451_Devault_Nettie-Census-1900.jpg` → `c:/users/public/pictures/familytree/I00451_Devault_Nettie-Census-1900.jpg`

---

### Summary

**What was replaced:**
- Martha Elizabeth Baldwin's first name typo ("Eizabeth" → "Elizabeth")
- Her birth place (generalized "Tennessee" → specific "Powell Valley, Claiborne, Tennessee")
- Her death date (specific "4 FEB 1873" → year-only "1873")
- Her death place ("Nodaway, Missouri" → removed)
- All source citations for her birth and death events (switched from FamilySearch `@S00071@` to WikiTree `@S00000@`)

**What was appended:**
- New WikiTree source (`@S00000@`) and unsourced-tree source (`@S00001@`)
- New WikiTree repository (`@R00001@`)
- New notes (`@N00006@`, `@N00007@`, `@N00042@` including a biography)
- New FACT tags (WikiTree ID, WikiTree Touched) on Martha's record
- New WWW link to her WikiTree profile
- Additional source citations throughout her record
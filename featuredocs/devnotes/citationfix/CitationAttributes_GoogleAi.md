# Transcript: GEDCOM & Gramps Data Quality Standards

## 1. GEDCOM Data Quality and Confidence Standard
In the GEDCOM standard, data quality and confidence are officially designated by the **`QUAY` (Quality of Data)** tag. This tag represents a certainty assessment indicating the credibility of a piece of information based on its supporting evidence, typically attached to a source citation (`SOUR`).

### The Standard Certainty Scale
Across all major versions (including GEDCOM 5.5.1 and 7.0), the standard enforces a fixed, four-value numeric scale:

| Code | Standard Meaning | Interpretation / Genealogical Context |
| :--- | :--- | :--- |
| **`0`** | **Unreliable** | Unreliable evidence, or data estimated from a random guess or suspect source. |
| **`1`** | **Questionable** | Questionable reliability (e.g., formal/official text matched with a direct contradiction, or oral family traditions). |
| **`2`** | **Secondary** | Secondary evidence, or data gleaned from an official document created a significant amount of time after the event. |
| **`3`** | **Primary** | Direct, primary evidence, or data from an official document recorded at or very close to the time of the event. |

### Limitations & Industry Reality
* **Too Subjective:** The standard four-value system is considered too simplistic for serious evidence analysis.
* **No "Direct vs. Indirect" Distinction:** The modern *Genealogy Proof Standard (GPS)* separates sources, information, and evidence into complex matrixes (Primary vs. Secondary sources; Direct vs. Indirect vs. Negative evidence). The basic `QUAY` tag cannot map cleanly to these.
* **Inconsistent Software Support:** Many modern genealogy applications ignore it or use proprietary custom tags, which don't transfer perfectly between platforms.

---

## 2. Enhancing Value with Note Tags (`NOTE`)
To implement a structured, machine-scannable rubric mirroring the GPS framework, you can standardize the data inside your plain-text notes.

### Structured Tag-Value System Inside the Note
```text
[QUALITY ASSESSMENT]
Source: [Original | Derivative | Authored]
Information: [Primary | Secondary | Unknown]
Evidence: [Direct | Indirect | Negative]
Analysis: [Your brief textual explanation of why you gave it this rating]
```

### Definitions
* **Source Type:** `Original` (first-hand material), `Derivative` (transcript/index), or `Authored` (compiled tree/book).
* **Information Type:** `Primary` (provided by a firsthand witness close to the event) or `Secondary` (provided by someone not there or recorded long after).
* **Evidence Type:** `Direct` (explicitly answers the question) or `Indirect` (requires combining clues to infer a fact).

### GEDCOM Representation
```text
1 BIRT
2 DATE 14 MAR 1882
2 PLAC Boston, Suffolk, Massachusetts
2 SOUR @S101@
3 QUAY 2
3 NOTE [QUALITY ASSESSMENT]
4 CONT Source: Derivative (Online database index)
4 CONT Information: Secondary (Birth date reported on a WW1 draft card decades later)
4 CONT Evidence: Direct (Explicitly states a date of birth)
4 CONT Analysis: The informant is the individual himself, which gives high confidence, but 
4 CONT because this is an index of a record created 36 years after the birth, a primary birth 
4 CONT certificate is still required to confirm.
```

---

## 3. Gramps Genealogy Software Capabilities
Gramps provides built-in, native features to categorize and track the quality, reliability, and confidence of a citation beyond plain-text notes.

### 1. Built-in "Confidence" Menu
Gramps features a built-in Confidence Dropdown Menu for citations. It internally handles a five-tier text scale that maps to GEDCOM standards:
* `Very High` (Maps to GEDCOM Primary / 3)
* `High`
* `Normal` (Default fallback)
* `Low`
* `Very Low` (Maps to GEDCOM Unreliable / 0)

### 2. Citation Attributes
Every citation object in Gramps contains an **Attributes Tab**. Attributes are structured key-value pairs (Key, Value, and optional attached notes/sources). 
* **Custom Customization:** Gramps has no built-in or pre-defined Citation Attributes out of the box. You must create your own keys (e.g., `Evidence Type`).
* **Automation:** Gramps remembers your key history for auto-completion. You can also add blank fields to a citation template, move it to the **Gramps Clipboard**, and drag-and-drop it to duplicate fields rapidly across new citations.

### 3. Color-Coded Tags
Allows attaching custom colored labels to individual Citations for workflow signaling (e.g., Red for `Unverified / Guess`, Green for `GPS Certified`).

---

## 4. SuperTool Integration in Gramps
The third-party addon **SuperTool** does not use or hardcode a standard mapping to Citation Attributes because Gramps doesn't define them natively. Instead, it provides Python proxy object accessibility.

### Read Access
SuperTool exposes an `attributes` list for citations evaluated as `(name, value)` string tuples:
```python
for name, val in citation.attributes:
    if name == "Evidence Type":
        print(val)
```

### Write Access / Automation
To automatically create or modify custom tracking fields in bulk using SuperTool, you instantiate the core Gramps database libraries via its execution window using `SrcAttribute`:
```python
from gramps.gen.lib import SrcAttribute

# Create a new attribute container
gps_attr = SrcAttribute()
gps_attr.set_type("Evidence Type")
gps_attr.set_value("Direct")

# Attach it to the citation being processed
citation.add_attribute(gps_attr)
```
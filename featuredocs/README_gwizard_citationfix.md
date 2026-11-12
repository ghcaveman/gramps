## Overview

The **GWizard citation fix** tool helps genealogists clean up and standardise citation data across the entire database. It analyses sources, repositories, and citations, offering suggestions to merge duplicate entries, assign correct repositories, unpack conflated titles, and add missing citation attributes. The tool also generates a detailed report of the analysis.

![GWizard citation fix main dialog](images/gwizard_citationfix-main.png)

## Usage

1. Open Gramps and navigate to **[VERIFY MENU PATH]**.
2. In the dialog you will see a series of buttons:
   - **Generate report** – creates a plain‑text citation analysis report.
   - **Unpack Conflated Source** – separates mixed or ambiguous source titles.
   - **Repository Consolidate** – groups similar repository entries.
   - **Fix Repositories** – assigns the best‑matching repository to sources.
   - **Fix Sources** – merges duplicate sources and trims excess data.
   - **Unpack Conflated Citation** – separates merged citation text.
   - **Fix Citations** – refines citation details such as volume/page and confidence.
   - **Citation Attributes** – adds or updates structured attributes (e.g., evidence type, confidence).
   - **Link Citation Media** – discovers documentary scans in galleries, master sources, or orphan files, validates compatibility, and links them directly to citations.
   - **Fix Notes** – cleans up notes attached to citations.
   - **Accept all hints** – runs all 9 steps automatically, applying safe fixes in one transaction per step.
3. Click the desired button(s) to perform the action. Most actions display a preview table where you can review and edit the suggested changes before applying them.
4. After completing the steps, you can close the dialog.

## Configure Options

*This tool does not expose additional checkboxes or configuration fields; all behaviour is driven by the buttons above.*

## Features

- **Automated analysis** of sources, repositories, citations, and attached evidence media.
- **Generate a comprehensive report** (`CitationFixReport.txt`), including media layout and citation evidence coverage.
- **Unpack conflated source titles** to separate distinct source information.
- **Consolidate similar repositories** and assign gold‑standard repository names.
- **Merge duplicate sources** and trim unnecessary data.
- **Unpack conflated citations** for clearer citation records.
- **Refine citation details** such as volume/page and confidence levels.
- **Add structured citation attributes** (e.g., evidence type, confidence).
- **Link Citation Media** – matches documentary media to citations with mismatch prevention heuristics:
  - *Chronological check:* flags date discrepancies between image and citation/source.
  - *Category compatibility:* prevents incompatible pairings (e.g., death certificate on census citation).
  - *Surname & sheet/page verification:* checks family names and sheet numbers.
  - *Inspector side-panel:* interactive thumbnail preview and full compatibility score breakdown.
  - *Owner detachment:* option to promote scans out of Person/Event galleries into citations, preserving locked media (`GWizard: Locked`).
- **Clean up citation notes** automatically.
- **Accept all hints** – one‑click execution of all 9 steps with preview and human intervention reporting.

![GWizard citation fix main dialog](images/gwizard_citationfix-main.png)

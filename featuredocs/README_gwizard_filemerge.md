## Overview

The GWizard File Merge tool compares another genealogy file (GEDCOM, Gramps XML, or another supported format) side by side with the open Family Tree and lets you merge selected differences person by person. The incoming file is loaded into a temporary source database and displayed next to your tree in the **GWizard Compare** window. You step through the people that differ, then choose, for each person, to copy individual fields into your tree or add the incoming person as a brand-new person. Nothing is merged automatically — you control exactly what is applied.

![The GWizard Compare window shows the incoming file (left) beside the open Family Tree (right).](images/gwizard_filemerge-compare.png)

## Usage

1. Open Gramps and load the Family Tree you want to merge into.
2. Choose **Tools > Family Tree Processing > GWizard File Merge**.
   - The **Select File to Compare** file chooser opens immediately; there is no separate options dialog.
3. Browse to and select the source genealogy file (for example, a GEDCOM or Gramps XML file), then click **OK**. Gramps reads the file and opens the **GWizard Compare** window.
4. Select a person pair to compare. The left panel shows the incoming person and the right panel shows the matching person in your Family Tree (or is empty when the person is new). Use the detail sections — **Individual Details**, **Family Relations**, **Children**, and **Events & Other Records** — to review the differences.
5. Work through the pairs with the toolbar buttons:
   - **Previous**: Move to the previous record that has differences.
   - **Next**: Move to the next record that has differences.
   - **Add as New...**: Add the selected incoming person as a new person in the Family Tree.
   - **Merge...**: Open the field-by-field merge dialog for the selected person pair.
6. Repeat until you have reviewed everyone you want to merge, then click **Close**.

### Previous

1. In the **GWizard Compare** window, select a person pair.
2. Click **Previous**.
   - The window moves to the previous record that has differences and re-highlights it.

### Next

1. In the **GWizard Compare** window, select a person pair.
2. Click **Next**.
   - The window moves to the next record that has differences and re-highlights it.

### Add as New...

1. In the **GWizard Compare** window, select the incoming person you want to add.
2. Click **Add as New...**.
   - If the person is currently paired with a person in your tree, the pairing is removed (rejected) so the person is treated as unmatched.
   - Otherwise, the **Add as New Person** dialog opens.
   ![The Add as New Person dialog previews the relatives that will be linked.](images/gwizard_filemerge-add-as-new.png)
3. The **Link family relationships** checkbox is on by default. Leave it checked to link relatives who are already in your tree to the new person; clear it if you do not want relationships linked.
4. Click **Add**. The incoming person is copied into your Family Tree as a brand-new person.
5. If some relationships could not be linked, a **Some relationships were not linked** warning opens; review the message and dismiss it.
   ![The warning lists any relationships that could not be linked.](images/gwizard_filemerge-add-as-new-complete.png)

### Merge...

1. In the **GWizard Compare** window, select a person pair that exists in both the incoming file and your Family Tree.
2. Click **Merge...**. The **GWizard Merge** dialog opens, showing the incoming person on the left and your tree's person on the right.
   ![The GWizard Merge dialog lists each differing field with an arrow to copy the incoming value into the tree.](images/gwizard_filemerge-merge.png)
3. For each field you want to take from the incoming file, click the **⇒** arrow button beside it (the tooltip reads "Move &lt;field&gt; to current family tree"). The button changes to **✓** and becomes insensitive.
4. Review the **Father**, **Mother**, and **Spouse** relationship rows and link any relatives that are not yet matched.
5. Click **Apply** to commit the selected resolutions to your Family Tree. The merge runs in a single transaction, so if it fails, a **Merge failed** error dialog appears and no changes are made.

## Configure Options

The tool has no separate configuration dialog (its option set is empty). You configure the merge through these controls as you work:

- **Select File to Compare** — file chooser that opens when the tool starts; choose the source genealogy file (GEDCOM, Gramps XML, or another supported format) and click **OK**, or **Cancel** to abort.
- **Previous** — move to the previous record that has differences.
- **Next** — move to the next record that has differences.
- **Add as New...** — add the selected incoming person as a new person in the Family Tree.
- **Merge...** — open the field-by-field merge dialog for the selected person pair.
- **Close** — close the GWizard Compare window.
- **Detail sections** — collapsible panels showing **Individual Details**, **Family Relations**, **Children**, and **Events & Other Records** for the selected pair.
- **Link family relationships** — checkbox in the **Add as New Person** dialog (checked by default); links relatives already in the tree to the newly added person.
- **⇒ arrow button** — in the **GWizard Merge** dialog, copies the incoming value for one differing field into the Family Tree; becomes **✓** and is disabled after use.
- **Father / Mother / Spouse** — relationship rows in the merge dialog used to link relatives between the two trees.
- **Apply** — commit the selected field resolutions to the Family Tree.
- **Cancel** — close the **Add as New Person** or **GWizard Merge** dialog without applying changes.

## Features

- Compare a source genealogy file (GEDCOM, Gramps XML, and other supported formats) side by side with the open Family Tree.
- Review paired people in collapsible sections: Individual Details, Family Relations, Children, and Events & Other Records.
- Step through the records that have differences using **Previous** and **Next**.
- Merge selected fields person by person from the incoming file into the Family Tree using field-by-field **⇒** arrows.
- Add an incoming person as a brand-new person in the tree, optionally linking family relationships.
- Selective, person-by-person merging — you choose exactly which differences to apply; nothing is merged automatically.
- Changes are committed in a single database transaction that is rolled back if the merge fails, so a failed merge leaves your tree unchanged.

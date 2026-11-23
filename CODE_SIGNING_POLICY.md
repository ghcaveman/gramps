Code signing policy
===================

Free code signing provided by [SignPath.io](https://signpath.io),
certificate by [SignPath Foundation](https://signpath.org).

> **Status:** GoatGramps has applied to the SignPath Foundation open-source
> program. Until the application is approved, releases are not code signed.

What is signed
--------------

Only the GoatGramps **Windows installer** (`GrampsAIO-*_win64.exe`) and the
GoatGramps executables inside it are signed with the SignPath Foundation
certificate. The macOS (`.dmg`) and Linux (`.deb`) packages in each release
are not covered by this policy.

Third-party components bundled in the Windows installer (Python, GTK and the
MSYS2 libraries) are distributed under their own open-source licenses and are
not represented as GoatGramps code.

How signed releases are built
-----------------------------

* Signed installers are built only by GitHub Actions, from the public
  [ghcaveman/gramps](https://github.com/ghcaveman/gramps) repository, when a
  `gg-*` release tag is pushed on the `goatgramps/core` branch
  (`.github/workflows/deploy-releases.yml`).
* No locally built binary is ever signed.
* Every signing request is approved manually by an approver listed below
  before the signed installer is published.

Team roles
----------

* Committers and reviewers: Kevin White ([@ghcaveman](https://github.com/ghcaveman))
* Approvers: Kevin White ([@ghcaveman](https://github.com/ghcaveman))

Changes from other contributors are reviewed by a committer before they are
merged. All team members use multi-factor authentication for GitHub and
SignPath.

GoatGramps is a fork of [Gramps](https://gramps-project.org). Code merged
from upstream Gramps is reviewed before it is merged into `goatgramps/core`.

Privacy policy
--------------

GoatGramps will not transfer any information to other networked systems
unless specifically requested by the user or the person installing or
operating it.

Family Tree data is stored only on the user's computer. GoatGramps connects
to the internet only for features the user starts or turns on, such as:

* searching WikiTree or the U.S. National Archives (NARA) Catalog from the
  GWizard merge tools, and downloading the records the user chooses;
* FamilySearch features;
* map tiles in the Geography views;
* checking for and installing addons from the Addon Manager (the automatic
  update check can be turned off in Preferences);
* opening web links in the user's browser.

No telemetry, analytics or usage data is collected.

Reporting a problem
-------------------

To report a signed GoatGramps binary that you believe is malicious, or any
breach of this policy, open an issue at
<https://github.com/ghcaveman/gramps/issues>.

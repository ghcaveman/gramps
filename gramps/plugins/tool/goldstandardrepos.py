#
# Gramps - a GTK+/GNOME based genealogy program
#
# Copyright (C) 2026  Kevin White
#
# This program is free software; you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation; either version 2 of the License, or
# (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License along
# with this program; if not, write to the Free Software Foundation, Inc.,
# 51 Franklin Street, Fifth Floor, Boston, MA 02110-1301 USA.
#

"""Gold-standard genealogy repositories for auto-population mapping."""

# -------------------------------------------------------------------------
#
# Standard Python modules
#
# -------------------------------------------------------------------------
from __future__ import annotations

# -------------------------------------------------------------------------
#
# Gramps modules
#
# -------------------------------------------------------------------------
from gramps.gen.const import GRAMPS_LOCALE as glocale

_ = glocale.translation.gettext


# ------------------------------------------------------------
#
# GoldStandardRepositories
#
# ------------------------------------------------------------
class GoldStandardRepositories:
    """Catalog of gold-standard genealogy repository definitions."""

    GENEALOGY_REPOSITORIES: list[dict[str, str]] = [
        {
            "name": "FamilySearch",
            "type": "Web site",
            "url": "https://www.familysearch.org",
            "address": "Family History Library, 35 N West Temple St, Salt Lake City, UT 84150, USA",
            "notes": _(
                "Free global database managed by the Family History Department of the LDS Church. Features digitized microfilms and a collaborative tree."
            ),
        },
        {
            "name": "Ancestry.com",
            "type": "Web site",
            "url": "https://www.ancestry.com",
            "address": "Ancestry Operations Inc., 1300 W Traverse Pkwy, Lehi, UT 84043, USA",
            "notes": _(
                "Commercial genealogy giant. Hosts the largest collection of historical records, user trees, and DNA testing databases."
            ),
        },
        {
            "name": "MyHeritage",
            "type": "Web site",
            "url": "https://www.myheritage.com",
            "address": "MyHeritage Ltd., 30 Hasifman St., Tel Aviv, Israel",
            "notes": _(
                "Commercial database with an international focus, featuring robust European historical records and family tree networks."
            ),
        },
        {
            "name": "Findmypast",
            "type": "Web site",
            "url": "https://www.findmypast.com",
            "address": "Findmypast, 185 Fleet Street, London, EC4A 2HS, UK",
            "notes": _(
                "Commercial database specializing extensively in British, Irish, Welsh, and Commonwealth historical records."
            ),
        },
        {
            "name": "Geneanet",
            "type": "Web site",
            "url": "https://www.geneanet.org",
            "address": "Geneanet, 165 bis rue de Vaugirard, 75015 Paris, France",
            "notes": _(
                "Community-driven European family tree network and historical database with strong coverage of France and continental Europe."
            ),
        },
        {
            "name": "National Archives and Records Administration (NARA)",
            "type": "Archive",
            "url": "https://www.archives.gov",
            "address": "National Archives Building, 700 Pennsylvania Ave NW, Washington, DC 20408, USA",
            "notes": _(
                "Official repository for US federal records, including census schedules, military service/pension records, land patents, and passenger lists."
            ),
        },
        {
            "name": "Library and Archives Canada (LAC)",
            "type": "Archive",
            "url": "https://library-archives.canada.ca",
            "address": "395 Wellington St, Ottawa, ON K1A 0N4, Canada",
            "notes": _(
                "Official repository for Canadian heritage records, holding federal censuses, military personnel service files, and immigration manifests."
            ),
        },
        {
            "name": "The National Archives, UK (TNA)",
            "type": "Archive",
            "url": "https://www.nationalarchives.gov.uk",
            "address": "Kew, Richmond, Surrey, TW9 4DU, UK",
            "notes": _(
                "Official government archive for Great Britain and the UK, holding records ranging from medieval rolls to modern civil service assets."
            ),
        },
        {
            "name": "National Records of Scotland (NRS)",
            "type": "Archive",
            "url": "https://www.nrscotland.gov.uk",
            "address": "HM General Register House, 2 Princes St, Edinburgh, EH1 3YY, UK",
            "notes": _(
                "Main Scottish repository housing statutory registers of births, marriages, and deaths, old parish records, and census books."
            ),
        },
        {
            "name": "National Archives of Australia (NAA)",
            "type": "Archive",
            "url": "https://www.naa.gov.au",
            "address": "Kings Avenue, Parkes, ACT 2600, Australia",
            "notes": _(
                "Official repository for Australian Commonwealth records, key for post-federation defense service, immigration, and naturalization."
            ),
        },
        {
            "name": "ScotlandsPeople",
            "type": "Web site",
            "url": "https://www.scotlandspeople.gov.uk",
            "address": "NRS, 2 Princes St, Edinburgh, EH1 3YY, UK",
            "notes": _(
                "Official pay-per-view web portal managed by the National Records of Scotland for statutory registers, church records, and wills."
            ),
        },
        {
            "name": "Irish Genealogy Portal",
            "type": "Web site",
            "url": "https://www.irishgenealogy.ie",
            "address": "Department of Tourism, Culture, Arts, Gaeltacht, Sport and Media, Dublin, Ireland",
            "notes": _(
                "Free, official government website providing access to digital images of Irish civil registration indexes and historical church registers."
            ),
        },
        {
            "name": "National Library of Ireland (NLI)",
            "type": "Library",
            "url": "https://www.nli.ie",
            "address": "Kildare St, Dublin 2, D02 P638, Ireland",
            "notes": _(
                "National library providing free online digital image access to historical Catholic parish registers spanning the island of Ireland."
            ),
        },
        {
            "name": "WieWasWie",
            "type": "Web site",
            "url": "https://www.wiewaswie.nl",
            "address": "Centrum voor Familiegeschiedenis (CBG), Prins Willem-Alexanderhof 22, 2595 BE The Hague, Netherlands",
            "notes": _(
                "Centralized Dutch database providing access to millions of civil registration records, church registers, and population books."
            ),
        },
        {
            "name": "ArkivDigital",
            "type": "Web site",
            "url": "https://www.arkivdigital.net",
            "address": "ArkivDigital AD AB, Södra Portgatan 19, 283 50 Lönsboda, Sweden",
            "notes": _(
                "Commercial subscription provider offering high-resolution color imagery of Swedish church books, estate inventories, and court records."
            ),
        },
        {
            "name": "Matricula Online",
            "type": "Web site",
            "url": "https://data.matricula-online.eu",
            "address": "Diocesan Archives of St. Pölten, Klosterneuburg / ICARUS, Vienna, Austria",
            "notes": _(
                "Free access portal for digitized church books and parish registers, covering Austria, Germany, Poland, and parts of Central Europe."
            ),
        },
        {
            "name": "Fold3",
            "type": "Web site",
            "url": "https://www.fold3.com",
            "address": "Ancestry Operations Inc., 1300 W Traverse Pkwy, Lehi, UT 84043, USA",
            "notes": _(
                "Ancestry-owned commercial niche site focusing on US, UK, and Commonwealth military histories, draft records, and pension files."
            ),
        },
        {
            "name": "Commonwealth War Graves Commission (CWGC)",
            "type": "Archive",
            "url": "https://www.cwgc.org",
            "address": "2 Marlow Road, Maidenhead, Berkshire, SL6 7CX, UK",
            "notes": _(
                "Free database documenting and honoring the graves, memorials, and final resting locations of Commonwealth forces from WWI and WWII."
            ),
        },
        {
            "name": "Forces War Records",
            "type": "Web site",
            "url": "https://www.forces-war-records.co.uk",
            "address": "Findmypast, 185 Fleet Street, London, EC4A 2HS, UK",
            "notes": _(
                "Specialist subscription site providing British military service records and rosters spanning over three centuries."
            ),
        },
        {
            "name": "Find a Grave",
            "type": "Web site",
            "url": "https://www.findagrave.com",
            "address": "Ancestry Operations Inc., 1300 W Traverse Pkwy, Lehi, UT 84043, USA",
            "notes": _(
                "Free, crowdsourced virtual cemetery database mapping millions of global headstone photos, inscriptions, and memorial notes."
            ),
        },
        {
            "name": "BillionGraves",
            "type": "Web site",
            "url": "https://www.billiongraves.com",
            "address": "BillionGraves LLC, 2087 E 3900 S, Salt Lake City, UT 84124, USA",
            "notes": _(
                "Crowdsourced database capturing GPS-tagged headstone images and transcription records mapped to exact cemetery plots globally."
            ),
        },
        {
            "name": "Interment.net",
            "type": "Web site",
            "url": "https://www.interment.net",
            "address": "Clear Digital Media, Inc., P.O. Box 486, Colton, CA 92324, USA",
            "notes": _(
                "Free resource containing thousands of independent cemetery burial transcriptions collected from public archives and volunteers."
            ),
        },
        {
            "name": "Library of Congress, Chronicling America",
            "type": "Library",
            "url": "https://chroniclingamerica.loc.gov",
            "address": "101 Independence Ave SE, Washington, DC 20540, USA",
            "notes": _(
                "Free digital repository of historical American newspapers from 1770 to 1963, maintained jointly with the National Endowment for the Humanities."
            ),
        },
        {
            "name": "Newspapers.com",
            "type": "Web site",
            "url": "https://www.newspapers.com",
            "address": "Ancestry Operations Inc., 1300 W Traverse Pkwy, Lehi, UT 84043, USA",
            "notes": _(
                "Largest commercial digital subscription archive of historical newspapers, featuring millions of pages globally from the 1700s forward."
            ),
        },
        {
            "name": "National Library of Australia, Trove",
            "type": "Library",
            "url": "https://trove.nla.gov.au",
            "address": "Parkes Place, Canberra ACT 2600, Australia",
            "notes": _(
                "Free digital database aggregator providing comprehensive text-searchable historical Australian newspapers, gazettes, diaries, and books."
            ),
        },
        {
            "name": "Internet Archive",
            "type": "Library",
            "url": "https://archive.org",
            "address": "300 Funston Ave, San Francisco, CA 94118, USA",
            "notes": _(
                "Non-profit digital library containing millions of public domain texts, digitized county histories, local family genealogies, and city directories."
            ),
        },
        {
            "name": "Google Books",
            "type": "Web site",
            "url": "https://books.google.com",
            "address": "Google LLC, 1600 Amphitheatre Pkwy, Mountain View, CA 94043, USA",
            "notes": _(
                "Global book indexing search engine containing full out-of-print digital views of early 19th and 20th-century family histories and town bios."
            ),
        },
    ]

    @classmethod
    def get_all(cls) -> list[dict[str, str]]:
        """Return all gold-standard repository definitions."""
        return [dict(entry) for entry in cls.GENEALOGY_REPOSITORIES]

    @classmethod
    def get_names(cls) -> list[str]:
        """Return the names of all gold-standard repositories."""
        return [entry["name"] for entry in cls.GENEALOGY_REPOSITORIES]

    @classmethod
    def get_by_name(cls, name: str) -> dict[str, str] | None:
        """Return the gold-standard entry matching a name, or None."""
        for entry in cls.GENEALOGY_REPOSITORIES:
            if entry["name"] == name:
                return dict(entry)
        return None

    @classmethod
    def get_display_label(cls, name: str) -> str:
        """Return the dropdown label showing description and URL."""
        entry = cls.get_by_name(name)
        if entry is None:
            return name
        description = entry["notes"]
        # Keep only the first sentence so the dropdown stays compact.
        if "." in description:
            description = description.split(".", 1)[0] + "."
        return f"{entry['name']} -- {description} [{entry['url']}]"

    @classmethod
    def as_dict(cls) -> dict[str, dict[str, str]]:
        """Return the catalog keyed by repository name."""
        return {entry["name"]: dict(entry) for entry in cls.GENEALOGY_REPOSITORIES}

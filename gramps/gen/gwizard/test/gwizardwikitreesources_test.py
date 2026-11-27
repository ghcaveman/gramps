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

"""
Tests for how WikiTree biography sources become Sources and Citations:
titles and authors, page numbers, web addresses, repositories, citation
dates, and reuse of the repositories and sources already in the tree.
"""

# -------------------------------------------------------------------------
#
# Standard Python modules
#
# -------------------------------------------------------------------------
from __future__ import annotations
import unittest
from typing import Any

# -------------------------------------------------------------------------
#
# Gramps modules
#
# -------------------------------------------------------------------------
from gramps.gen.db.base import DbWriteBase
from gramps.gen.db.txn import DbTxn
from gramps.gen.db.utils import make_database
from gramps.gen.lib import (
    Date,
    Name,
    Person,
    RepoRef,
    Repository,
    RepositoryType,
    Source,
    Surname,
)

# -------------------------------------------------------------------------
#
# Local imports
#
# -------------------------------------------------------------------------
from ..gwizardwikitree import (
    _BIRTH_WORDS_RE,
    _DEATH_WORDS_RE,
    WIKITREE_REPOSITORY_NAME,
    WIKITREE_SOURCE_TITLE,
    WikiTreeGWizard,
    describe_bio_source,
    extract_page,
    ref_sentence,
    source_fits_year,
    extract_url,
    split_author,
)

CENSUS = (
    '"United States Census, 1790," database with images, FamilySearch '
    "(https://familysearch.org/ark:/61903/1:1:ABCD-XYZ : accessed 16 November "
    "2021), Thomas Baker, Harford, Maryland, United States; citing p. 289, "
    "NARA microfilm publication M637, roll 3."
)
BOOK = (
    "Miller, John A. Carter, R. Paul. A Family History: The Bakers of "
    "Harford. Example Press, 2010. Pgs. xii & 40-42 "
    "[https://books.google.com/books?id=abc123&source=gbs_navlinks_s]"
)
FS_LINK = "https://www.familysearch.org/tree/person/details/ABCD-123;"


class DescribeBioSourceTest(unittest.TestCase):
    """The fields worked out from one biography source text."""

    def test_quoted_collection_title(self) -> None:
        info = describe_bio_source(CENSUS, CENSUS)
        self.assertEqual(info["title"], "United States Census, 1790")
        self.assertEqual(info["page"], "p. 289")
        self.assertEqual(info["repository"], "FamilySearch")
        self.assertEqual(info["accessed"], "16 November 2021")

    def test_author_list_and_book_title(self) -> None:
        cleaned = WikiTreeGWizard.clean_source_text(BOOK)
        info = describe_bio_source(cleaned, BOOK)
        self.assertEqual(info["author"], "Miller, John A. Carter, R. Paul")
        self.assertEqual(info["title"], "A Family History: The Bakers of Harford")
        self.assertEqual(info["page"], "Pgs. xii & 40-42")
        self.assertEqual(info["repository"], "Google Books")
        self.assertFalse(info["url"].endswith("]"))

    def test_initial_before_title_ends_author(self) -> None:
        author, rest = split_author("SMITH, JANE Q. The Old Mill of 1814. A Journal.")
        self.assertEqual(author, "SMITH, JANE Q.")
        self.assertTrue(rest.startswith("The Old Mill of 1814"))

    def test_two_authors_joined_by_and(self) -> None:
        author, rest = split_author("DOE, JOHN H. and ROE, ANNA. Old Roads. A Journal.")
        self.assertEqual(author, "DOE, JOHN H. and ROE, ANNA")
        self.assertTrue(rest.startswith("Old Roads"))

    def test_no_author(self) -> None:
        self.assertEqual(split_author("Parish register of births")[0], "")

    def test_familysearch_tree_link(self) -> None:
        info = describe_bio_source(FS_LINK, FS_LINK)
        self.assertEqual(info["title"], "FamilySearch Family Tree")
        self.assertEqual(info["fs_id"], "ABCD-123")
        self.assertEqual(info["url"], FS_LINK.rstrip(";"))

    def test_dar_ancestor(self) -> None:
        text = "DAR Ancestor #: A000123; Service Description: 1) PRIVATE"
        info = describe_bio_source(text, text)
        self.assertEqual(info["page"], "Ancestor #A000123")
        self.assertIn("DAR", info["repository"])
        self.assertNotIn("Service Description", info["title"])

    def test_page_forms(self) -> None:
        self.assertEqual(extract_page("Example Press, 1988. Pg. 42"), "Pg. 42")
        self.assertEqual(extract_page("record, pp. 54-55."), "pp. 54-55")
        self.assertEqual(extract_page("Register, page 12."), "page 12")
        self.assertEqual(extract_page("no page here"), "")

    def test_url_trailing_punctuation(self) -> None:
        self.assertEqual(
            extract_url("see [https://example.org/a?b=1]."), "https://example.org/a?b=1"
        )


class BioSourceLoadTest(unittest.TestCase):
    """Loading a profile reuses the tree's repositories and sources."""

    def setUp(self) -> None:
        self.db: DbWriteBase = make_database("sqlite")
        self.db.load(":memory:")
        with DbTxn("setup", self.db) as trans:
            self.fs_repo = Repository()
            self.fs_repo.set_name("FamilySearch")
            self.fs_repo.set_type(RepositoryType(RepositoryType.WEBSITE))
            self.db.add_repository(self.fs_repo, trans)
            self.wt_repo = Repository()
            self.wt_repo.set_name(WIKITREE_REPOSITORY_NAME)
            self.wt_repo.set_type(RepositoryType(RepositoryType.WEBSITE))
            self.db.add_repository(self.wt_repo, trans)
            self.fs_tree = Source()
            self.fs_tree.set_title("FamilySearch Family Tree")
            ref = RepoRef()
            ref.ref = self.fs_repo.handle
            self.fs_tree.add_repo_reference(ref)
            self.db.add_source(self.fs_tree, trans)
            self.target = Person()
            name = Name()
            name.set_first_name("Thomas")
            surname = Surname()
            surname.set_surname("Baker")
            name.add_surname(surname)
            self.target.set_primary_name(name)
            self.target.set_gender(Person.MALE)
            self.db.add_person(self.target, trans)

    def tearDown(self) -> None:
        self.db.close()

    def _load(self) -> tuple[WikiTreeGWizard, Any, Person]:
        profile = {
            "Id": 101,
            "Name": "Baker-101",
            "FirstName": "Thomas",
            "LastNameBirth": "Baker",
            "Gender": "Male",
            "BirthDate": "1753-03-10",
            "Bio": "== Biography ==\nThomas was born in 1753.<ref>%s</ref>\n"
            "He appears in a family history.<ref>%s</ref>\n"
            "<ref>%s</ref>\n== Sources ==\n<references />\n" % (CENSUS, BOOK, FS_LINK),
        }
        gw = WikiTreeGWizard(self.db)
        gw.run_step("connect", query="Baker-101", people_data=[profile])
        (person,) = gw.run_step("load")
        return gw, gw.context["source_db"], person

    def _sources(self, source_db: Any) -> dict[str, Any]:
        return {s.get_title(): s for s in source_db.iter_sources()}

    def test_repositories_and_sources_are_reused(self) -> None:
        _gw, source_db, _person = self._load()
        repos = {r.get_name(): r.handle for r in source_db.iter_repositories()}
        self.assertEqual(repos["FamilySearch"], self.fs_repo.handle)
        self.assertEqual(repos[WIKITREE_REPOSITORY_NAME], self.wt_repo.handle)
        sources = self._sources(source_db)
        self.assertEqual(
            sources["FamilySearch Family Tree"].handle, self.fs_tree.handle
        )
        self.assertIn(WIKITREE_SOURCE_TITLE, sources)
        census = sources["United States Census, 1790"]
        (census_ref,) = census.get_reporef_list()
        self.assertEqual(census_ref.ref, self.fs_repo.handle)

    def test_citations_have_pages_and_accessed_dates(self) -> None:
        _gw, source_db, person = self._load()
        sources = self._sources(source_db)
        by_source = {}
        for handle in person.get_citation_list():
            citation = source_db.get_citation_from_handle(handle)
            by_source[citation.get_reference_handle()] = citation
        census = by_source[sources["United States Census, 1790"].handle]
        self.assertEqual(census.get_page(), "p. 289")
        self.assertEqual(census.get_date_object().get_year(), 2021)
        book = by_source[sources["A Family History: The Bakers of Harford"].handle]
        self.assertEqual(book.get_page(), "Pgs. xii & 40-42")
        # No accessed date given, so no date (not the day of the merge).
        self.assertTrue(book.get_date_object().is_empty())
        tree = by_source[self.fs_tree.handle]
        self.assertEqual(tree.get_page(), "entry for Thomas Baker, person ID ABCD-123")

    def test_familysearch_id_is_stored(self) -> None:
        _gw, _source_db, person = self._load()
        values = [
            a.get_value()
            for a in person.get_attribute_list()
            if str(a.get_type()) == "_FSFTID"
        ]
        self.assertEqual(values, ["ABCD-123"])

    def test_merge_adds_no_duplicate_repositories_or_sources(self) -> None:
        gw, source_db, person = self._load()
        repos_before = self.db.get_number_of_repositories()
        self.assertTrue(
            gw.run_step(
                "apply",
                source_person_handle=person.handle,
                target_person_handle=self.target.handle,
                resolutions={"person_sources": "source"},
            )
        )
        names = sorted(r.get_name() for r in self.db.iter_repositories())
        # Only Google Books is new; FamilySearch and WikiTree are reused.
        self.assertEqual(self.db.get_number_of_repositories(), repos_before + 1)
        self.assertEqual(names.count("FamilySearch"), 1)
        self.assertEqual(names.count(WIKITREE_REPOSITORY_NAME), 1)
        titles = [s.get_title() for s in self.db.iter_sources()]
        self.assertEqual(titles.count("FamilySearch Family Tree"), 1)

        # A second merge of the same profile adds no repositories either.
        gw2, _db2, person2 = self._load()
        gw2.run_step(
            "apply",
            source_person_handle=person2.handle,
            target_person_handle=self.target.handle,
            resolutions={"person_sources": "source"},
        )
        self.assertEqual(self.db.get_number_of_repositories(), repos_before + 1)
        titles = [s.get_title() for s in self.db.iter_sources()]
        self.assertEqual(titles.count(WIKITREE_SOURCE_TITLE), 1)


CENSUS_1820 = (
    '"United States Census, 1820," database with images, FamilySearch '
    "(https://familysearch.org/ark:/61903/1:1:EFGH-XYZ : accessed 25 December "
    "2021), Thomas Baker, Baltimore Ward 4, Baltimore, Maryland, United States; "
    "citing p. 187, NARA microfilm publication M33, roll 42."
)
BAPTISMS = (
    '"Pennsylvania, Church Baptisms, 1709-1950," database, FamilySearch '
    "(https://familysearch.org/ark:/61903/1:1:IJKL-XYZ : accessed 3 March 2022), "
    "Thomas Baker, 1753."
)
GRAVE = (
    "Find a Grave, database and images (https://www.findagrave.com/memorial/1 "
    ": accessed 4 April 2022), memorial page for Thomas Baker (1753-1838)."
)


class RefSentenceTest(unittest.TestCase):
    """The sentence a reference footnotes."""

    def test_only_the_sentence_before_the_reference(self) -> None:
        bio = (
            "Thomas was born in 1753.<ref>a</ref>\n\n=== Research Notes ===\n"
            "The 1820 Census lists him in Baltimore.<ref>b</ref> More text."
        )
        self.assertEqual(
            ref_sentence(bio, bio.index("<ref>b")),
            "The 1820 Census lists him in Baltimore",
        )
        self.assertEqual(
            ref_sentence(bio, bio.index("<ref>a")), "Thomas was born in 1753"
        )

    def test_an_abbreviation_does_not_cut_the_sentence(self) -> None:
        bio = "He married Mary.\nHe was born in Bucks Co. Pa.<ref>a</ref>"
        self.assertEqual(
            ref_sentence(bio, bio.index("<ref>")), "He was born in Bucks Co. Pa"
        )

    def test_other_references_are_left_out(self) -> None:
        bio = 'He was born in 1753.<ref name="x">a</ref><ref>b</ref>'
        self.assertEqual(ref_sentence(bio, bio.index("<ref>b")), "He was born in 1753")


class SourceYearTest(unittest.TestCase):
    """A source's own year decides whether it can be about an event."""

    def test_a_census_far_from_the_birth(self) -> None:
        self.assertFalse(source_fits_year("United States Census, 1820", 1753))

    def test_a_span_that_holds_the_year(self) -> None:
        self.assertTrue(
            source_fits_year("Pennsylvania, Church Baptisms, 1709-1950", 1753)
        )

    def test_a_year_close_to_the_event(self) -> None:
        self.assertTrue(source_fits_year("Births, 1755", 1753))

    def test_no_year_on_either_side(self) -> None:
        self.assertTrue(source_fits_year("Find a Grave", 1753))
        self.assertTrue(source_fits_year("United States Census, 1820", 0))


class EventWordsTest(unittest.TestCase):
    """Words that make a reference a source for the birth or the death."""

    def test_will_is_a_word_not_part_of_a_name(self) -> None:
        self.assertIsNone(_DEATH_WORDS_RE.search("his son william was a smith"))
        self.assertIsNotNone(_DEATH_WORDS_RE.search("named in his will"))

    def test_word_forms(self) -> None:
        self.assertIsNotNone(_BIRTH_WORDS_RE.search("he was christened in 1753"))
        self.assertIsNotNone(_DEATH_WORDS_RE.search("he was buried at the church"))
        self.assertIsNone(_BIRTH_WORDS_RE.search("the reborn church"))


class BioSourceEventTest(unittest.TestCase):
    """Which events a biography's references are attached to."""

    def setUp(self) -> None:
        self.db: DbWriteBase = make_database("sqlite")
        self.db.load(":memory:")

    def tearDown(self) -> None:
        self.db.close()

    def _event_sources(self, bio: str) -> dict[str, list[str]]:
        """Load the profile; return source titles by event type, and "person"."""
        profile = {
            "Id": 101,
            "Name": "Baker-101",
            "FirstName": "Thomas",
            "LastNameAtBirth": "Baker",
            "Gender": "Male",
            "BirthDate": "1753-03-10",
            "DeathDate": "1838-00-00",
            "Bio": bio,
        }
        gw = WikiTreeGWizard(self.db)
        gw.run_step("connect", query="Baker-101", people_data=[profile])
        (person,) = gw.run_step("load")
        source_db = gw.context["source_db"]

        def titles(citations: list[str]) -> list[str]:
            found = []
            for handle in citations:
                citation = source_db.get_citation_from_handle(handle)
                source = source_db.get_source_from_handle(
                    citation.get_reference_handle()
                )
                found.append(source.get_title())
            return sorted(found)

        result = {"person": titles(person.get_citation_list())}
        for ref in person.get_event_ref_list():
            event = source_db.get_event_from_handle(ref.ref)
            result[str(event.get_type())] = titles(event.get_citation_list())
        return result

    def test_census_after_a_birth_sentence_stays_off_the_birth(self) -> None:
        """The 1820 census follows "born in 1753" but is not a birth record."""
        found = self._event_sources(
            "== Biography ==\nThomas was born in 1753.<ref>%s</ref>\n\n"
            "=== Research Notes ===\nThe 1820 Census lists Thomas in "
            "Baltimore with a large family.<ref>%s</ref>\n"
            "He died in 1838 and was buried in Baltimore.<ref>%s</ref>\n"
            "== Sources ==\n<references />\n" % (BAPTISMS, CENSUS_1820, GRAVE)
        )
        self.assertIn("Pennsylvania, Church Baptisms, 1709-1950", found["Birth"])
        self.assertNotIn("United States Census, 1820", found["Birth"])
        self.assertNotIn("United States Census, 1820", found["Death"])
        self.assertIn("United States Census, 1820", found["person"])
        self.assertIn("Find a Grave", " ".join(found["Death"]))

    def test_a_birth_sentence_citing_a_census_keeps_it_off_the_birth(self) -> None:
        """The year check still holds when the sentence speaks of the birth."""
        found = self._event_sources(
            "Thomas was born about 1753.<ref>%s</ref>\n" % CENSUS_1820
        )
        self.assertNotIn("United States Census, 1820", found["Birth"])
        self.assertIn("United States Census, 1820", found["person"])


if __name__ == "__main__":
    unittest.main()

"""Tests for gwizardwikitreeprovenance (run with: python -m unittest)."""

import os
import shutil
import tempfile
import unittest

from gramps.gen.db import DbTxn
from gramps.gen.db.utils import make_database
from gramps.gen.lib import Date, Event, Name, Person, Source, Citation, Surname

import gwizardwikitreeprovenance as prov


class ProvenanceTest(unittest.TestCase):
    """Run against a real, throw-away SQLite Gramps database."""

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.db = make_database("sqlite")
        path = os.path.join(self.tmp, "t")
        os.makedirs(path)
        self.db.load(path)
        self.person = self._add_person("Kevin Winters", "White")

    def tearDown(self):
        self.db.close()
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _add_person(self, given, surname):
        person = Person()
        name = Name()
        name.set_first_name(given)
        sn = Surname()
        sn.set_surname(surname)
        name.add_surname(sn)
        person.set_primary_name(name)
        with DbTxn("add", self.db) as trans:
            self.db.add_person(person, trans)
        return self.db.get_person_from_handle(person.handle)

    def _ensure(self, person=None, pid="White-94900"):
        person = self.db.get_person_from_handle((person or self.person).handle)
        with DbTxn("wt", self.db) as trans:
            return prov.ensure_provenance(self.db, trans, person, pid)

    def test_first_run_creates_everything(self):
        res = self._ensure()
        self.assertEqual(
            set(res.created),
            {
                "repository",
                "source",
                "citation",
                "attribute",
                "link",
                "person citation",
            },
        )
        person = self.db.get_person_from_handle(self.person.handle)
        self.assertEqual(
            [
                a.get_value()
                for a in person.get_attribute_list()
                if str(a.get_type()) == "WikiTree ID"
            ],
            ["White-94900"],
        )
        self.assertEqual(
            [u.get_path() for u in person.get_url_list()],
            ["https://www.wikitree.com/wiki/White-94900"],
        )
        self.assertEqual(len(person.get_citation_list()), 1)

    def test_idempotent(self):
        self._ensure()
        res = self._ensure()
        self.assertEqual(res.created, [])
        self.assertFalse(res.changed)
        self.assertEqual(self.db.get_number_of_sources(), 1)
        self.assertEqual(self.db.get_number_of_repositories(), 1)
        self.assertEqual(self.db.get_number_of_citations(), 1)
        person = self.db.get_person_from_handle(self.person.handle)
        self.assertEqual(len(person.get_attribute_list()), 1)
        self.assertEqual(len(person.get_url_list()), 1)
        self.assertEqual(len(person.get_citation_list()), 1)

    def test_shared_source_across_profiles(self):
        other = self._add_person("Kimberly", "White")
        self._ensure()
        self._ensure(other, "White-12345")
        self.assertEqual(self.db.get_number_of_sources(), 1)
        self.assertEqual(self.db.get_number_of_repositories(), 1)
        self.assertEqual(self.db.get_number_of_citations(), 2)

    def test_citation_has_retrieval_date_and_bare_page(self):
        res = self._ensure()
        citation = self.db.get_citation_from_handle(res.citation.handle)
        self.assertEqual(citation.get_page(), "White-94900")
        self.assertFalse(citation.get_date_object().is_empty())

    def test_conflicting_id_is_reported_not_overwritten(self):
        self._ensure()
        res = self._ensure(pid="White-99999")
        self.assertEqual(len(res.conflicts), 1)
        person = self.db.get_person_from_handle(self.person.handle)
        values = [a.get_value() for a in person.get_attribute_list()]
        self.assertEqual(values, ["White-94900"])

    def test_existing_link_variants_not_duplicated(self):
        from gramps.gen.lib import Url, UrlType

        url = Url()
        url.set_path("http://wikitree.com/wiki/White-94900/")
        url.set_type(UrlType.WEB_HOME)
        person = self.db.get_person_from_handle(self.person.handle)
        person.add_url(url)
        with DbTxn("u", self.db) as trans:
            self.db.commit_person(person, trans)
        self._ensure()
        person = self.db.get_person_from_handle(self.person.handle)
        self.assertEqual(len(person.get_url_list()), 1)

    def test_bad_id_rejected_before_any_write(self):
        with self.assertRaises(ValueError):
            self._ensure(pid="not an id")
        self.assertEqual(self.db.get_number_of_sources(), 0)

    def test_normalize_forms(self):
        for raw in (
            "White-94900",
            "WikiTree: White-94900",
            "https://www.wikitree.com/wiki/White-94900",
            "http://wikitree.com/wiki/White-94900?x=1",
        ):
            self.assertEqual(prov.normalize_profile_id(raw), "White-94900")
        self.assertEqual(prov.normalize_profile_id("O'Brien-12"), "O'Brien-12")

    def test_event_level_citation(self):
        res = self._ensure()
        event = Event()
        with DbTxn("e", self.db) as trans:
            self.db.add_event(event, trans)
        self.assertTrue(prov.cite(event, res.citation))
        self.assertFalse(prov.cite(event, res.citation))
        self.assertEqual(event.get_citation_list(), [res.citation.handle])

    def test_dates(self):
        d = prov.wikitree_date_to_gramps("1965-11-21", "certain")
        self.assertEqual(d.get_dmy(), (21, 11, 1965))
        self.assertEqual(d.get_modifier(), Date.MOD_NONE)
        d = prov.wikitree_date_to_gramps("1965-00-00", "guess")
        self.assertEqual(d.get_dmy(), (0, 0, 1965))
        self.assertEqual(d.get_modifier(), Date.MOD_ABOUT)
        d = prov.wikitree_date_to_gramps("1965-11-00", "before")
        self.assertEqual(d.get_dmy(), (0, 11, 1965))
        self.assertEqual(d.get_modifier(), Date.MOD_BEFORE)
        self.assertEqual(
            prov.wikitree_date_to_gramps("after", "").get_modifier(), Date.MOD_NONE
        )
        self.assertTrue(prov.wikitree_date_to_gramps("0000-00-00").is_empty())
        self.assertTrue(prov.wikitree_date_to_gramps(None).is_empty())
        self.assertEqual(
            prov.wikitree_date_to_gramps("1900-01-01", "after").get_modifier(),
            Date.MOD_AFTER,
        )

    def test_migrate_legacy_per_profile_sources(self):
        # Rebuild what the first version produced.
        with DbTxn("r", self.db) as trans:
            repo = prov.find_or_create_repository(self.db, trans)
        legacy_handles = []
        for pid in ("White-94900", "White-12345"):
            with DbTxn("legacy", self.db) as trans:
                src = Source()
                src.set_title(f"WikiTree - {pid}")
                from gramps.gen.lib import RepoRef

                rr = RepoRef()
                rr.set_reference_handle(repo.handle)
                src.add_repo_reference(rr)
                self.db.add_source(src, trans)
                cit = Citation()
                cit.set_reference_handle(src.handle)
                cit.set_page(f"WikiTree: {pid}")
                self.db.add_citation(cit, trans)
                legacy_handles.append((src.handle, cit.handle))
        with DbTxn("m", self.db) as trans:
            folded = prov.migrate_legacy_sources(self.db, trans)
        self.assertEqual(folded, 2)
        titles = [s.get_title() for s in self.db.iter_sources()]
        self.assertEqual(titles, ["WikiTree"])
        pages = sorted(c.get_page() for c in self.db.iter_citations())
        self.assertEqual(pages, ["White-12345", "White-94900"])
        shared = next(self.db.iter_sources())
        for _src, cit in legacy_handles:
            self.assertEqual(
                self.db.get_citation_from_handle(cit).get_reference_handle(),
                shared.handle,
            )
        # Second run is a no-op.
        with DbTxn("m2", self.db) as trans:
            self.assertEqual(prov.migrate_legacy_sources(self.db, trans), 0)


if __name__ == "__main__":
    unittest.main()

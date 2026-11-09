import stub, os, itertools, tempfile, pathlib

stub.sys.modules["gramps.gen.utils.db"].get_birth_or_fallback = lambda db, p: None
stub.sys.modules["gramps.gen.utils.db"].get_death_or_fallback = lambda db, p: None
import gwizardmediafix as m
import gwizard_common as gc


class Date:
    def __init__(s, y=0):
        s.y = y

    def get_year(s):
        return s.y

    def is_empty(s):
        return s.y == 0


class Name:
    def __init__(s, sur, giv):
        s.s, s.g = sur, giv

    def get_surname(s):
        return s.s

    def get_first_name(s):
        return s.g


class Person:
    def __init__(s, h, gid, sur, giv):
        s.h, s.gid, s.n = h, gid, Name(sur, giv)

    def get_handle(s):
        return s.h

    def get_gramps_id(s):
        return s.gid

    def get_primary_name(s):
        return s.n

    def get_event_ref_list(s):
        return []

    def get_birth_ref(s):
        return None


class Event:
    def __init__(s, h, gid, typ, y):
        s.h, s.gid, s.t, s.d = h, gid, typ, Date(y)

    def get_handle(s):
        return s.h

    def get_gramps_id(s):
        return s.gid

    def get_type(s):
        return s.t

    def get_date_object(s):
        return s.d


class Source:
    def get_title(s):
        return "familysearch.org"

    def get_gramps_id(s):
        return "S1"


class Citation:
    def __init__(s, h, gid):
        s.h, s.gid = h, gid

    def get_handle(s):
        return s.h

    def get_gramps_id(s):
        return s.gid

    def get_reference_handle(s):
        return "src"

    def get_page(s):
        return ""


class Media:
    def __init__(s, h, gid, desc, path, notes=()):
        s.h, s.gid, s.desc, s.path, s.notes = h, gid, desc, path, list(notes)

    def get_handle(s):
        return s.h

    def get_gramps_id(s):
        return s.gid

    def get_description(s):
        return s.desc

    def get_path(s):
        return s.path

    def set_path(s, p):
        s.path = p

    def get_date_object(s):
        return Date()

    def get_note_list(s):
        return s.notes

    def remove_note(s, h):
        s.notes.remove(h)

    def get_attribute_list(s):
        return []

    def get_tag_list(s):
        return []

    def get_citation_list(s):
        return []


class Note:
    def __init__(s, h, gid, text):
        s.h, s.gid, s.t = h, gid, text

    def get(s):
        return s.t

    def get_gramps_id(s):
        return s.gid


class DB:
    def __init__(s, mp, medias, back, **objs):
        s.mp = mp
        s.medias = {x.h: x for x in medias}
        s.back = back
        s.o = objs
        s.commits = 0

    def get_mediapath(s):
        return s.mp

    def iter_media(s):
        return iter(list(s.medias.values()))

    def get_media_from_handle(s, h):
        return s.medias.get(h)

    def commit_media(s, mm, t):
        s.commits += 1

    def remove_media(s, h, t):
        del s.medias[h]

    def find_backlink_handles(s, h, include_classes=None):
        r = list(s.back.get(h, []))
        return [b for b in r if not include_classes or b[0] in include_classes]

    def get_person_from_handle(s, h):
        return s.o.get("P", {}).get(h)

    def get_event_from_handle(s, h):
        return s.o.get("E", {}).get(h)

    def get_citation_from_handle(s, h):
        return s.o.get("C", {}).get(h)

    def get_source_from_handle(s, h):
        return Source()

    def get_family_from_handle(s, h):
        return None

    def get_note_from_handle(s, h):
        return s.o.get("N", {}).get(h)

    def remove_note(s, h, t):
        s.o["N"].pop(h)


P = {
    "p450": Person("p450", "I00450", "Fuller", "Harry Jay"),
    "pE": Person("pE", "M25S-XWS", "Fuller", "Edward C"),
    "pL": Person("pL", "I00054", "Fuller", "Lilly"),
    "p451": Person("p451", "I00451", "Devault", "Nettie"),
}
E_ = {"e1": Event("e1", "E1", "Census", 1910), "e2": Event("e2", "E2", "Birth", 1856)}
C = {
    "c1": Citation("c1", "C00859"),
    "c2": Citation("c2", "C01169"),
    "c3": Citation("c3", "C00109"),
}
base_back = {
    "c1": [("Event", "e1")],
    "e1": [("Person", "p450")],
    "c2": [("Event", "e2")],
    "e2": [("Person", "pE")],
    "c3": [("Person", "pL")],
    "m3": [("Person", "p451")],
}

# ---- 5. deterministic + description-aware ref_id, whatever the backlink order
refs = set()
for perm in itertools.permutations(
    [("Citation", "c1"), ("Citation", "c2"), ("Citation", "c3")]
):
    back = dict(base_back)
    back["m0"] = list(perm)
    med = Media(
        "m0",
        "O00000",
        "Fuller, Harry Jay - 1910Census",
        "/x/Fuller, Harry Jay - 1910Census.jpg",
    )
    db = DB("/b", [med], back, P=P, E=E_, C=C)
    ctx = m.resolve_media_reference_context(db, med)
    refs.add((ctx["ref_id"], ctx["surname"], ctx["given"]))
print("ref_id over all 6 backlink orders:", refs)
assert refs == {("I00450", "Fuller", "Harry Jay")}
# no name in description -> still stable across orders
refs = set()
for perm in itertools.permutations(
    [("Citation", "c1"), ("Citation", "c2"), ("Citation", "c3")]
):
    back = dict(base_back)
    back["m0"] = list(perm)
    med = Media("m0", "O00000", "scan", "/x/scan.jpg")
    db = DB("/b", [med], back, P=P, E=E_, C=C)
    refs.add(m.resolve_media_reference_context(db, med)["ref_id"])
print("undescribed media, ref_id stable:", refs)
assert len(refs) == 1

# ---- 4. name mismatch
tmp = pathlib.Path(tempfile.mkdtemp())
base = tmp / "Tree"
(base / "sub").mkdir(parents=True)
other = tmp / "old"
other.mkdir()
(other / "Fuller, Harry Jay - 1910Census.jpg").write_text("HARRY CENSUS")
(base / "sub" / "Duvault, Nettie - 1900Census.jpg").write_text("NETTIE CENSUS")
m0 = Media(
    "m0",
    "O00000",
    "Fuller, Harry Jay - 1910Census",
    str(other / "Fuller, Harry Jay - 1910Census.jpg"),
)
m3 = Media(
    "m3", "O00003", "Duvault, Nettie - 1900Census", "Duvault, Nettie - 1900Census.jpg"
)  # missing at top level
m4 = Media(
    "m4", "O00004", "Orphan - 1900Census", str(other / "orphan.jpg")
)  # unreferenced, bare
(other / "orphan.jpg").write_text("o")
m5 = Media("m5", "O00005", "Kept - note", str(other / "kept.jpg"), notes=["n1"])
(other / "kept.jpg").write_text("k")
back = dict(base_back)
back["m0"] = [("Citation", "c3"), ("Citation", "c1"), ("Citation", "c2")]
notes = {
    "n1": Note(
        "n1",
        "N1",
        "Records not imported into OBJE (multi-media object) Could not import C:\\\\x",
    )
}
db = DB(str(base), [m0, m3, m4, m5], back, P=P, E=E_, C=C, N=notes)
mm = m.find_name_mismatches(db)
print("mismatches:", mm)
assert len(mm) == 1 and mm[0][0] == "O00003" and mm[0][4] == "probable spelling variant"

# ---- 1. dry-run plan (must not change anything)
snap = [(x.h, x.path) for x in db.medias.values()]
plan = m.build_accept_all_plan(db, str(base), True)
assert (
    snap == [(x.h, x.path) for x in db.medias.values()]
    and db.commits == 0
    and len(db.medias) == 4
), "plan mutated state!"
print(m.format_plan(plan))
assert [f[0] for f in plan["find"]] == ["O00003"] and plan["find"][0][
    2
] == "sub/Duvault, Nettie - 1900Census.jpg"
assert [d[0] for d in plan["delete"]] == ["O00004"] and [
    k[0] for k in plan["keep_unref"]
] == ["O00005"]
assert {x[0] for x in plan["moves"]} == {"O00000", "O00003", "O00005"} or {
    x[0] for x in plan["moves"]
} == {"O00000", "O00003"}
print("moves:", plan["moves"])
assert any(
    x[0] == "O00000"
    and x[1].endswith("I00450_Fuller_Harry_Jay-Census-1910.jpg")
    or x[2] == "I00450_Fuller_Harry_Jay-Census-1910.jpg"
    for x in plan["moves"]
)
# no base path -> step 3 skipped
p2 = m.build_accept_all_plan(db, str(base), False)
assert p2["halted"] and not p2["moves"]

# ---- 8. {hash} token: different content -> different names, same content -> same name
(other / "a.jpg").write_text("AAA")
(other / "b.jpg").write_text("BBB")
ma = Media("ma", "O1", "Smith, J - 1900Census", str(other / "a.jpg"))
mb = Media("mb", "O2", "Smith, J - 1900Census", str(other / "b.jpg"))
dbh = DB(
    str(base),
    [ma, mb],
    {},
)
t = "{surname}_{given}-{doc_type}-{year}-{hash}.{ext}"
na = m.sanitize_standard_filename(ma.path, db=dbh, media=ma, template=t)
nb = m.sanitize_standard_filename(mb.path, db=dbh, media=mb, template=t)
print("hash names:", na, nb)
assert na != nb and na.endswith(".jpg")
assert na == m.sanitize_standard_filename(ma.path, db=dbh, media=ma, template=t)

# ---- 3. stale import notes
items = m.find_stale_import_notes(db)
print("stale notes:", items)
assert [i[1] for i in items] == ["O00005"]  # only where the file is readable
db.back["n1"] = [("Media", "m5")]
assert (
    m.remove_import_notes(db, items) == 1 and "n1" not in db.o["N"] and m5.notes == []
)
assert m.find_stale_import_notes(db) == []

# ---- 6. cache avoids recomputation
calls = []
orig = m._resolve_media_reference_context_uncached
m._resolve_media_reference_context_uncached = lambda d, x: (
    calls.append(1),
    orig(d, x),
)[1]
cache = {}
for _ in range(3):
    m.resolve_media_reference_context(db, m0, cache)
assert len(calls) == 1
print("cache: 3 lookups, 1 computation")
print("ALL NEW TESTS PASSED")

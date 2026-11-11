import gramps.plugins.tool.test.gw_stubs as gw_stubs, tempfile, logging
from gramps.gen.db.utils import make_database
from gramps.gen.db import DbTxn
from gramps.gen.lib import (
    Source,
    Citation,
    Repository,
    RepoRef,
    Note,
    NoteType,
    Address,
    Person,
    Event,
    EventRef,
    EventType,
    RepositoryType,
)
from gramps.plugins.tool import gwizardcitationfix as fix
from gramps.plugins.tool.gwizardcitationshared import note_text

logging.basicConfig(level=logging.WARNING)

db = make_database("sqlite")
db.load(tempfile.mkdtemp())


def snapshot():
    import json

    out = {}
    for name in ("source", "citation", "repository", "note"):
        it = getattr(
            db, "iter_%ss" % name if name != "repository" else "iter_repositories"
        )()
        out[name] = sorted(
            json.dumps(o.serialize(), sort_keys=True, default=str) for o in it
        )
    return out


def counts():
    return dict(
        src=db.get_number_of_sources(),
        repo=db.get_number_of_repositories(),
        cit=db.get_number_of_citations(),
        note=db.get_number_of_notes(),
    )


with DbTxn("setup", db) as t:
    # repositories mirroring the real data
    r1 = Repository()
    r1.set_name(
        "Local Government and Municipal Registries (Genoa, IT / Broward County, FL)"
    )
    a = Address()
    a.set_street(r1.get_name())
    r1.add_address(a)
    h_r1 = db.add_repository(r1, t)
    r2 = Repository()
    r2.set_name("The National Archives and Records Administration (NARA)")
    a = Address()
    a.set_street(r2.get_name())
    r2.add_address(a)
    h_r2 = db.add_repository(r2, t)

    def mk_source(title, repo=None, author="", pub=""):
        s = Source()
        s.set_title(title)
        s.set_author(author)
        s.set_publication_info(pub)
        if repo:
            rr = RepoRef()
            rr.set_reference_handle(repo)
            s.add_repo_reference(rr)
        return s

    def mk_cit(src_handle, page="", conf=2, notes=()):
        c = Citation()
        c.set_reference_handle(src_handle)
        c.set_page(page)
        c.set_confidence_level(conf)
        for n in notes:
            nn = Note()
            nn.set(n)
            nn.set_type(NoteType.CITATION)
            c.add_note(db.add_note(nn, t))
        return db.add_citation(c, t)

    # duplicate sources with conflicting text
    s1 = mk_source(
        "Pennsylvania, U.S., Marriages, 1852-1968",
        h_r2,
        author="Ancestry.com",
        pub="Provo, UT",
    )
    s2 = mk_source(
        "Pennsylvania, Marriages, 1852-1968",
        h_r2,
        author="FamilySearch",
        pub="Salt Lake City",
    )
    hs1 = db.add_source(s1, t)
    hs2 = db.add_source(s2, t)
    mk_cit(hs1, "Vol 1")
    mk_cit(hs2, "Vol 2")
    # tree source with conflated pages
    odd = mk_source(
        "Newspapers.com Obituary Index, 1800s-current (Repository: Newspapers.com, Source: Obituary Index)"
    )
    db.add_source(odd, t)
    tree = mk_source("FamilySearch Family Tree", h_r1)
    htree = db.add_source(tree, t)
    for i in range(3):
        mk_cit(
            htree,
            "(accessed 12 Jul 2026), entry for Person%d, person ID ABC-%d." % (i, i),
            conf=3,
        )
    # citation with empty page and bare URL note (should copy then drop the note)
    ssrc = mk_source("U.S., Find A Grave Index", h_r2)
    hss = db.add_source(ssrc, t)
    c_url = mk_cit(
        hss, "", 2, notes=["https://www.familysearch.org/ark:/61903/1:1:XYZ?view=index"]
    )
    # citation whose page holds URL + text while a note already holds the URL
    c_dup = mk_cit(
        hss,
        "Entry for Edward https://www.familysearch.org/ark:/61903/1:1:QQQ accessed 3 Jan 2020",
        2,
        notes=["https://www.familysearch.org/ark:/61903/1:1:QQQ"],
    )
    # filename source (user's Lois White jpg)
    jpg = mk_source("LoisWhite - PittalugaFAMILY TREE.jpg", h_r2)
    hjpg = db.add_source(jpg, t)
    mk_cit(hjpg, "")
    # notes
    for txt in [
        "Records not imported into REPO (repository) Gramps ID R00001:ADDR element ignored 'x'",
        "   ",
        "  padded  ",
    ]:
        n = Note()
        n.set(txt)
        db.add_note(n, t)

print("start", counts())
steps = []
for layer in fix.AUTO_STEP_LAYERS:
    before = counts()
    snap = snapshot()
    undo_depth_before = (
        db.undodb.undoq.__len__() if hasattr(db.undodb, "undoq") else None
    )
    msg = fix.run_auto_layer(layer, db)
    after = counts()
    print("%-26s %s" % (layer, msg), "|", after)
    # one undo reverses exactly this step
    changed = after != before
    ok = db.undo()
    reverted = snapshot() == snap
    db.redo()
    print(
        "   undo ok=%s content-identical-after-ONE-undo=%s (step changed db: %s)"
        % (ok, reverted, changed)
    )

print("\n--- final state")
for s in db.iter_sources():
    print(
        "SRC",
        s.get_gramps_id(),
        repr(s.get_title()),
        [db.get_repository_from_handle(r.ref).get_name() for r in s.get_reporef_list()],
        "notes:",
        [note_text(db.get_note_from_handle(n)) for n in s.get_note_list()],
    )
for r in db.iter_repositories():
    print(
        "REPO",
        repr(r.get_name()),
        [a.get_street() for a in r.get_address_list()],
        [u.get_path() for u in r.get_url_list()],
        [note_text(db.get_note_from_handle(n)) for n in r.get_note_list()],
    )
for c in db.iter_citations():
    print(
        "CIT",
        repr(c.get_page()),
        c.get_confidence_level(),
        [(str(a.get_type()), a.get_value()) for a in c.get_attribute_list()],
        [note_text(db.get_note_from_handle(n))[:50] for n in c.get_note_list()],
        c.get_date_object(),
    )
print("NOTES", [note_text(n)[:40] for n in db.iter_notes()])
print("REVIEW:", fix.find_items_needing_review(db))

print("\n=== second full pass (should be idempotent)")
snap1 = snapshot()
for layer in fix.AUTO_STEP_LAYERS:
    print("%-26s %s" % (layer, fix.run_auto_layer(layer, db)))
print("db unchanged by second pass:", snapshot() == snap1)

print("\n=== repo chain A->B->C and cycle safety")
from gramps.plugins.tool.gw_repoconsolidatedialog import apply_repo_consolidations

with DbTxn("mk", db) as t:
    hs = []
    for nm in ("Chain A", "Chain B", "Chain C"):
        r = Repository()
        r.set_name(nm)
        hs.append(db.add_repository(r, t))
res = apply_repo_consolidations(db, [(hs[0], hs[1]), (hs[1], hs[2])])


def exists(h):
    try:
        db.get_repository_from_handle(h)
        return True
    except Exception:
        return False


print(res, [exists(h) for h in hs])
with DbTxn("mk2", db) as t:
    r = Repository()
    r.set_name("Cyc X")
    x = db.add_repository(r, t)
    r = Repository()
    r.set_name("Cyc Y")
    y = db.add_repository(r, t)
res = apply_repo_consolidations(db, [(x, y), (y, x)])
print("cycle:", res["merged"], res["errors"], exists(x), exists(y))

print("\n=== third pass (parser input converges after 2 passes)")
snap2 = snapshot()
msgs = [fix.run_auto_layer(l, db) for l in fix.AUTO_STEP_LAYERS]
print(msgs)
print("db unchanged by third pass:", snapshot() == snap2)

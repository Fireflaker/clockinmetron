import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from timeclock import sync  # noqa: E402
from timeclock.store import Store  # noqa: E402


def doc(tags=(("A", 0, 0),), log=((100, "A", 0, 0),), sch=()):
    return {"tags": [{"name": n, "x": x, "y": y} for n, x, y in tags],
            "log": [list(r) for r in log],
            "schedules": [{"id": i, "name": n, "hhmm": "09:00", "days": "12345", "on": True, "last": last}
                          for i, n, last in sch]}


class SyncTest(unittest.TestCase):
    def test_digest_ignores_int_float_order_and_schedule_last(self):
        a = doc(tags=(("A", 0, 1), ("B", .5, .5)), sch=((1, "A", 10),))
        b = doc(tags=(("B", .5, .5), ("A", 0.0, 1.0)), log=((100.0, "A", 0.0, 0.0),), sch=((1, "A", 99),))
        self.assertEqual(sync.digest(a), sync.digest(b))
        self.assertNotEqual(sync.digest(a), sync.digest(doc()))

    def test_decide_cases(self):
        old, mine, theirs = doc(), doc(log=((100, "A", 0, 0), (200, "A", 1, 1))), doc(tags=(("A", 0, 0), ("Z", 1, 1)))
        base = sync.digest(old)
        self.assertEqual(sync.decide(None, mine, None), (mine, None, sync.digest(mine)))     # no gist yet
        self.assertEqual(sync.decide(base, old, old), (None, None, base))                     # nothing changed
        self.assertEqual(sync.decide(base, mine, old), (mine, None, sync.digest(mine)))       # upload
        self.assertEqual(sync.decide(base, old, theirs), (None, theirs, sync.digest(theirs)))  # adopt
        up, adopt, nb = sync.decide(base, mine, theirs)                                        # both: merge
        self.assertIs(up, adopt)
        self.assertEqual({t["name"] for t in up["tags"]}, {"A", "Z"})
        self.assertEqual([r[0] for r in up["log"]], [100, 200])
        self.assertEqual(nb, sync.digest(up))

    def test_merge_local_wins_and_compacts(self):
        remote = doc(tags=(("A", 0, 0),), log=((100, "A", 0, 0), (150, "A", 0, 0), (300, "B", 1, 1)),
                     sch=((1, "A", 500),))
        local = doc(tags=(("A", 1, 1),), log=((100, "A", 0, 0), (200, "C", .5, .5)), sch=((1, "A", 400), (2, "C", None)))
        m = sync.merge(remote, local)
        self.assertEqual(m["tags"], [{"name": "A", "x": 1, "y": 1}])
        self.assertEqual([r[0] for r in m["log"]], [100, 200, 300])     # 150 duplicate of 100 dropped
        self.assertEqual({s["id"]: s["last"] for s in m["schedules"]}, {1: 500, 2: None})

    def test_store_doc_roundtrip(self):
        with tempfile.TemporaryDirectory() as tmp:
            a, b = Store(os.path.join(tmp, "a.db"), now=1000), Store(os.path.join(tmp, "b.db"), now=5)
            try:
                a.add_tag("New", .3, .7)
                a.clock_in("New", now=2000)
                b.replace_doc(a.doc())
                self.assertEqual(sync.digest(a.doc()), sync.digest(b.doc()))
                self.assertEqual(b.current()[1], "New")
            finally:
                a.db.close()
                b.db.close()

    def test_sync_once_with_fake_gist(self):
        class Fake(sync.Gist):
            def __init__(self, remote):
                super().__init__("t")
                self.remote, self.saved = remote, None

            def find(self):
                self.id = "g" if self.remote else None

            def load(self):
                return self.remote

            def save(self, d):
                self.saved, self.id = d, "g"

        g = Fake(None)
        self.assertEqual(sync.sync_once(g, None, doc()), (None, sync.digest(doc())))
        self.assertEqual(g.saved, doc())
        theirs = doc(tags=(("Q", 1, 1),))
        g = Fake(theirs)
        self.assertEqual(sync.sync_once(g, None, doc(), first="replace"), (theirs, sync.digest(theirs)))
        self.assertIsNone(g.saved)


if __name__ == "__main__":
    unittest.main()

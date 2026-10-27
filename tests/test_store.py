import os
import sys
import tempfile
import unittest
from datetime import date, datetime, timedelta

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from timeclock.store import Store, day_bounds  # noqa: E402

D = date(2025, 1, 15)
DS, DE = day_bounds(D)
H = 3600


class StoreTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.s = Store(os.path.join(self.tmp.name, "t.db"), now=DS)

    def tearDown(self):
        self.s.db.close()
        self.tmp.cleanup()

    def log_ts(self):
        return [r[0] for r in self.s.db.execute("SELECT t FROM log ORDER BY t")]

    def test_seeded_and_clocked_into_sleep(self):
        self.assertEqual(self.s.current()[1], "Sleep")
        self.assertIn("Gym", [n for n, _, _ in self.s.tags()])

    def test_full_day_sums_to_24h(self):
        self.s.clock_in("Gym", now=DS + 7 * H)
        self.s.clock_in("YouTube", now=DS + 9 * H)
        s = self.s.day_summary(D, now=DE + H)
        self.assertAlmostEqual(sum(s["by_name"].values()), 24 * H)
        self.assertEqual(s["future"], 0)
        self.assertAlmostEqual(s["by_name"]["Gym"], 2 * H)
        self.assertAlmostEqual(sum(s["quadrants"].values()), 24 * H)

    def test_partial_day_has_future(self):
        s = self.s.day_summary(D, now=DS + 10 * H)
        self.assertAlmostEqual(s["future"], 14 * H)
        self.assertAlmostEqual(s["by_name"]["Sleep"] + s["future"] + s["untracked"], 24 * H)

    def test_clock_in_same_task_is_noop_and_quick_switch_updates(self):
        self.s.clock_in("Sleep", now=DS + H)
        self.assertEqual(len(self.log_ts()), 1)
        self.s.clock_in("Gym", now=DS + H)
        self.s.clock_in("Chores", now=DS + H + 0.5)
        self.assertEqual(self.s.current()[1], "Chores")
        self.assertEqual(len(self.log_ts()), 2)

    def test_log_block_splits_middle(self):
        self.s.log_block("Gym", DS + 2 * H, DS + 3 * H)
        segs = [(n, a, b) for _, n, _, _, a, b in self.s.segments_between(DS, DS + 5 * H, DS + 5 * H)]
        self.assertEqual(segs, [("Sleep", DS, DS + 2 * H), ("Gym", DS + 2 * H, DS + 3 * H),
                                ("Sleep", DS + 3 * H, DS + 5 * H)])

    def test_log_block_until_now_keeps_running(self):
        self.s.clock_in("YouTube", now=DS + 5 * H)
        self.s.log_block("Engineering", DS + 3 * H)
        self.assertEqual(self.s.current()[1], "Engineering")
        self.assertEqual(self.log_ts(), [DS, DS + 3 * H])

    def test_log_block_before_tracking_marks_untracked(self):
        self.s.log_block("Gym", DS - 3 * H, DS - 2 * H)
        rows = self.s.db.execute("SELECT t,name FROM log ORDER BY t").fetchall()
        self.assertEqual(rows, [(DS - 3 * H, "Gym"), (DS - 2 * H, None), (DS, "Sleep")])
        prev = self.s.day_summary(D - timedelta(days=1), now=DS + H)
        self.assertAlmostEqual(prev["by_name"]["Gym"], H)
        self.assertAlmostEqual(prev["untracked"], 23 * H)

    def test_compaction_merges_identical_neighbours(self):
        self.s.clock_in("Gym", now=DS + H)
        self.s.clock_in("Sleep", now=DS + 2 * H)
        self.s.reassign(DS + H, "Sleep")
        self.assertEqual(self.log_ts(), [DS])

    def test_tag_edits_never_rewrite_log(self):
        self.s.clock_in("Gym", now=DS + H)
        self.s.clock_in("Sleep", now=DS + 2 * H)
        self.s.clock_in("Gym", now=DS + 3 * H)
        before = self.s.db.execute("SELECT * FROM log ORDER BY t").fetchall()
        self.s.move_tag("Gym", 0.9, 0.9)
        self.s.rename_tag("Gym", "Lifting")
        self.s.delete_tag("Lifting")
        self.assertIsNone(self.s.tag("Lifting"))
        self.assertEqual(self.s.db.execute("SELECT * FROM log ORDER BY t").fetchall(), before)

    def test_moved_tag_applies_from_next_clock_in(self):
        self.s.clock_in("Gym", now=DS + H)
        self.s.move_tag("Gym", 0.9, 0.9)
        self.s.clock_in("Gym", now=DS + 2 * H)
        rows = self.s.db.execute("SELECT x,y FROM log WHERE name='Gym' ORDER BY t").fetchall()
        self.assertNotEqual(rows[0], (0.9, 0.9))
        self.assertEqual(rows[1], (0.9, 0.9))

    def test_add_duplicate_tag_raises(self):
        self.s.add_tag("Hike", 0.9, 0.1)
        with self.assertRaises(ValueError):
            self.s.add_tag("Hike", 0.1, 0.1)

    def test_segments_never_overlap(self):
        for i, n in enumerate(["Gym", "Chores", "YouTube", "Shower"]):
            self.s.clock_in(n, now=DS + (i + 1) * H)
        self.s.log_block("Skincare", DS + 1.5 * H, DS + 3.5 * H)
        segs = self.s.segments_between(DS, DE, DS + 6 * H)
        for (*_, a1, b1), (*_, a2, b2) in zip(segs, segs[1:]):
            self.assertEqual(b1, a2)
        self.assertAlmostEqual(sum(b - a for *_, a, b in segs), 6 * H)

    def test_schedule_backfills_weekdays_at_exact_time(self):
        # D is a Wednesday; schedule Engineering Mon-Fri 09:00, app "closed" until Sunday night.
        self.s.add_schedule("Engineering", "9:00", "12345", now=DS)
        fired = self.s.apply_schedules(now=DS + 4 * 24 * H + 20 * H)
        self.assertEqual(fired, ["Engineering"] * 3)  # Wed, Thu, Fri
        self.assertIn(DS + 9 * H, self.log_ts())
        self.assertNotIn(DS + 3 * 24 * H + 9 * H, self.log_ts())  # Saturday
        self.assertEqual(self.s.apply_schedules(now=DS + 4 * 24 * H + 21 * H), [])  # only once

    def test_schedule_not_retroactive_and_respects_later_entries(self):
        self.s.add_schedule("Gym", "08:00", "1234567", now=DS + 10 * H)
        self.assertEqual(self.s.apply_schedules(now=DS + 11 * H), [])
        self.s.clock_in("YouTube", now=DS + 24 * H + 8.5 * H)
        self.assertEqual(self.s.apply_schedules(now=DS + 24 * H + 9 * H), ["Gym"])
        segs = self.s.segments_between(DS + 24 * H, DS + 48 * H, DS + 24 * H + 9 * H)
        self.assertEqual([(n, b - a) for _, n, _, _, a, b in segs if n == "Gym"], [("Gym", 0.5 * H)])
        self.assertEqual(self.s.current()[1], "YouTube")

    def test_disabled_schedule_does_not_fire(self):
        self.s.add_schedule("Gym", "08:00", "1234567", now=DS)
        sid = self.s.schedules()[0][0]
        self.s.set_schedule_enabled(sid, False, now=DS)
        self.assertEqual(self.s.apply_schedules(now=DS + 2 * 24 * H), [])
        self.s.set_schedule_enabled(sid, True, now=DS + 2 * 24 * H)
        self.assertEqual(self.s.apply_schedules(now=DS + 2 * 24 * H + 1), [])
        with self.assertRaises(ValueError):
            self.s.add_schedule("Gym", "25:00", "1")


if __name__ == "__main__":
    unittest.main()

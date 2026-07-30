import unittest

from vlog_director.revision import compare_revisions, compile_revision


def plan(version: int, parent_version, segments: list[dict]) -> dict:
    return {
        "schema_version": "1.0",
        "project_id": "demo",
        "version": version,
        "parent_version": parent_version,
        "brief": {
            "target_duration_sec": 20,
            "aspect_ratio": "16:9",
            "mode": "timeline",
            "keep_dialogue": True,
        },
        "chapters": [
            {"id": "ch01", "title": "Demo", "target_duration_sec": 20, "segments": segments}
        ],
        "music": [],
        "qa": [],
        "created_at": "2026-07-30T00:00:00+08:00",
    }


class RevisionTests(unittest.TestCase):
    def test_identical_timeline_is_blocked(self) -> None:
        segments = [
            {
                "source": "raw/a.mp4", "in_sec": 0, "out_sec": 10,
                "story_role": "setup", "reason": "setup", "keep_original_audio": True,
                "beat_snap": False, "confidence": 0.9,
            }
        ]
        result = compare_revisions(plan(1, None, segments), plan(2, 1, segments))
        self.assertEqual(result["status"], "blocked")
        self.assertIn("timeline_unchanged", {issue["code"] for issue in result["issues"]})

    def test_compile_revision_requires_real_profile_principles(self) -> None:
        parent_segments = [
            {
                "source": "raw/a.mp4", "in_sec": 0, "out_sec": 10,
                "story_role": "setup", "reason": "setup", "keep_original_audio": True,
                "beat_snap": False, "confidence": 0.9,
            }
        ]
        changed = [dict(parent_segments[0], out_sec=7)]
        directives = {
            "version": 2,
            "created_at": "2026-07-30T00:00:00+08:00",
            "minimum_change_ratio": 0.5,
            "applied_principles": ["pacing"],
            "chapters": [{"id": "ch01", "title": "Demo", "segments": changed}],
        }
        candidate, report = compile_revision(
            plan(1, None, parent_segments),
            {"profile_id": "profile", "principles": [{"id": "pacing"}]},
            directives,
        )
        self.assertEqual(candidate["version"], 2)
        self.assertEqual(candidate["brief"]["target_duration_sec"], 7)
        self.assertEqual(report["status"], "passed")
        self.assertEqual(report["profile_id"], "profile")


if __name__ == "__main__":
    unittest.main()

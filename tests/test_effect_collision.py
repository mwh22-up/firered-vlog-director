import unittest

from vlog_director.effect_collision import audit_effect_collisions


class EffectCollisionTests(unittest.TestCase):
    def test_subtitle_or_face_overlap_becomes_measured_blocker(self) -> None:
        findings = audit_effect_collisions(
            effect_id="fx-1",
            sample_time_sec=2.0,
            effect_bbox={"x": 0, "y": 700, "width": 1920, "height": 380},
            protected_regions=[
                {
                    "region_id": "cue-1",
                    "region_type": "subtitle",
                    "start_sec": 1.0,
                    "end_sec": 3.0,
                    "bbox": {"x": 500, "y": 820, "width": 920, "height": 140},
                }
            ],
        )

        self.assertEqual(len(findings), 1)
        self.assertEqual(findings[0]["severity"], "error")
        self.assertEqual(findings[0]["protected_overlap_ratio"], 1.0)

    def test_regions_outside_sample_time_are_ignored(self) -> None:
        findings = audit_effect_collisions(
            effect_id="fx-1",
            sample_time_sec=5.0,
            effect_bbox={"x": 0, "y": 0, "width": 100, "height": 100},
            protected_regions=[
                {
                    "region_id": "face-1",
                    "region_type": "face",
                    "start_sec": 0.0,
                    "end_sec": 1.0,
                    "bbox": {"x": 0, "y": 0, "width": 100, "height": 100},
                }
            ],
        )
        self.assertEqual(findings, [])


if __name__ == "__main__":
    unittest.main()

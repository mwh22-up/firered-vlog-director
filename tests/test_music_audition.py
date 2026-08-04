import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from vlog_director.music_audition import build_music_audition_report


class MusicAuditionTests(unittest.TestCase):
    def test_machine_analysis_requires_human_listening_before_pass(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            project = Path(directory) / "project"
            (project / "work" / "enhancement").mkdir(parents=True)
            (project / "assets" / "music").mkdir(parents=True)
            track = project / "assets" / "music" / "bed.wav"
            track.write_bytes(b"music")
            import hashlib
            digest = hashlib.sha256(track.read_bytes()).hexdigest()
            plan = project / "work" / "enhancement" / "enhancement_plan.v1.json"
            plan.write_text(json.dumps({"project_id": "demo", "music": {"tracks": [{"id": "bed", "source": "assets/music/bed.wav"}]}}), encoding="utf-8")
            rights = project / "assets" / "music" / "rights.json"
            rights.write_text(json.dumps({"assets": [{"id": "bed", "sha256": digest}]}), encoding="utf-8")
            with patch("vlog_director.music_audition.analyze_music_track", return_value={"tempo": {"bpm": 120.0, "confidence": 0.8}, "speech_band_energy_ratio": 0.4, "beat_grid_sec": [0.0, 0.5]}):
                result = build_music_audition_report(project=project, enhancement_plan_path=plan, rights_manifest_path=rights, output_path=project / "work" / "qa" / "audition.json")
            self.assertEqual(result["status"], "review_required")
            self.assertEqual(result["assets"][0]["audition_status"], "review_required")
            self.assertFalse(result["speech_intelligibility"]["verified"])
            self.assertEqual(result["human_review"]["status"], "pending")


if __name__ == "__main__":
    unittest.main()

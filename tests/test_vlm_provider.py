import tempfile
import unittest
from pathlib import Path

from vlog_director.vlm_provider import build_vlm_request, canonical_request_sha256, validate_vlm_evidence, vlm_events_to_candidate_moments


class VLMProviderTests(unittest.TestCase):
    def test_provider_evidence_is_sha_bound_and_cannot_approve_edits(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            media = Path(directory) / "clip.mp4"
            media.write_bytes(b"media")
            request = build_vlm_request(project_id="demo", media_path=media, shots=[{"shot_id": "s1", "start_sec": 0, "end_sec": 1, "evidence_ids": ["scene:s1"]}], provider_name="firered", model="vlm", provider_version="1", prompt="describe")
            evidence = {
                "schema_version": "1.0",
                "contract_version": "vlm-analysis-evidence-v1",
                "status": "evidence_ready",
                "project_id": "demo",
                "request_sha256": canonical_request_sha256(request),
                "media_sha256": request["media"]["sha256"],
                "provider": request["provider"],
                "prompt_sha256": request["prompt_sha256"],
                "events": [{"evidence_id": "e1", "shot_id": "s1", "event_type": "reaction", "description": "smile", "confidence": 0.9}],
                "calibration": {"method": "provider-reported", "calibrated": False},
                "safety": {"may_approve_deletion": False, "may_approve_release": False},
            }
            self.assertEqual(validate_vlm_evidence(request, evidence)["status"], "passed")
            moments = vlm_events_to_candidate_moments(evidence)
            self.assertEqual(moments[0]["keep_level"], "candidate")
            evidence["media_sha256"] = "0" * 64
            self.assertEqual(validate_vlm_evidence(request, evidence)["status"], "blocked")


if __name__ == "__main__":
    unittest.main()

from __future__ import annotations

import copy
import hashlib
import json
import tempfile
import unittest
from datetime import UTC, datetime
from pathlib import Path

from vlog_director.effect_approval import (
    EffectContractError,
    apply_approved_effects,
    build_effect_approval,
    validate_effect_approval,
)
from vlog_director.effect_plan import build_effect_plan, canonical_effect_payload_sha256
from vlog_director.enhancement import build_enhancement_plan
from vlog_director.enhancement_assets import validate_enhancement_assets


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _canonical(document: dict) -> str:
    return hashlib.sha256(
        json.dumps(document, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()


def _write(path: Path, document: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(document, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _edit_plan() -> dict:
    return {
        "schema_version": "1.0",
        "project_id": "approval-demo",
        "version": 1,
        "chapters": [
            {
                "id": "ch01",
                "title": "雪山冲刺",
                "segments": [
                    {
                        "source": "raw/a.mp4",
                        "in_sec": 0,
                        "out_sec": 2,
                        "story_role": "reaction",
                        "keep_original_audio": True,
                    }
                ],
            }
        ],
    }


class EffectApprovalTests(unittest.TestCase):
    def test_effect_evidence_formal_and_runtime_schemas_are_identical(self) -> None:
        root = Path(__file__).parents[1]
        for name in (
            "effect-visual-qa.schema.json",
            "effect-human-review.schema.json",
            "effect-approval.schema.json",
        ):
            self.assertEqual(
                (root / "schemas" / name).read_bytes(),
                (root / "src" / "vlog_director" / "schemas" / name).read_bytes(),
            )

    def _artifacts(self, root: Path) -> dict[str, Path | dict]:
        project = root / "project"
        edit = _edit_plan()
        edit_path = project / "work" / "plans" / "edit_plan.v1.json"
        _write(edit_path, edit)
        effect = build_effect_plan(edit, edit_plan_sha256=_canonical(edit))
        effect_duration = round(
            effect["effects"][0]["placement"]["end_sec"]
            - effect["effects"][0]["placement"]["start_sec"],
            4,
        )
        effect_path = project / "work" / "effects" / "effect_plan.v1.json"
        _write(effect_path, effect)
        effect_id = effect["effects"][0]["effect_id"]
        output = project / "work" / "effects" / "job-1" / effect_id / "overlay.mov"
        output.parent.mkdir(parents=True)
        output.write_bytes(b"transparent-effect-v1")
        composition = output.parent / "index.html"
        composition.write_text("<html>effect</html>", encoding="utf-8")
        composition_manifest_path = project / "work" / "effects" / "job-1" / "composition-manifest.json"
        _write(composition_manifest_path, {"status": "composed"})
        render = {
            "schema_version": "1.0",
            "contract_version": "hyperframes-render-manifest-v1",
            "status": "rendered",
            "project_id": edit["project_id"],
            "edit_plan_version": 1,
            "edit_plan_sha256": effect["edit_plan_sha256"],
            "effect_plan": "work/effects/effect_plan.v1.json",
            "effect_plan_sha256": _sha(effect_path),
            "effect_payload_sha256": canonical_effect_payload_sha256(effect),
            "composition_manifest": "work/effects/job-1/composition-manifest.json",
            "composition_manifest_sha256": _sha(composition_manifest_path),
            "hyperframes": {
                "executable": "hyperframes",
                "package": "hyperframes",
                "version": "0.7.90",
                "npm_integrity": effect["capability_registry"]["npm_integrity"],
            },
            "effects": [
                {
                    "effect_id": effect_id,
                    "intent": effect["effects"][0]["intent"],
                    "duration_sec": effect_duration,
                    "composition": composition.relative_to(project).as_posix(),
                    "composition_sha256": _sha(composition),
                    "output": output.relative_to(project).as_posix(),
                    "output_size_bytes": output.stat().st_size,
                    "output_sha256": _sha(output),
                }
            ],
        }
        render_path = project / "work" / "effects" / "job-1" / "render-manifest.json"
        _write(render_path, render)
        preview = project / "work" / "qa" / "effects" / "qa-1" / f"{effect_id}.preview.mp4"
        preview.parent.mkdir(parents=True)
        preview.write_bytes(b"preview")
        frames = []
        for role in ("entry", "peak", "exit"):
            frame = preview.parent / f"{effect_id}.{role}.png"
            frame.write_bytes(role.encode("ascii"))
            frames.append(
                {"role": role, "path": frame.relative_to(project).as_posix(), "sha256": _sha(frame)}
            )
        base = project / "output" / "directed.v1.mp4"
        base.parent.mkdir(parents=True)
        base.write_bytes(b"base-edit")
        visual = {
            "schema_version": "1.0",
            "contract_version": "effect-visual-qa-v1",
            "status": "evidence_ready",
            "project_id": edit["project_id"],
            "edit_plan_version": 1,
            "edit_plan_sha256": effect["edit_plan_sha256"],
            "effect_plan_sha256": _sha(effect_path),
            "effect_payload_sha256": canonical_effect_payload_sha256(effect),
            "render_manifest_sha256": _sha(render_path),
            "base_media": {
                "path": base.relative_to(project).as_posix(),
                "size_bytes": base.stat().st_size,
                "sha256": _sha(base),
            },
            "effects": [
                {
                    "effect_id": effect_id,
                    "output_sha256": _sha(output),
                    "preview": {
                        "path": preview.relative_to(project).as_posix(),
                        "sha256": _sha(preview),
                    },
                    "frames": frames,
                    "machine_checks": {
                        "decode": "passed",
                        "duration": "passed",
                        "geometry": "passed",
                        "alpha": "passed",
                    },
                }
            ],
            "human_review": {"status": "pending"},
            "conclusion": "已生成视觉帧和布局证据，效果适配性仍需人工检查。",
        }
        visual_path = preview.parent / "visual-qa.json"
        _write(visual_path, visual)
        human = {
            "schema_version": "1.0",
            "contract_version": "effect-human-review-v1",
            "status": "approved",
            "reviewer": "editor-a",
            "reviewed_at": datetime.now(UTC).isoformat(),
            "effect_plan_sha256": _sha(effect_path),
            "effect_payload_sha256": canonical_effect_payload_sha256(effect),
            "render_manifest_sha256": _sha(render_path),
            "visual_qa_sha256": _sha(visual_path),
            "base_media_sha256": _sha(base),
            "effects": [
                {
                    "effect_id": effect_id,
                    "decision": "accepted",
                    "checks": ["timing", "safe_zones", "visual_fit", "intensity"],
                    "intensity_feedback": "keep",
                }
            ],
            "attestation": "I reviewed the rendered effect previews against the base edit.",
        }
        human_path = project / "work" / "qa" / "effects" / "human-review.v1.json"
        _write(human_path, human)
        return {
            "project": project,
            "edit": edit,
            "effect": effect,
            "effect_path": effect_path,
            "render_path": render_path,
            "visual_path": visual_path,
            "human_path": human_path,
            "output": output,
        }

    def test_build_validate_and_apply_sha_bound_approval(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            artifacts = self._artifacts(Path(temporary))
            project = artifacts["project"]
            approval_path = project / "work" / "qa" / "effects" / "approval.v1.json"
            approval = build_effect_approval(
                project,
                artifacts["effect_path"],
                artifacts["render_path"],
                artifacts["visual_path"],
                artifacts["human_path"],
                approval_path,
            )
            self.assertEqual(approval["status"], "approved")
            self.assertEqual(
                validate_effect_approval(
                    project,
                    artifacts["effect_path"],
                    artifacts["render_path"],
                    artifacts["visual_path"],
                    artifacts["human_path"],
                    approval_path,
                )["status"],
                "passed",
            )

            enhancement_path = project / "work" / "enhancement" / "enhancement_plan.v1.json"
            _write(enhancement_path, build_enhancement_plan(artifacts["edit"]))
            output_path = project / "work" / "enhancement" / "enhancement_plan.v2.json"
            enhanced = apply_approved_effects(
                project,
                enhancement_path,
                artifacts["effect_path"],
                artifacts["render_path"],
                artifacts["visual_path"],
                artifacts["human_path"],
                approval_path,
                output_path,
            )
            item = enhanced["illustration_motion"]["items"][0]
            self.assertEqual(item["type"], "hyperframes")
            self.assertEqual(item["media_kind"], "transparent_video")
            self.assertEqual(item["source_sha256"], _sha(artifacts["output"]))
            self.assertIn("effect_evidence", enhanced["illustration_motion"])
            self.assertTrue(output_path.is_file())
            self.assertEqual(validate_enhancement_assets(project, enhanced), [])

    def test_any_render_or_evidence_change_invalidates_approval(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            artifacts = self._artifacts(Path(temporary))
            project = artifacts["project"]
            approval_path = project / "work" / "qa" / "effects" / "approval.v1.json"
            build_effect_approval(
                project,
                artifacts["effect_path"],
                artifacts["render_path"],
                artifacts["visual_path"],
                artifacts["human_path"],
                approval_path,
            )
            artifacts["output"].write_bytes(b"changed")
            result = validate_effect_approval(
                project,
                artifacts["effect_path"],
                artifacts["render_path"],
                artifacts["visual_path"],
                artifacts["human_path"],
                approval_path,
            )
            self.assertEqual(result["status"], "blocked")
            self.assertIn("effect_output_sha256_mismatch", result["blocker_codes"])

    def test_manual_approval_status_cannot_replace_required_contract(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            artifacts = self._artifacts(Path(temporary))
            project = artifacts["project"]
            fake = project / "work" / "qa" / "effects" / "approval.fake.json"
            _write(fake, {"schema_version": "1.0", "status": "approved"})

            result = validate_effect_approval(
                project,
                artifacts["effect_path"],
                artifacts["render_path"],
                artifacts["visual_path"],
                artifacts["human_path"],
                fake,
            )
            self.assertEqual(result["status"], "blocked")
            self.assertIn("effect_approval_schema_invalid", result["blocker_codes"])

    def test_visual_qa_cannot_rebind_base_media_outside_output_or_proxy(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            artifacts = self._artifacts(Path(temporary))
            project = artifacts["project"]
            visual = json.loads(artifacts["visual_path"].read_text(encoding="utf-8"))
            visual["base_media"] = {
                "path": artifacts["output"].relative_to(project).as_posix(),
                "size_bytes": artifacts["output"].stat().st_size,
                "sha256": _sha(artifacts["output"]),
            }
            _write(artifacts["visual_path"], visual)
            human = json.loads(artifacts["human_path"].read_text(encoding="utf-8"))
            human["base_media_sha256"] = _sha(artifacts["output"])
            human["visual_qa_sha256"] = _sha(artifacts["visual_path"])
            _write(artifacts["human_path"], human)

            with self.assertRaises(EffectContractError) as caught:
                build_effect_approval(
                    project,
                    artifacts["effect_path"],
                    artifacts["render_path"],
                    artifacts["visual_path"],
                    artifacts["human_path"],
                    project / "work" / "qa" / "effects" / "approval.v1.json",
                )
            self.assertEqual(caught.exception.code, "effect_base_media_path_invalid")

    def test_render_manifest_cannot_rebind_intent_or_duration(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            artifacts = self._artifacts(Path(temporary))
            project = artifacts["project"]
            render = json.loads(artifacts["render_path"].read_text(encoding="utf-8"))
            render["effects"][0]["intent"] = "impact_hit"
            render["effects"][0]["duration_sec"] += 0.25
            _write(artifacts["render_path"], render)
            visual = json.loads(artifacts["visual_path"].read_text(encoding="utf-8"))
            visual["render_manifest_sha256"] = _sha(artifacts["render_path"])
            _write(artifacts["visual_path"], visual)
            human = json.loads(artifacts["human_path"].read_text(encoding="utf-8"))
            human["render_manifest_sha256"] = _sha(artifacts["render_path"])
            human["visual_qa_sha256"] = _sha(artifacts["visual_path"])
            _write(artifacts["human_path"], human)

            with self.assertRaises(EffectContractError) as caught:
                build_effect_approval(
                    project,
                    artifacts["effect_path"],
                    artifacts["render_path"],
                    artifacts["visual_path"],
                    artifacts["human_path"],
                    project / "work" / "qa" / "effects" / "approval.v1.json",
                )
            self.assertEqual(caught.exception.code, "effect_render_recipe_mismatch")


if __name__ == "__main__":
    unittest.main()

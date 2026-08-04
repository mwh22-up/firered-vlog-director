from __future__ import annotations

import hashlib
import html
import json
import re
import shutil
import subprocess
from pathlib import Path
from typing import Any, Mapping

from jsonschema import Draft202012Validator

from .effect_plan import (
    HYPERFRAMES_NPM_INTEGRITY,
    HYPERFRAMES_VERSION,
    canonical_effect_payload_sha256,
    validate_effect_plan,
)


VERSION_PATTERN = re.compile(r"(?<![0-9])([0-9]+\.[0-9]+\.[0-9]+)(?![0-9])")


def _schema_issues(document: Mapping[str, Any], schema_name: str) -> list[str]:
    schema_path = Path(__file__).with_name("schemas") / schema_name
    schema = json.loads(schema_path.read_text(encoding="utf-8"))
    errors = sorted(
        Draft202012Validator(schema).iter_errors(document),
        key=lambda error: tuple(str(value) for value in error.absolute_path),
    )
    return [f"{error.json_path}: {error.message}" for error in errors]


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _canonical_sha256(value: Any) -> str:
    return hashlib.sha256(
        json.dumps(
            value,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        ).encode("utf-8")
    ).hexdigest()


def _load_json(path: Path, label: str) -> dict[str, Any]:
    resolved = path.resolve()
    if not resolved.is_file():
        raise FileNotFoundError(resolved)
    payload = resolved.read_bytes()
    if payload.startswith(b"\xef\xbb\xbf"):
        raise ValueError(f"{label} must be UTF-8 without BOM")
    try:
        document = json.loads(payload.decode("utf-8"), parse_constant=lambda value: (_ for _ in ()).throw(ValueError(value)))
    except (UnicodeError, json.JSONDecodeError) as error:
        raise ValueError(f"{label} must be valid UTF-8 JSON") from error
    if not isinstance(document, dict):
        raise ValueError(f"{label} must be a JSON object")
    return document


def _write_new_json(path: Path, document: Mapping[str, Any]) -> None:
    if path.exists():
        raise FileExistsError(path)
    path.write_text(
        json.dumps(document, ensure_ascii=False, sort_keys=True, indent=2, allow_nan=False)
        + "\n",
        encoding="utf-8",
        newline="\n",
    )


def _strict_job_directory(project: Path, output_directory: Path) -> tuple[Path, str]:
    project = project.resolve()
    allowed_root = (project / "work" / "effects").resolve()
    output = output_directory.resolve()
    try:
        relative = output.relative_to(allowed_root)
    except ValueError as error:
        raise ValueError("HyperFrames jobs must stay under project/work/effects") from error
    if output == allowed_root or len(relative.parts) != 1 or relative.parts[0] in {".", ".."}:
        raise ValueError("HyperFrames output must be one unique directory below work/effects")
    return output, relative.as_posix()


def _project_relative(project: Path, path: Path) -> str:
    try:
        return path.resolve().relative_to(project.resolve()).as_posix()
    except ValueError as error:
        raise ValueError("effect artifact escaped the project root") from error


def _effect_markup(effect: Mapping[str, Any]) -> tuple[str, str]:
    intent = str(effect["intent"])
    parameters = effect["recipe"].get("parameters", {})
    if intent == "place_reveal":
        text = html.escape(str(parameters.get("text", "新章节")))
        markup = f"""
        <div id="panel" data-layout-allow-overflow class="visual panel"></div>
        <div id="slash-a" data-layout-allow-overflow class="visual slash slash-a"></div>
        <div id="slash-b" data-layout-allow-overflow class="visual slash slash-b"></div>
        <div id="title-wrap" data-layout-allow-overflow class="visual title-wrap">
          <div class="eyebrow">NOW ENTERING</div>
          <div id="title" class="title">{text}</div>
        </div>
        """
        animation = """
        animateElement(document.getElementById("panel"),
          [{ transform: "translate3d(-105%,0,0) skewX(-8deg)", opacity: 1 },
           { transform: "translate3d(0,0,0) skewX(0deg)", opacity: 1, offset: 0.28 },
           { transform: "translate3d(0,0,0) skewX(0deg)", opacity: 1, offset: 0.82 },
           { transform: "translate3d(105%,0,0) skewX(8deg)", opacity: 0 }], totalMs);
        animateElement(document.getElementById("title-wrap"),
          [{ transform: "translate3d(0,120px,0) scale(1.35)", opacity: 0 },
           { transform: "translate3d(0,-12px,0) scale(0.96)", opacity: 1, offset: 0.32 },
           { transform: "translate3d(0,0,0) scale(1)", opacity: 1, offset: 0.52 },
           { transform: "translate3d(0,-60px,0) scale(1.08)", opacity: 0 }], totalMs);
        animateElement(document.getElementById("slash-a"),
          [{ transform: "translate3d(-800px,0,0) rotate(-12deg)", opacity: 0 },
           { transform: "translate3d(0,0,0) rotate(-12deg)", opacity: 1, offset: 0.34 },
           { transform: "translate3d(900px,0,0) rotate(-12deg)", opacity: 0 }], totalMs);
        animateElement(document.getElementById("slash-b"),
          [{ transform: "translate3d(800px,0,0) rotate(12deg)", opacity: 0 },
           { transform: "translate3d(0,0,0) rotate(12deg)", opacity: 1, offset: 0.4 },
           { transform: "translate3d(-900px,0,0) rotate(12deg)", opacity: 0 }], totalMs);
        """
        return markup, animation
    if intent == "kinetic_explain":
        text = html.escape(str(parameters.get("text", "重点")))
        markup = f"""
        <div id="explain-card" data-layout-allow-overflow class="visual explain-card">
          <div class="explain-index">EXPLAIN / 01</div>
          <div id="explain-text" class="explain-text">{text}</div>
          <div id="underline" class="underline"></div>
        </div>
        <div id="cyan-chip" data-layout-allow-overflow class="visual cyan-chip"></div>
        """
        animation = """
        animateElement(document.getElementById("explain-card"),
          [{ transform: "translate3d(-115%,0,0) rotate(-5deg) scale(.9)", opacity: 0 },
           { transform: "translate3d(4%,0,0) rotate(1.5deg) scale(1.04)", opacity: 1, offset: .28 },
           { transform: "translate3d(0,0,0) rotate(0deg) scale(1)", opacity: 1, offset: .45 },
           { transform: "translate3d(110%,0,0) rotate(5deg) scale(.92)", opacity: 0 }], totalMs);
        animateElement(document.getElementById("explain-text"),
          [{ transform: "translate3d(0,70px,0) scale(1.22)", opacity: 0 },
           { transform: "translate3d(0,-8px,0) scale(.97)", opacity: 1, offset: .34 },
           { transform: "translate3d(0,0,0) scale(1)", opacity: 1, offset: .52 },
           { transform: "translate3d(0,-40px,0) scale(1.04)", opacity: 0 }], totalMs);
        animateElement(document.getElementById("underline"),
          [{ transform: "scaleX(0)", opacity: 1 },
           { transform: "scaleX(1)", opacity: 1, offset: .42 },
           { transform: "scaleX(1)", opacity: 1, offset: .84 },
           { transform: "scaleX(0)", opacity: 0 }], totalMs);
        animateElement(document.getElementById("cyan-chip"),
          [{ transform: "translate3d(500px,-500px,0) rotate(25deg)", opacity: 0 },
           { transform: "translate3d(0,0,0) rotate(-12deg)", opacity: 1, offset: .38 },
           { transform: "translate3d(-500px,500px,0) rotate(-35deg)", opacity: 0 }], totalMs);
        """
        return markup, animation
    if intent == "reaction_burst":
        glyph = html.escape(str(parameters.get("glyph", "!")))
        count = max(6, min(24, int(parameters.get("burst_count", 14))))
        rays = "\n".join(
            f'<div class="ray" style="transform:rotate({round(index * 360 / count, 3)}deg)"></div>'
            for index in range(count)
        )
        markup = f"""
        <div id="burst" data-layout-allow-overflow class="visual burst">{rays}</div>
        <div id="reaction-badge" data-layout-allow-overflow class="visual reaction-badge">{glyph}</div>
        <div id="reaction-ring" data-layout-allow-overflow class="visual reaction-ring"></div>
        """
        animation = """
        animateElement(document.getElementById("burst"),
          [{ transform: "scale(.08) rotate(-24deg)", opacity: 0 },
           { transform: "scale(1.3) rotate(6deg)", opacity: 1, offset: .26 },
           { transform: "scale(1) rotate(0deg)", opacity: .92, offset: .48 },
           { transform: "scale(1.55) rotate(12deg)", opacity: 0 }], totalMs);
        animateElement(document.getElementById("reaction-badge"),
          [{ transform: "scale(.05) rotate(-25deg)", opacity: 0 },
           { transform: "scale(1.35) rotate(8deg)", opacity: 1, offset: .22 },
           { transform: "scale(.94) rotate(-3deg)", opacity: 1, offset: .42 },
           { transform: "scale(1.05) rotate(0deg)", opacity: 1, offset: .72 },
           { transform: "scale(1.5) rotate(15deg)", opacity: 0 }], totalMs);
        animateElement(document.getElementById("reaction-ring"),
          [{ transform: "scale(.2)", opacity: 0 },
           { transform: "scale(1.1)", opacity: 1, offset: .25 },
           { transform: "scale(2.5)", opacity: 0 }], totalMs);
        """
        return markup, animation
    if intent == "impact_hit":
        markup = """
        <div id="impact-flash" data-layout-allow-overflow class="visual impact-flash"></div>
        <div id="impact-ring-a" data-layout-allow-overflow class="visual impact-ring impact-ring-a"></div>
        <div id="impact-ring-b" data-layout-allow-overflow class="visual impact-ring impact-ring-b"></div>
        <div id="impact-cross" data-layout-allow-overflow class="visual impact-cross">×</div>
        """
        animation = """
        animateElement(document.getElementById("impact-flash"),
          [{ transform: "scale(.05) rotate(-18deg)", opacity: 0 },
           { transform: "scale(1.4) rotate(3deg)", opacity: .9, offset: .18 },
           { transform: "scale(2.2) rotate(8deg)", opacity: 0, offset: .5 },
           { transform: "scale(2.4) rotate(12deg)", opacity: 0 }], totalMs);
        animateElement(document.getElementById("impact-ring-a"),
          [{ transform: "scale(.05)", opacity: 0 },
           { transform: "scale(1.15)", opacity: 1, offset: .26 },
           { transform: "scale(2.8)", opacity: 0 }], totalMs);
        animateElement(document.getElementById("impact-ring-b"),
          [{ transform: "scale(.05)", opacity: 0 },
           { transform: "scale(.05)", opacity: 0, offset: .12 },
           { transform: "scale(1.1)", opacity: 1, offset: .36 },
           { transform: "scale(3.2)", opacity: 0 }], totalMs);
        animateElement(document.getElementById("impact-cross"),
          [{ transform: "scale(.1) rotate(-45deg)", opacity: 0 },
           { transform: "scale(1.4) rotate(8deg)", opacity: 1, offset: .22 },
           { transform: "scale(.9) rotate(0deg)", opacity: 1, offset: .44 },
           { transform: "scale(1.8) rotate(35deg)", opacity: 0 }], totalMs);
        """
        return markup, animation
    raise ValueError(f"unsupported HyperFrames effect intent: {intent}")


def _composition_html(
    effect: Mapping[str, Any],
    style_pack: Mapping[str, Any],
    *,
    width: int,
    height: int,
) -> str:
    duration = float(effect["placement"]["end_sec"]) - float(effect["placement"]["start_sec"])
    total_ms = max(1, round(duration * 1000))
    effect_id = str(effect["effect_id"])
    composition_id = re.sub(r"[^A-Za-z0-9_-]", "-", effect_id)
    palette = style_pack["palette"]
    family = html.escape(str(style_pack["typography"]["family"]), quote=True)
    markup, animations = _effect_markup(effect)
    return f"""<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="UTF-8" />
  <meta name="viewport" content="width={width}, height={height}" />
  <title>{html.escape(effect_id)}</title>
  <style>
    @font-face {{ font-family:"Microsoft YaHei"; src:local("Microsoft YaHei"); }}
    html, body {{ margin:0; width:{width}px; height:{height}px; overflow:hidden; background:transparent; }}
    body {{ font-family:{family}; color:{palette['paper']}; }}
    #root {{ position:relative; width:{width}px; height:{height}px; overflow:hidden; background:transparent; }}
    .clip {{ position:absolute; inset:0; width:100%; height:100%; overflow:hidden; }}
    .visual {{ position:absolute; display:block; box-sizing:border-box; will-change:transform,opacity; }}
    .panel {{ inset:0; background:{palette['primary']}; transform-origin:center; }}
    .slash {{ width:130%; height:70px; left:-15%; top:50%; background:{palette['secondary']}; }}
    .slash-a {{ margin-top:-230px; }} .slash-b {{ margin-top:170px; background:{palette['contrast']}; }}
    .title-wrap {{ inset:0; display:flex; flex-direction:column; align-items:center; justify-content:center; padding:8%; text-align:center; }}
    .eyebrow {{ font-family:Arial,sans-serif; font-weight:900; font-size:30px; letter-spacing:12px; color:{palette['ink']}; margin-bottom:24px; }}
    .title {{ max-width:88%; font-size:clamp(96px,10vw,190px); line-height:.92; font-weight:900; letter-spacing:-5px; text-shadow:10px 10px 0 {palette['ink']}; }}
    .explain-card {{ left:8%; right:8%; top:20%; bottom:20%; padding:7%; background:{palette['paper']}; color:{palette['ink']}; border:18px solid {palette['ink']}; box-shadow:28px 28px 0 {palette['primary']}; display:flex; flex-direction:column; justify-content:center; }}
    .explain-index {{ font:900 28px Arial,sans-serif; letter-spacing:8px; color:{palette['primary']}; margin-bottom:32px; }}
    .explain-text {{ font-size:clamp(80px,8vw,152px); line-height:.98; font-weight:900; max-width:94%; }}
    .underline {{ display:block; width:100%; height:22px; margin-top:40px; background:{palette['primary']}; transform-origin:left center; }}
    .cyan-chip {{ width:260px; height:260px; right:3%; top:7%; background:{palette['contrast']}; border:14px solid {palette['ink']}; }}
    .burst {{ width:980px; height:980px; left:50%; top:50%; margin:-490px 0 0 -490px; }}
    .ray {{ position:absolute; display:block; left:480px; top:0; width:22px; height:440px; background:{palette['secondary']}; transform-origin:11px 490px; clip-path:polygon(50% 0,100% 100%,0 100%); }}
    .reaction-badge {{ width:360px; height:360px; left:50%; top:50%; margin:-180px 0 0 -180px; border-radius:50%; display:grid; place-items:center; background:{palette['primary']}; color:{palette['paper']}; border:18px solid {palette['ink']}; box-shadow:20px 20px 0 {palette['contrast']}; font:900 260px/1 Arial Black,Arial,sans-serif; }}
    .reaction-ring {{ width:520px; height:520px; left:50%; top:50%; margin:-260px 0 0 -260px; border:30px solid {palette['paper']}; border-radius:50%; }}
    .impact-flash {{ width:900px; height:900px; left:50%; top:50%; margin:-450px 0 0 -450px; background:{palette['primary']}; clip-path:polygon(50% 0,61% 34%,86% 14%,70% 42%,100% 50%,70% 58%,86% 86%,61% 66%,50% 100%,39% 66%,14% 86%,30% 58%,0 50%,30% 42%,14% 14%,39% 34%); }}
    .impact-ring {{ width:420px; height:420px; left:50%; top:50%; margin:-210px 0 0 -210px; border:34px solid {palette['secondary']}; border-radius:50%; }}
    .impact-ring-b {{ border-color:{palette['contrast']}; }}
    .impact-cross {{ width:300px; height:300px; left:50%; top:50%; margin:-150px 0 0 -150px; display:grid; place-items:center; color:{palette['paper']}; text-shadow:12px 12px 0 {palette['ink']}; font:900 300px/1 Arial Black,Arial,sans-serif; }}
  </style>
</head>
<body>
  <div id="root" data-composition-id="{composition_id}" data-no-timeline data-start="0" data-width="{width}" data-height="{height}" data-duration="{duration:.4f}" data-fps="30">
    <section id="effect-clip" class="clip" data-start="0" data-duration="{duration:.4f}" data-track-index="1">
      {markup}
    </section>
  </div>
  <script>
    const totalMs = {total_ms};
    const animations = [];
    function animateElement(element, keyframes, duration) {{
      const animation = element.animate(keyframes, {{ duration, fill: "both", iterations: 1, easing: "cubic-bezier(.16,1,.3,1)" }});
      animation.pause();
      animations.push(animation);
      return animation;
    }}
    {animations}
  </script>
</body>
</html>
"""


def _validated_plan(project: Path, effect_plan_path: Path) -> tuple[dict[str, Any], dict[str, Any], Path]:
    project = project.resolve()
    plan_path = effect_plan_path.resolve()
    try:
        plan_path.relative_to(project / "work" / "effects")
    except ValueError as error:
        raise ValueError("effect plan must stay under project/work/effects") from error
    effect_plan = _load_json(plan_path, "effect plan")
    edit_version = effect_plan.get("edit_plan_version")
    edit_path = project / "work" / "plans" / f"edit_plan.v{edit_version}.json"
    edit_plan = _load_json(edit_path, "edit plan")
    validation = validate_effect_plan(
        edit_plan,
        effect_plan,
        edit_plan_sha256=_canonical_sha256(edit_plan),
    )
    if validation["status"] != "passed":
        raise ValueError("effect plan validation failed: " + json.dumps(validation["issues"], ensure_ascii=False))
    return effect_plan, edit_plan, edit_path


def build_hyperframes_compositions(
    project: Path,
    effect_plan_path: Path,
    output_directory: Path,
    *,
    canvas_width: int = 1920,
    canvas_height: int = 1080,
) -> dict[str, Any]:
    project = project.resolve()
    if canvas_width <= 0 or canvas_height <= 0:
        raise ValueError("HyperFrames canvas dimensions must be positive")
    effect_plan, _, edit_path = _validated_plan(project, effect_plan_path)
    output, output_relative = _strict_job_directory(project, output_directory)
    output.mkdir(parents=False, exist_ok=False)
    effects: list[dict[str, Any]] = []
    for effect in effect_plan["effects"]:
        effect_id = str(effect["effect_id"])
        safe_id = re.sub(r"[^A-Za-z0-9._-]", "-", effect_id)
        effect_directory = output / safe_id
        effect_directory.mkdir()
        composition_path = effect_directory / "index.html"
        composition_path.write_text(
            _composition_html(
                effect,
                effect_plan["style_pack"],
                width=canvas_width,
                height=canvas_height,
            ),
            encoding="utf-8",
            newline="\n",
        )
        effects.append(
            {
                "effect_id": effect_id,
                "intent": effect["intent"],
                "duration_sec": round(
                    float(effect["placement"]["end_sec"])
                    - float(effect["placement"]["start_sec"]),
                    4,
                ),
                "composition": _project_relative(project, composition_path),
                "composition_sha256": _sha256_file(composition_path),
                "output": _project_relative(project, effect_directory / "overlay.mov"),
            }
        )
    result = {
        "schema_version": "1.0",
        "contract_version": "hyperframes-composition-manifest-v1",
        "status": "composed",
        "project_id": effect_plan["project_id"],
        "edit_plan_version": effect_plan["edit_plan_version"],
        "edit_plan_sha256": effect_plan["edit_plan_sha256"],
        "edit_plan_file": _project_relative(project, edit_path),
        "effect_plan": _project_relative(project, effect_plan_path),
        "effect_plan_sha256": _sha256_file(effect_plan_path),
        "effect_payload_sha256": canonical_effect_payload_sha256(effect_plan),
        "job_directory": f"work/effects/{output_relative}",
        "canvas": {"width": canvas_width, "height": canvas_height, "fps": 30},
        "hyperframes": {
            "package": "hyperframes",
            "version": HYPERFRAMES_VERSION,
            "npm_integrity": HYPERFRAMES_NPM_INTEGRITY,
        },
        "effects": effects,
    }
    issues = _schema_issues(result, "hyperframes-composition-manifest.schema.json")
    if issues:
        raise ValueError("composition manifest schema invalid: " + "; ".join(issues))
    _write_new_json(output / "composition-manifest.json", result)
    return result


def _run(command: list[str], *, cwd: Path) -> subprocess.CompletedProcess[str]:
    def invoke(arguments: list[str]) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            arguments,
            cwd=cwd,
            check=False,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
        )

    try:
        completed = invoke(command)
    except OSError as error:
        resolved = shutil.which(command[0])
        if not resolved or resolved == command[0]:
            raise RuntimeError(f"unable to start HyperFrames executable: {command[0]}") from error
        try:
            completed = invoke([resolved, *command[1:]])
        except OSError as retry_error:
            raise RuntimeError(
                f"unable to start HyperFrames executable: {command[0]}"
            ) from retry_error
    if completed.returncode != 0:
        detail = (completed.stderr or completed.stdout or "HyperFrames command failed").strip()
        raise RuntimeError(f"HyperFrames command failed with exit code {completed.returncode}: {detail}")
    return completed


def _hyperframes_command(executable: str, *arguments: str) -> list[str]:
    executable_name = Path(executable).name.lower()
    if executable_name in {"npx", "npx.cmd"}:
        return [executable, "--yes", f"hyperframes@{HYPERFRAMES_VERSION}", *arguments]
    return [executable, *arguments]


def render_hyperframes_compositions(
    project: Path,
    effect_plan_path: Path,
    composition_manifest_path: Path,
    *,
    executable: str = "hyperframes",
    quality: str = "standard",
) -> dict[str, Any]:
    if quality not in {"draft", "standard", "high"}:
        raise ValueError("HyperFrames quality must be draft, standard, or high")
    project = project.resolve()
    effect_plan, _, _ = _validated_plan(project, effect_plan_path)
    manifest_path = composition_manifest_path.resolve()
    try:
        manifest_path.relative_to(project / "work" / "effects")
    except ValueError as error:
        raise ValueError("composition manifest must stay under project/work/effects") from error
    manifest = _load_json(manifest_path, "composition manifest")
    composition_issues = _schema_issues(
        manifest,
        "hyperframes-composition-manifest.schema.json",
    )
    if composition_issues:
        raise ValueError(
            "composition manifest schema invalid: " + "; ".join(composition_issues)
        )
    render_manifest_path = manifest_path.parent / "render-manifest.json"
    if render_manifest_path.exists():
        raise FileExistsError(render_manifest_path)
    if manifest.get("effect_plan_sha256") != _sha256_file(effect_plan_path):
        raise ValueError("composition manifest effect plan SHA-256 changed")
    if manifest.get("effect_payload_sha256") != canonical_effect_payload_sha256(effect_plan):
        raise ValueError("composition manifest effect payload SHA-256 changed")

    version_result = _run(
        _hyperframes_command(executable, "--version"),
        cwd=manifest_path.parent,
    )
    match = VERSION_PATTERN.search((version_result.stdout or "") + "\n" + (version_result.stderr or ""))
    actual_version = match.group(1) if match else ""
    if actual_version != HYPERFRAMES_VERSION:
        raise RuntimeError(
            f"HyperFrames version must be {HYPERFRAMES_VERSION}; found {actual_version or 'unknown'}"
        )

    rendered: list[dict[str, Any]] = []
    for row in manifest.get("effects", []):
        composition = (project / str(row["composition"])).resolve()
        output = (project / str(row["output"])).resolve()
        if output.exists():
            raise FileExistsError(output)
        if _sha256_file(composition) != row.get("composition_sha256"):
            raise ValueError(f"HyperFrames composition changed: {row.get('effect_id')}")
        composition_directory = composition.parent
        _run(
            _hyperframes_command(
                executable,
                "check",
                str(composition_directory),
                "--strict",
            ),
            cwd=composition_directory,
        )
        _run(
            _hyperframes_command(
                executable,
                "render",
                str(composition_directory),
                "--output",
                str(output),
                "--format",
                "mov",
                "--fps",
                "30",
                "--quality",
                quality,
                "--workers",
                "1",
                "--strict",
                "--no-best-effort",
                "--no-browser-gpu",
                "--quiet",
            ),
            cwd=composition_directory,
        )
        if not output.is_file() or output.stat().st_size <= 0:
            raise RuntimeError(f"HyperFrames did not create a non-empty output: {row.get('effect_id')}")
        rendered.append(
            {
                **row,
                "output_size_bytes": output.stat().st_size,
                "output_sha256": _sha256_file(output),
            }
        )

    result = {
        "schema_version": "1.0",
        "contract_version": "hyperframes-render-manifest-v1",
        "status": "rendered",
        "project_id": effect_plan["project_id"],
        "edit_plan_version": effect_plan["edit_plan_version"],
        "edit_plan_sha256": effect_plan["edit_plan_sha256"],
        "effect_plan": _project_relative(project, effect_plan_path),
        "effect_plan_sha256": _sha256_file(effect_plan_path),
        "effect_payload_sha256": canonical_effect_payload_sha256(effect_plan),
        "composition_manifest": _project_relative(project, manifest_path),
        "composition_manifest_sha256": _sha256_file(manifest_path),
        "hyperframes": {
            "executable": Path(executable).name,
            "package": "hyperframes",
            "version": actual_version,
            "npm_integrity": HYPERFRAMES_NPM_INTEGRITY,
        },
        "effects": rendered,
    }
    render_issues = _schema_issues(result, "hyperframes-render-manifest.schema.json")
    if render_issues:
        raise ValueError("render manifest schema invalid: " + "; ".join(render_issues))
    _write_new_json(render_manifest_path, result)
    return result

"""Controller-side checks of saved artifacts; never trust an agent's success report alone."""

import json
import wave
from pathlib import Path

from .analysis import analyze_voice_leading, compare_revisions, validate_score
from .render import sha256
from .store import Project


def verify_project(project: str | Path, require_audio: bool = False) -> dict:
    store = Project(project)
    score = store.read()
    policy = json.loads((store.state / "policy.json").read_text())
    baseline = store.read(policy["baseline"])
    comparison = compare_revisions(baseline, score)
    errors = []
    if validate_score(score)["status"] != "passed":
        errors.append("Invalid structure")
    if not set(policy["protected_tracks"]) <= set(comparison["unchanged_tracks"]):
        errors.append("Protected tracks changed")
    verified = []
    renders = store.path / "renders"
    for file in sorted(renders.rglob("manifest.json")):
        if file.is_symlink() or not file.resolve().is_relative_to(store.path):
            continue
        manifest = json.loads(file.read_text())
        if manifest.get("revision") != score.revision or manifest.get("status") != "passed":
            continue
        required = {"score.json", "score.mid", "score.musicxml", "score.ly", "score.pdf"}
        if require_audio:
            required.add("score.wav")
        if not required <= manifest.get("artifacts", {}).keys():
            continue
        valid = True
        for name, evidence in manifest["artifacts"].items():
            path = file.parent / name
            if (
                Path(name).name != name
                or path.is_symlink()
                or not path.is_file()
                or sha256(path) != evidence["sha256"]
                or path.stat().st_size != evidence["bytes"]
            ):
                valid = False
                break
        if valid:
            if require_audio:
                with wave.open(str(file.parent / "score.wav")) as wav:
                    valid = wav.getnframes() > 0 and any(wav.readframes(wav.getnframes()))
            if valid:
                verified.append(str(file))
    if not verified:
        errors.append("No complete hash-verified render for HEAD")
    style = analyze_voice_leading(score)
    return {
        "status": "failed" if errors else "passed",
        "revision": score.revision,
        "protected_tracks": policy["protected_tracks"],
        "comparison": comparison,
        "style": style,
        "render_manifests": verified,
        "errors": errors,
        "scope": "Score structure, protected content, artifact hashes and audio presence; not artistic quality",
    }

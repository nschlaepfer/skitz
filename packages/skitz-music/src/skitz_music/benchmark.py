"""Direct-response and compiler-feedback conditions, deliberately separate from the agent workflow."""

import hashlib
import json
import re
import subprocess
import time
from pathlib import Path

from .harness import node_command, repository, runtime_environment
from .render import compile_lilypond
from .store import atomic_json


def extract_lilypond(text: str) -> str:
    blocks = re.findall(r"```(?:lilypond|ly)?\s*\n(.*?)```", text, flags=re.DOTALL | re.IGNORECASE)
    if len(blocks) == 1:
        return blocks[0].strip() + "\n"
    if not blocks and text.lstrip().startswith("\\version"):
        return text.strip() + "\n"
    raise ValueError(
        "Expected one LilyPond source block; preserve the original response for review"
    )


def run_benchmark(
    prompt_file: str,
    output_dir: str,
    condition: str,
    model: str,
    max_attempts: int = 3,
    max_output_tokens: int = 6000,
) -> dict:
    if condition not in {"single-response", "compiler-repair"}:
        raise ValueError("Unknown evaluation condition")
    if not 1 <= max_attempts <= 10 or not 256 <= max_output_tokens <= 32000:
        raise ValueError("Invalid evaluation budget")
    if condition == "single-response":
        max_attempts = 1
    prompt = Path(prompt_file).read_text()
    output = Path(output_dir).resolve()
    output.mkdir(parents=True, exist_ok=False)
    (output / "prompt.txt").write_text(prompt)
    report = {
        "condition": condition,
        "model": model,
        "provider": "openai-codex",
        "prompt_sha256": hashlib.sha256(prompt.encode()).hexdigest(),
        "max_attempts": max_attempts,
        "max_output_tokens_per_attempt": max_output_tokens,
        "attempts": [],
        "tools_during_response": False,
        "durable_memory": False,
        "source": "https://aug5th.substack.com/p/the-bach-benchmark",
        "grading": "Compiler success only. Musical correctness requires separate review.",
        "status": "failed",
    }
    request = prompt
    start = time.monotonic()
    for index in range(max_attempts):
        attempt = output / f"attempt-{index + 1:02}"
        attempt.mkdir()
        (attempt / "request.txt").write_text(request)
        process = subprocess.run(
            node_command(repository() / "apps/cli/benchmark-response.ts"),
            input=json.dumps({"prompt": request, "model": model, "maxTokens": max_output_tokens}),
            capture_output=True,
            text=True,
            timeout=180,
            env=runtime_environment(),
        )
        if process.returncode:
            report["error"] = "Subscription response failed; no API-key fallback was attempted"
            atomic_json(output / "report.json", report)
            return report
        response = json.loads(process.stdout)
        atomic_json(attempt / "response.json", response)
        (attempt / "response.txt").write_text(response["text"])
        try:
            if response["stopReason"] in {"error", "aborted", "length"}:
                raise ValueError(f"Incomplete response: {response['stopReason']}")
            compiled = compile_lilypond(extract_lilypond(response["text"]), attempt)
        except (ValueError, RuntimeError) as exc:
            compiled = {"status": "failed", "diagnostics": str(exc)}
        report["attempts"].append(
            {
                "attempt": index + 1,
                "compiler_status": compiled["status"],
                "usage": response["usage"],
                "elapsed_ms": response["elapsedMs"],
            }
        )
        report["first_attempt_passed"] = report["attempts"][0]["compiler_status"] == "passed"
        if compiled["status"] == "passed":
            report["status"] = "passed"
            break
        request = (
            prompt
            + "\n\nYour previous response:\n"
            + response["text"]
            + "\n\nCompiler diagnostics:\n"
            + compiled["diagnostics"][:16000]
            + "\nReturn a corrected complete LilyPond source. This is a repair attempt."
        )
        atomic_json(output / "report.json", report)
    report["elapsed_seconds"] = time.monotonic() - start
    atomic_json(output / "report.json", report)
    return report

"""Skitz's local tools and subscription-backed Prime Agent launcher."""

import argparse
import json
import sys
from pathlib import Path

from .analysis import analyze_voice_leading, inspect_score, validate_score
from .fixtures import chorale_fixture
from .harness import doctor, launch_agent, login
from .importers import import_notation
from .render import compile_lilypond, render_score
from .score import Score
from .service import MusicService
from .store import Project


def main() -> int:
    argv = sys.argv[1:]
    if not argv or argv[0] == "agent":
        try:
            return launch_agent(argv[1:] if argv else [])
        except (ValueError, RuntimeError) as exc:
            print(str(exc), file=sys.stderr)
            return 2
    if argv[0] == "auth" or argv[:2] == ["login", "suno"]:
        from .auth_cli import main as auth_main

        return auth_main(argv[1:] if argv[0] == "auth" else ["login", "suno", *argv[2:]])
    if argv[0] == "suno":
        from .suno_cli import main as suno_main

        return suno_main(argv[1:])
    if argv[0] == "samples":
        from .samples_cli import main as samples_main

        return samples_main(argv[1:])
    parser = argparse.ArgumentParser(
        prog="skitz", description="Editable music with a ChatGPT or Claude agent"
    )
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser(
        "agent", help="Start the music agent (--provider codex|claude, --model <id>)"
    )
    auth = commands.add_parser("login", help="Sign in with your ChatGPT subscription")
    auth.add_argument("--status", action="store_true")
    commands.add_parser("doctor", help="Inspect local tools and subscription setup")
    schema = commands.add_parser("schema", help="Print the versioned score or patch JSON schema")
    schema.add_argument("kind", nargs="?", choices=["score", "patch"], default="score")
    demo = commands.add_parser(
        "demo", help="Create an authored test fixture, not an AI composition"
    )
    demo.add_argument("project")
    create = commands.add_parser("create", help="Create a project from canonical score JSON")
    create.add_argument("project")
    create.add_argument("score")
    create.add_argument("--protect", action="append", default=[])
    imported = commands.add_parser(
        "import", help="Import ABC or MusicXML parts (chords, meter and tempo changes)"
    )
    imported.add_argument("project")
    imported.add_argument("source")
    for name in ("inspect", "validate", "analyze"):
        command = commands.add_parser(name)
        command.add_argument("project")
        command.add_argument("--revision")
    migrate = commands.add_parser(
        "migrate", help="Upgrade a project to the current score schema (also automatic on read)"
    )
    migrate.add_argument("project")
    patch = commands.add_parser("patch")
    patch.add_argument("project")
    patch.add_argument(
        "patch_file",
        help="JSON with expected_revision, edits, allowed_measures, reason (skitz schema patch)",
    )
    render = commands.add_parser("render")
    render.add_argument("project")
    render.add_argument("--revision")
    render.add_argument("--soundfont")
    render.add_argument("--no-audio", action="store_true")
    render.add_argument("--no-engrave", action="store_true")
    compile_command = commands.add_parser(
        "compile", help="Compile direct LilyPond in a restricted worker"
    )
    compile_command.add_argument("source")
    compile_command.add_argument("output")
    bench = commands.add_parser(
        "bench", help="Run direct-LilyPond subscription evaluation with saved attempts"
    )
    bench.add_argument("--prompt-file", required=True)
    bench.add_argument("--output", required=True)
    bench.add_argument("--condition", choices=["single-response", "compiler-repair"], required=True)
    bench.add_argument("--model", default="gpt-5.5")
    bench.add_argument("--max-attempts", type=int, default=3)
    bench.add_argument("--max-output-tokens", type=int, default=6000)
    serve = commands.add_parser("mcp", help="Expose music operations over local MCP stdio")
    serve.add_argument("--workspace", default=".")
    export = commands.add_parser("export")
    export.add_argument("project")
    export.add_argument("destination")
    verify = commands.add_parser(
        "verify", help="Independently check protected content and saved render hashes"
    )
    verify.add_argument("project")
    verify.add_argument("--require-audio", action="store_true")
    commands.add_parser(
        "auth", help="Connect providers: skitz auth login suno|chatgpt, skitz auth", add_help=False
    )
    commands.add_parser(
        "suno", help="Generate songs on your Suno account (see skitz suno --help)", add_help=False
    )
    commands.add_parser(
        "samples", help="Cut audio into loops and one-shots, then layer them", add_help=False
    )
    args = parser.parse_args(argv)
    try:
        if args.command == "login":
            return login(args.status)
        if args.command == "doctor":
            result = doctor()
        elif args.command == "schema":
            from .patch import ScorePatch

            result = (Score if args.kind == "score" else ScorePatch).model_json_schema()
        elif args.command == "demo":
            result = Project(args.project).create(chorale_fixture(), ["soprano"])
        elif args.command == "create":
            result = Project(args.project).create(
                Score.model_validate_json(Path(args.score).read_text()), args.protect
            )
        elif args.command == "import":
            result = Project(args.project).create(import_notation(args.source))
        elif args.command in {"inspect", "validate", "analyze"}:
            operation = {
                "inspect": inspect_score,
                "validate": validate_score,
                "analyze": analyze_voice_leading,
            }[args.command]
            result = operation(Project(args.project).read(args.revision))
        elif args.command == "migrate":
            result = Project(args.project).migrate()
        elif args.command == "patch":
            from .patch import ScorePatch

            request = ScorePatch.model_validate_json(Path(args.patch_file).read_text())
            result = Project(args.project).apply_score_patch(
                request.expected_revision, request.edits, request.allowed_measures, request.reason
            )
        elif args.command == "render":
            project = Project(args.project)
            result = render_score(
                project.read(args.revision),
                project.path / "renders",
                args.soundfont,
                not args.no_audio,
                not args.no_engrave,
            )
        elif args.command == "compile":
            result = compile_lilypond(Path(args.source).read_text(), args.output)
        elif args.command == "bench":
            from .benchmark import run_benchmark

            result = run_benchmark(
                args.prompt_file,
                args.output,
                args.condition,
                args.model,
                args.max_attempts,
                args.max_output_tokens,
            )
        elif args.command == "mcp":
            from .mcp_server import create_server

            create_server(args.workspace).run(transport="stdio")
            return 0
        elif args.command == "export":
            result = MusicService(Path.cwd()).export_project(args.project, args.destination)
        elif args.command == "verify":
            from .verification import verify_project

            result = verify_project(args.project, args.require_audio)
        else:
            parser.error("Unknown command")
        print(json.dumps(result, indent=2))
        return 1 if result.get("status") == "failed" else 0
    except (ValueError, OSError, RuntimeError) as exc:
        print(json.dumps({"status": "failed", "error": str(exc)}), file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())

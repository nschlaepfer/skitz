"""`skitz suno ...`: generate songs on the user's own Suno account.

Prints one JSON object to stdout; progress goes to stderr. Exit codes: 0 ok, 1 usage,
2 API error, 3 cookie missing or expired, 4 captcha required, 5 out of credits,
6 timed out (wait again with the same ids), 7 audio must be downloaded on suno.com.
Codes 3-5 and 7 need a person to act.

Suno builds downloads in the browser, so for songs it no longer serves, `download`
(and `--out`) take the files from ~/Downloads or ~/.skitz/suno/inbox, matched by the
clip id Suno embeds in each file. `--wait-for-browser` opens the song pages and waits
for the user to click Download; `inbox` lists the Suno files found.
"""

import argparse
import json
import sys
from pathlib import Path

import httpx

from .suno import (
    DEFAULT_MODEL,
    MODELS,
    SunoClient,
    SunoError,
    build_payload,
    download_stems,
    inbox_listing,
    request_record,
    slim,
    tempo_from_downbeats,
)
from .suno_inbox import remember_request


def parser() -> argparse.ArgumentParser:
    root = argparse.ArgumentParser(
        prog="skitz suno",
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    commands = root.add_subparsers(dest="command", required=True)
    login = commands.add_parser("login", help="Connect your Suno account (guided)")
    login.add_argument(
        "cookie",
        nargs="?",
        help="__client value or cookie header; - reads stdin; omit to be guided",
    )
    commands.add_parser("whoami", help="Check the session and show credits")
    models = commands.add_parser("models", help="List model aliases")
    models.add_argument("--live", action="store_true", help="Ask Suno which models you can use")

    def waiting(command: argparse.ArgumentParser) -> None:
        command.add_argument("--timeout", type=float, default=600)
        command.add_argument("--interval", type=float, default=5)

    def browser(command: argparse.ArgumentParser) -> None:
        command.add_argument(
            "--wait-for-browser",
            action="store_true",
            help="Open the song pages and wait for the files you download there",
        )
        command.add_argument(
            "--no-open", action="store_true", help="With --wait-for-browser: don't open pages"
        )

    generate = commands.add_parser("generate", help="Start a song (2 clips; spends credits)")
    generate.add_argument("-d", "--description", help="Simple mode: Suno writes the lyrics")
    generate.add_argument("-l", "--lyrics", help="Custom mode: lyrics with [Verse]/[Chorus] tags")
    generate.add_argument("--lyrics-file")
    generate.add_argument("-t", "--tags", help="Custom mode: style, e.g. 'lofi, female vocals'")
    generate.add_argument("--negative-tags")
    generate.add_argument("--title")
    generate.add_argument("-i", "--instrumental", action="store_true")
    generate.add_argument("-m", "--model", default=DEFAULT_MODEL)
    generate.add_argument(
        "--bpm", type=float, help="Ask for this tempo and record it for `skitz samples`"
    )
    generate.add_argument("-w", "--wait", action="store_true", help="Block until clips finish")
    generate.add_argument("-o", "--out", help="Wait, then save mp3s and a manifest here")
    generate.add_argument("--dry-run", action="store_true", help="Print the payload only")
    waiting(generate)
    browser(generate)

    status = commands.add_parser("status", help="Show the current state of clips")
    status.add_argument("ids", nargs="+")
    wait = commands.add_parser("wait", help="Block until clips finish")
    wait.add_argument("ids", nargs="+")
    wait.add_argument("-o", "--out")
    waiting(wait)
    browser(wait)
    download = commands.add_parser(
        "download", help="Save finished clips (from Suno, or from your downloads on suno.com)"
    )
    download.add_argument("ids", nargs="+")
    download.add_argument("-o", "--out", default=".")
    download.add_argument("--timeout", type=float, default=600)
    browser(download)
    commands.add_parser("inbox", help="List Suno files found in ~/Downloads and the inbox")
    stems = commands.add_parser(
        "stems", help="List or download stems made on suno.com (Edit > Get Stems)"
    )
    stems.add_argument("clip_id")
    stems.add_argument("-o", "--out", help="Save one variant's stems here")
    stems.add_argument("--variant", type=int, default=1, help="Suno makes 2 of each stem (1 or 2)")
    stems.add_argument("--only", nargs="+", help="Only these stems, e.g. --only drums bass")
    beats = commands.add_parser("downbeats", help="Suno's beat grid for a clip")
    beats.add_argument("clip_id")
    lyrics = commands.add_parser("lyrics", help="Have Suno write lyrics (no credits)")
    lyrics.add_argument("prompt")
    lyrics.add_argument("--timeout", type=float, default=60)
    return root


def run(args: argparse.Namespace, transport: httpx.BaseTransport | None = None) -> dict:
    if args.command == "models":
        if args.live:
            return {"default": DEFAULT_MODEL, "live": SunoClient(transport=transport).live_models()}
        return {"default": DEFAULT_MODEL, "aliases": MODELS}
    if args.command == "login":
        from .auth_cli import login_suno

        value = None if args.cookie in (None, "-") else args.cookie
        return login_suno(value, transport)
    if args.command == "generate":
        lyrics = Path(args.lyrics_file).read_text() if args.lyrics_file else args.lyrics
        payload = build_payload(
            args.description,
            lyrics,
            args.tags,
            args.title,
            args.negative_tags,
            args.instrumental,
            args.model,
            args.bpm,
        )
        if args.dry_run:
            return {"status": "dry_run", "payload": payload}
        client = SunoClient(transport=transport)
        print(f"[suno] generating with {payload['mv']}", file=sys.stderr)
        ids = [clip["id"] for clip in client.generate(payload)]
        request = request_record(payload, args.bpm)
        remember_request(ids, request)
        if not (args.wait or args.out):
            return {"status": "submitted", "ids": ids}
        return finish(client, ids, args, request)
    if args.command == "inbox":
        return inbox_listing()

    client = SunoClient(transport=transport)
    if args.command == "whoami":
        billing = client.billing()
        return {"session_id": client.session_id, **billing}
    if args.command == "status":
        return {"clips": [slim(clip) for clip in client.feed(args.ids)]}
    if args.command == "wait":
        return finish(client, args.ids, args)
    if args.command == "download":
        clips = client.feed(args.ids)
        missing = [clip["id"] for clip in clips if not clip.get("audio_url")]
        if missing:
            raise SunoError("not_ready", "Some clips have no audio yet; wait first.", ids=missing)
        return client.download(
            clips, Path(args.out), None, args.wait_for_browser, args.timeout, not args.no_open
        )
    if args.command == "stems":
        out = Path(args.out) if args.out else None
        return download_stems(client, args.clip_id, out, args.variant, args.only)
    if args.command == "downbeats":
        data = client.downbeats(args.clip_id)
        return {"clip_id": args.clip_id, **tempo_from_downbeats(data), "downbeats": data}
    if args.command == "lyrics":
        return client.lyrics(args.prompt, args.timeout)
    raise SunoError("usage", f"Unknown command {args.command}")


def finish(
    client: SunoClient, ids: list[str], args: argparse.Namespace, payload: dict | None = None
) -> dict:
    clips = client.wait(ids, args.timeout, args.interval)
    result = {"status": "complete", "ids": ids, "clips": [slim(clip) for clip in clips]}
    if args.out:
        result.update(
            client.download(
                clips,
                Path(args.out),
                payload,
                args.wait_for_browser,
                args.timeout,
                not args.no_open,
            )
        )
    if any(clip.get("status") == "error" for clip in clips):
        raise SunoError("generation_failed", "One or more clips failed.", **result)
    return result


def main(argv: list[str], transport: httpx.BaseTransport | None = None) -> int:
    args = parser().parse_args(argv)
    try:
        print(json.dumps(run(args, transport), indent=2))
        return 0
    except SunoError as error:
        print(json.dumps(error.report(), indent=2))
        return error.exit_code
    except httpx.HTTPError as error:
        print(json.dumps({"status": "failed", "error_kind": "network_error", "error": str(error)}))
        return 2
    except OSError as error:
        print(json.dumps({"status": "failed", "error_kind": "usage", "error": str(error)}))
        return 1

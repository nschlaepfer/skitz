"""`skitz samples ...`: cut Suno clips (or any audio) into loops and one-shots, then layer.

Every command prints one JSON object and writes WAVs plus a manifest. Needs ffmpeg.
Typical flow:

  skitz suno generate -i -t "dusty boom bap drums" --bpm 90 --out songs/drums
  skitz samples stems songs/drums/<clip>.mp3 --drumkit --out stems/drums
  skitz samples loops songs/drums/<clip>.mp3 --bars 2 --out samples/drums
  skitz samples hits songs/drums/<clip>.mp3 --out samples/drum-hits
  skitz samples layer out/beat.wav --bpm 90 --bars 8 --place samples/drums/<loop>.wav:0:x4/2
  skitz samples stems songs/<song>.mp3 --out stems/song
  skitz samples transcribe stems/song/bass.wav --out projects/song-bass
"""

import argparse
import json
import re
from pathlib import Path

from . import samples
from .transcribe import GRIDS, LINES, transcribe

PLACE = re.compile(
    r"^(?P<sample>.+?):(?P<at>[\d.]+)(?P<unit>[bsq]?)"
    r"(?::x(?P<repeat>\d+)/(?P<every>[\d.]+))?(?::(?P<gain>-?[\d.]+)dB)?$"
)
UNITS = {"": "bar", "b": "bar", "q": "beat", "s": "second"}


def parse_place(text: str) -> dict:
    """SAMPLE:AT[b|q|s][:xREPEAT/EVERY][:GAINdB], e.g. kick.wav:0q:x16/1:-3dB."""
    match = PLACE.match(text)
    if not match:
        raise argparse.ArgumentTypeError(
            f"Bad placement {text!r}; use SAMPLE:AT[b|q|s][:xREPEAT/EVERY][:GAINdB]"
        )
    placement = {
        "sample": match["sample"],
        "at": float(match["at"]),
        "unit": UNITS[match["unit"]],
    }
    if match["repeat"]:
        placement.update(repeat=int(match["repeat"]), every=float(match["every"]))
    if match["gain"]:
        placement["gain_db"] = float(match["gain"])
    return placement


def parser() -> argparse.ArgumentParser:
    root = argparse.ArgumentParser(
        prog="skitz samples",
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    commands = root.add_subparsers(dest="command", required=True)
    info = commands.add_parser("info", help="Length, peak, recorded and estimated BPM")
    info.add_argument("source")

    loops = commands.add_parser("loops", help="Cut into back-to-back bar-length loops")
    loops.add_argument("source")
    loops.add_argument("-o", "--out", required=True)
    loops.add_argument("--bpm", type=float, help="Defaults to the BPM recorded by suno --bpm")
    loops.add_argument("--bars", type=int, default=1)
    loops.add_argument("--beats-per-bar", type=int, default=4)
    loops.add_argument("--offset", type=float, default=0.0, help="Seconds before bar 1")
    loops.add_argument("--every", type=float, help="Loop length in seconds instead of bars")
    loops.add_argument("--max", type=int, default=64)
    loops.add_argument("--normalize", action="store_true")

    hits = commands.add_parser("hits", help="Detect transients and cut one-shots")
    hits.add_argument("source")
    hits.add_argument("-o", "--out", required=True)
    hits.add_argument("--sensitivity", type=float, default=0.3, help="0-1; higher finds fewer")
    hits.add_argument("--max", type=int, default=32)
    hits.add_argument("--max-length", type=float, default=1.0, help="Seconds per hit")
    hits.add_argument("--min-gap", type=float, default=0.08, help="Seconds between hits")
    hits.add_argument("--no-normalize", action="store_true")

    stems = commands.add_parser("stems", help="Split audio into stems on the local GPU")
    stems.add_argument("source")
    stems.add_argument("-o", "--out", required=True)
    stems.add_argument(
        "-m", "--model", default="stems",
        help="stems (6, default), 4stem, vocals, drumkit, or an audio-separator model file",
    )  # fmt: skip
    stems.add_argument(
        "--drumkit", action="store_true", help="Also split drums into kick/snare/toms/hh/..."
    )
    stems.add_argument("--models", action="store_true", help="List presets and exit")

    notes = commands.add_parser(
        "transcribe", help="Turn audio (e.g. a stem) into an editable score project"
    )
    notes.add_argument("source")
    notes.add_argument("-o", "--out", required=True, help="New project folder")
    notes.add_argument(
        "--stem", help="vocals, bass, guitar, piano, ... (default: from the file name)"
    )
    notes.add_argument("--bpm", type=float, help="Default: recorded or Suno BPM, else estimated")
    notes.add_argument("--offset", type=float, help="Seconds to the first downbeat (bar 1)")
    notes.add_argument(
        "--downbeats", help="JSON saved from `skitz suno downbeats <id>`: bpm, offset, meter"
    )
    notes.add_argument("--meter", help="Default 4/4, or the downbeats' beats per bar")
    notes.add_argument(
        "--grid", type=int, default=16, choices=GRIDS,
        help="Shortest note value: 4, 8, 16 (default) or 32; 12 and 24 are triplets",
    )  # fmt: skip
    notes.add_argument(
        "--tracks", type=int, default=1, help="Split chords into up to N monophonic tracks"
    )
    notes.add_argument(
        "--line", choices=LINES,
        help="Which overlapping note wins (default: bottom for bass, loudest for vocals, else top)",
    )  # fmt: skip
    notes.add_argument("--key", help='Key for spelling, e.g. "g minor" (default: estimated)')
    notes.add_argument("--title")
    notes.add_argument("--program", type=int, help="General MIDI program (default by stem)")
    notes.add_argument("--onset-threshold", type=float, default=0.5, help="basic-pitch, 0-1")
    notes.add_argument("--frame-threshold", type=float, default=0.3, help="basic-pitch, 0-1")
    notes.add_argument(
        "--min-note-ms", type=float, help="basic-pitch; default 3/4 of a grid step, max 127.7"
    )
    notes.add_argument(
        "--join-repeats", action="store_true",
        help="Merge same-pitch notes that touch (vibrato split into repeats)",
    )  # fmt: skip

    cut = commands.add_parser("slice", help="Cut one region by seconds")
    cut.add_argument("source")
    cut.add_argument("start", type=float)
    cut.add_argument("end", type=float)
    cut.add_argument("-o", "--out", required=True)
    cut.add_argument("--name")
    cut.add_argument("--normalize", action="store_true")

    mix = commands.add_parser("layer", help="Mix samples onto a timeline into a new WAV")
    mix.add_argument("output")
    mix.add_argument(
        "--place",
        action="append",
        type=parse_place,
        default=[],
        help="SAMPLE:AT[b|q|s][:xREPEAT/EVERY][:GAINdB]; b=bar (default), q=beat, s=second",
    )
    mix.add_argument("--plan", help="JSON file with a list of placements")
    mix.add_argument("--bpm", type=float)
    mix.add_argument("--beats-per-bar", type=int, default=4)
    mix.add_argument("--bars", type=float, help="Total length in bars")
    mix.add_argument("--seconds", type=float, help="Total length in seconds")
    mix.add_argument("--base", help="Audio to mix under the samples, e.g. a score.wav render")
    mix.add_argument("--base-gain-db", type=float, default=0.0)
    return root


def run(args: argparse.Namespace) -> dict:
    if args.command == "info":
        return samples.info(args.source)
    if args.command == "loops":
        return samples.chop_loops(
            args.source,
            args.out,
            args.bpm,
            args.bars,
            args.beats_per_bar,
            args.offset,
            args.every,
            args.max,
            normalize=args.normalize,
        )
    if args.command == "hits":
        return samples.chop_hits(
            args.source,
            args.out,
            args.sensitivity,
            args.max,
            args.max_length,
            args.min_gap,
            not args.no_normalize,
        )
    if args.command == "stems":
        from .separate import PRESETS, separate

        if args.models:
            return {"presets": PRESETS}
        return separate(args.source, args.out, args.model, args.drumkit)
    if args.command == "transcribe":
        return transcribe(
            args.source,
            args.out,
            stem=args.stem,
            bpm=args.bpm,
            offset=args.offset,
            meter=args.meter,
            grid=args.grid,
            tracks=args.tracks,
            line=args.line,
            key=args.key,
            title=args.title,
            program=args.program,
            downbeats=args.downbeats,
            onset_threshold=args.onset_threshold,
            frame_threshold=args.frame_threshold,
            min_note_ms=args.min_note_ms,
            join_repeats=args.join_repeats,
        )
    if args.command == "slice":
        return samples.slice_sample(
            args.source, args.out, args.start, args.end, args.name, normalize=args.normalize
        )
    placements = list(args.place)
    if args.plan:
        placements += json.loads(Path(args.plan).read_text())
    if not placements and not args.base:
        raise ValueError("Give at least one --place, a --plan or a --base")
    return samples.layer(
        args.output,
        placements,
        args.bpm,
        args.beats_per_bar,
        args.bars,
        args.seconds,
        args.base,
        args.base_gain_db,
    )


def main(argv: list[str]) -> int:
    args = parser().parse_args(argv)
    try:
        print(json.dumps(run(args), indent=2))
        return 0
    except (ValueError, OSError, RuntimeError, KeyError) as error:
        print(json.dumps({"status": "failed", "error": str(error)}, indent=2))
        return 1

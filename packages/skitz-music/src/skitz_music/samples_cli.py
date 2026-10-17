"""`skitz samples ...`: cut Suno clips (or any audio) into loops and one-shots, fit them
to a tempo and key, mix them with effects, and export stems and MIDI for a DAW.

Every command prints one JSON object and writes WAVs plus a manifest. Needs ffmpeg;
fit and effects use pedalboard (the skitz-music `fx` extra). Typical flow:

  skitz suno generate -i -t "dusty boom bap drums" --bpm 90 --out songs/drums
  skitz samples analyze songs/keys/<clip>.mp3            # estimated BPM, key, chords
  skitz samples stems songs/drums/<clip>.mp3 --drumkit --out stems/drums
  skitz samples loops songs/drums/<clip>.mp3 --bars 2 --out samples/drums
  skitz samples hits songs/drums/<clip>.mp3 --out samples/drum-hits
  skitz samples fit songs/keys/<clip>.mp3 --bpm 90 --key "A minor" --out samples/keys
  skitz samples layer out/beat.wav --bpm 90 --bars 8 --place samples/drums/<loop>.wav:0:x4/2 \\
    --fx 1:hp=40,comp=-18/4 --master limit
  skitz samples export out/beat --bpm 90 --bars 8 --plan plan.json   # stems + MIDI

Effect chains are KEY=VALUE pairs joined by commas, values split by `/`:
  hp=HZ[/SLOPE]  lp=HZ[/SLOPE]  lowshelf=HZ/DB[/Q]  highshelf=HZ/DB[/Q]  peak=HZ/DB[/Q]
  comp=THRESHOLD[/RATIO/ATTACK_MS/RELEASE_MS/MAKEUP]  delay=TIME[q|s][/FEEDBACK/MIX]
  reverb=WET[/ROOM/DAMPING/WIDTH]  gain=DB  pan=-1..1  limit[=CEILING/RELEASE_MS]
"""

import argparse
import json
import re
from pathlib import Path

from . import samples

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

    analyze = commands.add_parser("analyze", help="Estimate tempo, key/mode and chords")
    analyze.add_argument("source")
    analyze.add_argument(
        "--bpm", type=float, help="Chord grid tempo; defaults to recorded/estimated"
    )
    analyze.add_argument("--beats-per-bar", type=int, default=4)
    analyze.add_argument("--offset", type=float, default=0.0, help="Seconds before bar 1")
    analyze.add_argument("--chord-beats", type=float, help="Beats per chord window (default a bar)")

    fit = commands.add_parser("fit", help="Time-stretch to a BPM and/or pitch-shift to a key")
    fit.add_argument("source")
    fit.add_argument("-o", "--out", required=True)
    fit.add_argument("--bpm", type=float, help="Target tempo")
    fit.add_argument("--key", help="Target key, e.g. 'A minor', Am, F#, 'Bb major', 8A")
    fit.add_argument(
        "--from-bpm", type=float, help="Source tempo (default recorded, else estimated)"
    )
    fit.add_argument("--from-key", help="Source key (default estimated)")
    fit.add_argument("--semitones", type=float, help="Shift by semitones instead of --key")
    fit.add_argument("--engine", choices=["auto", "pedalboard", "rubberband"], default="auto")
    fit.add_argument("--name", help="Output file name without .wav")
    fit.add_argument("--normalize", action="store_true")

    fx = commands.add_parser("fx", help="Run an effect chain over one file")
    fx.add_argument("source")
    fx.add_argument("output")
    fx.add_argument("--chain", required=True, help="e.g. hp=80,comp=-20/3,reverb=0.15,limit")
    fx.add_argument("--bpm", type=float, help="For delay times in beats (q)")
    fx.add_argument("--tail", type=float, default=0.0, help="Seconds of silence to ring out into")

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

    cut = commands.add_parser("slice", help="Cut one region by seconds")
    cut.add_argument("source")
    cut.add_argument("start", type=float)
    cut.add_argument("end", type=float)
    cut.add_argument("-o", "--out", required=True)
    cut.add_argument("--name")
    cut.add_argument("--normalize", action="store_true")

    mix = commands.add_parser("layer", help="Mix samples onto a timeline into a new WAV")
    mix.add_argument("output")
    add_plan_arguments(mix)

    export = commands.add_parser(
        "export", help="Write a layer plan as a mix, 32-bit stems and MIDI for a DAW"
    )
    export.add_argument("output_dir")
    add_plan_arguments(export)
    export.add_argument("--name", default="mix", help="Mix file name without .wav")
    return root


def parse_fx(text: str) -> tuple[int, dict]:
    """N:CHAIN, e.g. 2:hp=120,reverb=0.2 for the second placement."""
    number, _, chain = text.partition(":")
    if not number.isdigit() or int(number) < 1 or not chain:
        raise argparse.ArgumentTypeError(f"Bad --fx {text!r}; use N:CHAIN, e.g. 1:hp=120,pan=-0.3")
    try:
        return int(number), samples.parse_chain(chain)
    except ValueError as error:
        raise argparse.ArgumentTypeError(str(error)) from error


def add_plan_arguments(command: argparse.ArgumentParser) -> None:
    command.add_argument(
        "--place",
        action="append",
        type=parse_place,
        default=[],
        help="SAMPLE:AT[b|q|s][:xREPEAT/EVERY][:GAINdB]; b=bar (default), q=beat, s=second",
    )
    command.add_argument("--plan", help="JSON file with a list of placements")
    command.add_argument(
        "--fx",
        action="append",
        type=parse_fx,
        default=[],
        help="N:CHAIN effects for placement N (1-based, --place first, then --plan)",
    )
    command.add_argument("--master", help="Effect chain for the summed mix, e.g. comp=-12/2,limit")
    command.add_argument("--bpm", type=float)
    command.add_argument("--beats-per-bar", type=int, default=4)
    command.add_argument("--bars", type=float, help="Total length in bars")
    command.add_argument("--seconds", type=float, help="Total length in seconds")
    command.add_argument("--base", help="Audio to mix under the samples, e.g. a score.wav render")
    command.add_argument("--base-gain-db", type=float, default=0.0)


def plan_from(args: argparse.Namespace) -> list[dict]:
    placements = list(args.place)
    if args.plan:
        placements += json.loads(Path(args.plan).read_text())
    if not placements and not args.base:
        raise ValueError("Give at least one --place, a --plan or a --base")
    for number, chain in args.fx:
        if number > len(placements):
            raise ValueError(f"--fx {number} but there are only {len(placements)} placements")
        existing = placements[number - 1].get("fx") or {}
        if isinstance(existing, str):
            existing = samples.parse_chain(existing)
        placements[number - 1] = {**placements[number - 1], "fx": {**existing, **chain}}
    return placements


def run(args: argparse.Namespace) -> dict:
    if args.command == "info":
        return samples.info(args.source)
    if args.command == "analyze":
        return samples.analyze(
            args.source, args.bpm, args.beats_per_bar, args.offset, args.chord_beats
        )
    if args.command == "fit":
        return samples.fit_sample(
            args.source,
            args.out,
            args.bpm,
            args.key,
            args.from_bpm,
            args.from_key,
            args.semitones,
            args.engine,
            args.name,
            args.normalize,
        )
    if args.command == "fx":
        return samples.apply_fx(args.source, args.output, args.chain, args.bpm, args.tail)
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
    if args.command == "slice":
        return samples.slice_sample(
            args.source, args.out, args.start, args.end, args.name, normalize=args.normalize
        )
    placements = plan_from(args)
    plan = (args.bpm, args.beats_per_bar, args.bars, args.seconds, args.base, args.base_gain_db)
    if args.command == "export":
        return samples.export_plan(args.output_dir, placements, *plan, args.master, args.name)
    return samples.layer(args.output, placements, *plan, args.master)


def main(argv: list[str]) -> int:
    args = parser().parse_args(argv)
    try:
        print(json.dumps(run(args), indent=2))
        return 0
    except (ValueError, OSError, RuntimeError, KeyError) as error:
        print(json.dumps({"status": "failed", "error": str(error)}, indent=2))
        return 1

"""Conservative ABC/MusicXML import into the bounded score model. Anything the model cannot
hold exactly (simultaneous voices in one part, partial chord ties, pickups, changes inside
a measure, other articulations) fails explicitly instead of being dropped."""

import re
from fractions import Fraction
from pathlib import Path

from music21 import articulations, chord, converter, harmony, key, meter, note, stream, tempo

from .score import Event, MeasureGrid, MeterChange, Score, TempoChange, Track


def _changes(parts: list, kind, value, label: str) -> dict[Fraction, object]:
    """Offset -> value for marks of one kind, which every part must agree on."""
    found: dict[Fraction, object] = {}
    for part in parts:
        for item in part.flatten().getElementsByClass(kind):
            result = value(item)
            if result is None:
                continue
            offset = Fraction(item.offset)
            if found.setdefault(offset, result) != result:
                raise ValueError(f"Parts disagree on the {label} at quarter {offset}")
    return dict(sorted(found.items()))


def _meter_map(changes: dict[Fraction, str]) -> tuple[MeterChange, ...]:
    if not changes or next(iter(changes)) != 0:
        raise ValueError("Import needs an explicit meter at the start")
    result: list[MeterChange] = []
    for offset, value in changes.items():
        if result:
            grid = MeasureGrid(tuple(result))
            if not grid.is_boundary(offset):
                raise ValueError(f"Meter change at quarter {offset} is not on a barline")
            if value == result[-1].meter:
                continue
            result.append(MeterChange(measure=grid.measure_at(offset), meter=value))
        else:
            result.append(MeterChange(measure=1, meter=value))
    return tuple(result)


def _tempo_map(changes: dict[Fraction, int], grid: MeasureGrid) -> tuple[TempoChange, ...]:
    result = [TempoChange(measure=1, bpm=changes.pop(Fraction(0), 90))]
    for offset, value in changes.items():
        if not grid.is_boundary(offset):
            raise ValueError(f"Tempo change at quarter {offset} is not on a barline")
        if value != result[-1].bpm:
            result.append(TempoChange(measure=grid.measure_at(offset), bpm=value))
    return tuple(result)


def _pitches(item) -> tuple[list[str], str | None]:
    if isinstance(item, harmony.ChordSymbol):
        raise ValueError("Chord symbols are unsupported; remove harmony labels before import")
    if isinstance(item, chord.Chord):
        ties = {n.tie.type if n.tie else None for n in item.notes}
        if len(ties) > 1:
            raise ValueError("Chords whose notes are tied differently are unsupported")
        return [p.nameWithOctave for p in item.pitches], ties.pop()
    if isinstance(item, note.Note):
        return [item.pitch.nameWithOctave], item.tie.type if item.tie else None
    if isinstance(item, note.Rest):
        return [], None
    raise ValueError("Unpitched and percussion notes are unsupported")


def _abc_body_changes(path: Path) -> bool:
    """music21 drops or misreads key, meter and tempo fields inside an ABC tune body."""
    text = path.read_text(errors="replace")
    header = re.search(r"^K:.*$", text, re.M)
    body = text[header.end() :] if header else ""
    return bool(re.search(r"^\s*[KMQ]:|\[[KMQ]:", body, re.M))


ARTICULATIONS = {
    articulations.Staccato: "staccato",
    articulations.Tenuto: "tenuto",
    articulations.Accent: "accent",
}


def _articulation(item) -> str | None:
    names = [ARTICULATIONS.get(type(mark)) for mark in item.articulations]
    if len(names) > 1 or None in names:
        raise ValueError("Only one staccato, tenuto or accent per note can be imported")
    return names[0] if names else None


def import_notation(path: str | Path) -> Score:
    path = Path(path)
    if path.suffix.lower() not in {".abc", ".musicxml", ".xml"}:
        raise ValueError("Import supports ABC and uncompressed MusicXML, not arbitrary LilyPond")
    if path.suffix.lower() == ".abc" and _abc_body_changes(path):
        raise ValueError(
            "Key, meter or tempo changes inside an ABC tune are unsupported; import MusicXML"
        )
    parsed = converter.parse(path, forceSource=True)
    if isinstance(parsed, stream.Opus):
        raise ValueError("Select one tune; collections are not supported")
    keys = {item.sharps for item in parsed.recurse().getElementsByClass(key.KeySignature)}
    if len(keys) > 1:
        raise ValueError("Key changes are unsupported")
    if parsed.recurse().getElementsByClass(stream.Voice):
        raise ValueError("Split simultaneous voices into separate parts before import")
    parts = list(parsed.parts) or [parsed]
    for part in parts:
        measures = list(part.getElementsByClass(stream.Measure))
        if measures and measures[0].paddingLeft:
            raise ValueError("Pickup (anacrusis) measures are unsupported")
    meter_map = _meter_map(_changes(parts, meter.TimeSignature, lambda ts: ts.ratioString, "meter"))
    tempo_map = _tempo_map(
        _changes(
            parts,
            tempo.MetronomeMark,
            lambda mark: round(mark.getQuarterBPM()) if mark.number is not None else None,
            "tempo",
        ),
        MeasureGrid(meter_map),
    )
    tracks = []
    for index, part in enumerate(parts):
        events = []
        for event_index, item in enumerate(part.flatten().notesAndRests):
            if item.duration.isGrace:
                raise ValueError("Grace notes require explicit conversion")
            pitches, tie = _pitches(item)
            events.append(
                Event(
                    id=f"t{index + 1}_e{event_index + 1}",
                    offset=str(Fraction(item.offset)),
                    duration=str(Fraction(item.duration.quarterLength)),
                    pitches=tuple(pitches),
                    tie=tie,
                    articulation=_articulation(item),
                )
            )
        inst = part.getInstrument(returnDefault=True)
        tracks.append(
            Track(
                id=f"track_{index + 1}",
                name=part.partName or f"Track {index + 1}",
                program=inst.midiProgram or 0,
                events=tuple(events),
            )
        )
    signature = next(iter(parsed.recurse().getElementsByClass(key.KeySignature)), None)
    inferred_key = (
        signature
        if isinstance(signature, key.Key)
        else (signature.asKey() if signature else key.Key("C"))
    )
    return Score(
        title=(parsed.metadata and parsed.metadata.bestTitle) or path.stem,
        meter_map=meter_map,
        tempo_map=tempo_map,
        key=f"{inferred_key.tonic.name} {inferred_key.mode}",
        tracks=tuple(tracks),
    )

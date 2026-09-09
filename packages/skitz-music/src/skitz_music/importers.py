"""Conservative ABC/MusicXML import into the explicitly bounded v1 score model."""

from fractions import Fraction
from pathlib import Path

from music21 import chord, converter, key, meter, note, stream, tempo

from .score import Event, Score, Track


def import_notation(path: str | Path) -> Score:
    path = Path(path)
    if path.suffix.lower() not in {".abc", ".musicxml", ".xml"}:
        raise ValueError("Import supports ABC and uncompressed MusicXML, not arbitrary LilyPond")
    parsed = converter.parse(path, forceSource=True)
    if isinstance(parsed, stream.Opus):
        raise ValueError("Select one tune; collections are not supported")
    meters = {item.ratioString for item in parsed.recurse().getElementsByClass(meter.TimeSignature)}
    tempi = {
        int(item.number)
        for item in parsed.recurse().getElementsByClass(tempo.MetronomeMark)
        if item.number is not None
    }
    keys = {item.sharps for item in parsed.recurse().getElementsByClass(key.KeySignature)}
    if len(meters) != 1 or len(tempi) > 1 or len(keys) > 1:
        raise ValueError(
            "V1 needs one explicit meter and fixed tempo/key; changing maps are unsupported"
        )
    if parsed.recurse().getElementsByClass(stream.Voice):
        raise ValueError("Split simultaneous voices into separate monophonic parts before import")
    if parsed.recurse().getElementsByClass(chord.Chord):
        raise ValueError("Split chords into separate monophonic tracks before import")
    parts = list(parsed.parts) or [parsed]
    tracks = []
    for index, part in enumerate(parts):
        events = []
        for event_index, item in enumerate(part.flatten().notesAndRests):
            if item.duration.isGrace or item.articulations:
                raise ValueError(
                    "Grace notes and imported articulations require explicit conversion"
                )
            events.append(
                Event(
                    id=f"t{index + 1}_e{event_index + 1}",
                    offset=str(Fraction(item.offset)),
                    duration=str(Fraction(item.duration.quarterLength)),
                    pitch=item.pitch.nameWithOctave if isinstance(item, note.Note) else None,
                    tie=item.tie.type if item.tie else None,
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
        title=parsed.metadata.title if parsed.metadata and parsed.metadata.title else path.stem,
        meter=next(iter(meters)),
        tempo=next(iter(tempi), 90),
        key=f"{inferred_key.tonic.name} {inferred_key.mode}",
        tracks=tuple(tracks),
    )

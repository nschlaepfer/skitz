X: 1
T: Cooley's
M: 4/4
L: 1/8
R: reel
K: Em
V: Melody
|:D2|EB{c}BA B2 EB|~B2 AB dBAG|FDAD BDAD|FDAD dAFD|
EBBA B2 EB|B2 AB defg|afe^c dBAF|DEFD E2:|
|:gf|eB B2 efge|eB B2 gedB|A2 FA DAFA|A2 FA defg|
eB B2 eBgB|eB B2 defg|afe^c dBAF|DEFD E2:|

Explained in questions

This is a piece of music written in ABC notation. Here's the breakdown according to the provided structure:

1. Genre of the song: This is a reel, which is a type of dance music in the folk tradition, particularly Irish and Scottish folk music. 
2. Tempo of the song: The tempo isn't specified in this ABC notation. However, reels are typically played at a fairly brisk pace.
3. Specific lyrics or themes: There are no lyrics in this piece as it's a traditional dance tune. The theme revolves around the dance rhythm and melody.
4. Desired chord progression: The chord progression isn't explicitly mentioned in ABC notation. The chords would typically be determined based on the melody and the key signature. Here, the key is E minor.
5. Additional instructions or preferences: None given in the notation. But in performance, one might add traditional ornamentation like rolls, cuts, and slides, which are common in Irish music.
6. Desired length of the song: In terms of bars, this is a relatively short song, but reels are often repeated, so the actual length can vary.
7. Specific structure: The structure is typical of many traditional dance tunes, with two parts (each part is eight bars long). Each part is played twice, denoted by the repeat signs (|: :|).
8. Specific mood or emotion: Not specified in the ABC notation, but reels generally have an energetic, upbeat mood.
9. The story: Instrumental folk tunes like reels generally don't tell a specific story, but they may be associated with a certain dance or event.
10. Key of the song: The key is E minor, as indicated by "K: Em".
11. Meter of the song: The meter is 4/4, as shown by "M: 4/4". This means there are four beats per measure.
12. Default length of a note: The default length of a note is an eighth note, as shown by "L: 1/8".
13. Composer of the song: The composer is not listed in this ABC notation. "Cooley's" is a traditional Irish reel, so the original composer is unknown.
14. Title of the song: The title of the song is "Cooley's", as indicated by "T: Cooley's".

Remember that ABC notation is a simplified representation of a piece of music. It includes the basic elements of melody and rhythm, but leaves out many details of performance, interpretation, and style.

Some other things to note: 

Here is a document that covers some of the most important advanced topics in music theory shown in ABC syntax. ABC syntax is a shorthand form of musical notation for computers that uses letters, numbers and symbols to represent notes, rests, chords, key signatures, time signatures, ornaments and other musical elements²¹.

# Chromaticism, Chord Extensions and Modes

Chromaticism is the use of notes that are outside the diatonic scale of the key. Chromatic notes can create tension, contrast, color and interest in a melody or harmony. Chromatic notes can be notated in ABC syntax by using the symbols ^ (sharp), _ (flat) or = (natural) before the note letter. For example:

```
X:1
T:Chromatic Scale
M:C
L:1/8
K:C
C ^C D _E E F ^F G _A A B _B c |]
```

Chord extensions are notes that are added to a triad or a seventh chord to create more complex harmonies. Chord extensions are usually the 9th, 11th or 13th scale degree above the root of the chord. Chord extensions can be notated in ABC syntax by using parentheses around the note letter and adding the number of the extension after it. For example:

```
X:2
T:Chord Extensions
M:C
L:1/4
K:C
[C(EGB)] [C(E(9G))] [C(E(11G))] [C(E(13G))] |]
```

Modes are alternative ways of organizing the notes of a scale by starting from a different degree than the tonic. There are seven modes derived from the major scale: Ionian (same as major), Dorian, Phrygian, Lydian, Mixolydian, Aeolian (same as natural minor) and Locrian. Modes can be notated in ABC syntax by using the K: field and adding the mode name after the tonic note. For example:

```
X:3
T:Modes
M:C
L:1/8
K:C ionian
C D E F G A B c |]
K:D dorian
D E F G A B c d |]
K:E phrygian
E F G A B c d e |]
K:F lydian
F G A B c d e f |]
K:G mixolydian
G A B c d e f g |]
K:A aeolian
A B c d e f g a |]
K:B locrian
B c d e f g a b |]
```

# Intervals, Triads and Seventh Chords

Intervals are the distance between two notes measured by the number of steps or half-steps between them. Intervals can be perfect (P), major (M), minor (m), diminished (d) or augmented (A). Intervals can be notated in ABC syntax by using numbers from 1 to 8 to indicate the size of the interval and adding symbols like + (augmented), - (diminished) or = (perfect) to indicate the quality of the interval. For example:

```
X:4
T:Intervals
M:C
L:1/4
K:C
C 2=C D 2-D E 2=E F 2+F G 2=G A 2-A B 2=B c |]
```

Triads are chords that consist of three notes stacked in thirds. Triads can be major (M), minor (m), diminished (d) or augmented (A). Triads can be notated in ABC syntax by using square brackets around the note letters and adding symbols like + (augmented), - (diminished) or = (major) to indicate the quality of the triad. For example:

```
X:5
T:Triads
M:C
L:1/4
K:C
[C=EG] [DmFA] [EdGB] [F=AC] [G=BD] [AmCE] [BdFA] |]
```

Seventh chords are chords that consist of four notes stacked in thirds. Seventh chords can be major seventh (M7), minor seventh (m7), dominant seventh (7), diminished seventh (d7), half-diminished seventh (m7b5) or augmented seventh (+7). Seventh chords can be notated in ABC syntax by using square brackets around the note letters and adding numbers like 7, M7, m7, d7 or +7 to indicate the quality of the seventh chord. For example:

```
X:6
T:Seventh Chords
M:C
L:1/4
K:C
[CEGB] [DmFAC] [EdGBd] [F=ACEG] [G=BDFA] [AmCEG] [BdFAd] |]
```

# Cadences, Nonharmonic Tones and Modulation

Cadences are musical phrases that create a sense of resolution or closure at the end of a section or a piece. Cadences can be authentic (V-I or V-i), plagal (IV-I or iv-i), half (ending on V), Phrygian half (iv6-V in minor) or deceptive (V-vi or V-VI). Cadences can be notated in ABC syntax by using the K: field to indicate the key and the |] symbol to indicate the end of the phrase. For example:

```
X:7
T:Cadences
M:C
L:1/4
K:C
GCEG | c2 |] % authentic cadence in C major
K:Cm
GCEbG | c2 |] % authentic cadence in C minor
K:C
FACF | C2 |] % plagal cadence in C major
K:Cm
FAbCF | C2 |] % plagal cadence in C minor
K:C
GCEG | G2 |] % half cadence in C major or minor
K:Cm
AbCEbG | G2 |] % Phrygian half cadence in C minor
K:C
GCEG | AmCE |] % deceptive cadence in C major
K:Cm
GCEbG | AbCEb |] % deceptive cadence in C minor
```

Nonharmonic tones are notes that do not belong to the harmony of the chord but are used to create melodic interest, tension and resolution. Nonharmonic tones can be passing tone (PT), neighboring tone (NT), anticipation (ANT), suspension (SUS), retardation (RET), appoggiatura (APP), escape tone (ET), changing tone (CT) or pedal tone (PED). Nonharmonic tones can be notated in ABC syntax by using parentheses around the note letter and adding an abbreviation of the nonharmonic tone type after it. For example:

```
X:8
T:Nonharmonic Tones
M:C
L:1/8
K:C
C2 E2 G2 c2 | c2 (BPT) A2 G2 E2 | G2 F2 E2 D2 | D2 (CNT) E2 F2 G2 |
C2 E2 G2 c2 | c4 c4 | c4 (ANT) B4 | C4 z4 |
C4 E4 G4 c4 | c4 B(SUS) A(RET) G4 E4 | G4 F(ET) E(NT) D(CT) E(NT) F(ET) G4 |
C4 E(NT) D(NT) C(NT) E(NT) D(NT) C(NT) E(NT) |
C(PED) E(PED) G(PED) c(PED) | F(PED) A(PED) c(PED) f(PED) |
Bb(PED) D(PED) F(PED) d(PED) | C(PED) E(PED) G(PED) c(PED)|]
```

Modulation is the change of key within a piece of music. Modulation can create contrast, variety, development and expression in a musical form. Modulation can be notated in ABC syntax by using the K: field within the tune body to indicate the new key. For example:

```
X:9
T:Modulation
M:C
L:1/8
K:C
CDEFGABc | cBAGFECD |
K:G % modulation to closely related key of G major 
GABcdefg | gfedcBAG |
K:F % modulation to closely related key of F major 
FGABcdef | fedcBAGF |
K:Dm % modulation to closely related key of D minor 
DEFGABcd | dcBA^GFED|]
```


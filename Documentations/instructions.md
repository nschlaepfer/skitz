
Advanced ABC Notation

Multi-Voice Music
- V: fields define separate voices 
- Each voice has own meter, key if needed
- Voice overlay with & to temporarily combine 
- Score directive groups voices on staves

Broken Rhythms
- > makes previous note dotted, next halved
- < makes previous note halved, next dotted
- Allows notation of swing rhythms

Grace Notes 
- Enclosed in { } 
- Played quickly before main note
- Can add durations like {a2b/c/}

Tuplet Grouping
- (n specifies n notes in duration of m
- (3 is a triplet, (5 is quintuplet
- Can use (n:m:p for n notes in m with total of p
- Allows complex rhythmic groupings

Measure Repeats
- |: :| repeats section once 
- :| [1 :| [2 alternate endings 

Inline Fields
- [K:F#m] changes key inline in body
- Allows changes mid-tune

Decorations
- . is staccato mark
- !trill! is trill symbol
- Many more available
- Can stack decorations

Redefinable Symbols 
- U: defines custom symbols
- e.g. U: T = !trill!
- Applies substitutions globally

Transposing Instruments
- V: fields can transpose
- K: fields can set concert key
- Allow parts in written pitch


        The abc Notation System
        =======================

Each tune consists of a header and a body. The header,  which  is
composed of information fields, should start with an X (reference
number) field followed by a T (title) field and finish with  a  K
(key)  field.  The body of the tune in abc notation should follow
immediately after. Tunes are separated by blank lines.

  Information fields
  ==================

The  information  fields  are  used  to  notate  things  such  as
composer,  meter, etc. in fact anything that isn't music. Most of
the information fields are for use within a tune  header  but  in
addition  some  may be used in the tune body, or elsewhere in the
tune file. Those which are allowed elsewhere can be used  to  set
up  a  default  for  the whole or part of a file. For example, in
exactly the same way that tunebooks are organised, a  file  might
start  with  M:6/8 and R:Jigs, followed by some jigs, followed by
M:4/4 and R:Reels, followed by  some  reels.  Tunes  within  each
section then inherit the M: and R: fields automatically, although
they can be overridden inside a tune header.

By far the best way to find out how to use the fields is to  look
at  the  example  files  (in particular Xenglish.abc) and try out
some examples. Thus rather than describing them in  detail,  they
are  summarised  in  the  following  table. The second, third and
fourth columns specify respectively how the field should be  used
in  the  header and whether it may used in tune body or elsewhere
in the file. Certain fields do not affect the typeset  music  but
are  there for other reasons, and the fifth column reflects this;
index fields only affect the index (see index.tex) while  archive
fields  do not affect the output at all, but are just provided to
put in information that one might find in,  say,  a  conventional
tunebook.

Field name            header   tune elsewhere Used by Examples and notes
==========            ======   ==== ========= ======= ==================
A:area                optional                        A:Donegal, A:Bampton
B:book                optional      yes       archive B:O'Neills
C:composer            optional                        C:Trad.
D:discography         optional                archive D:Chieftans IV
E:elemskip            optional yes                    see Line Breaking
F:file name                         yes               see index.tex
G:group               optional      yes       archive G:flute
H:history             optional      yes       archive H:This tune said to ...
I:information         optional      yes       playabc
K:key                 last     yes                    K:G, K:Dm, K:AMix
L:default note length optional yes                    L:1/4, L:1/8
M:meter               optional yes  yes               M:3/4, M:4/4
N:notes               optional                        N:see also O'Neills - 234
O:origin              optional      yes       index   O:I, O:Irish, O:English
P:parts               optional yes                    P:ABAC, P:A, P:B
Q:tempo               optional yes                    Q:200, Q:C2=200
R:rhythm              optional      yes       index   R:R, R:reel
S:source              optional                        S:collected in Brittany
T:title               second   yes                    T:Paddy O'Rafferty
W:words               no       yes                    W:Hey, the dusty miller
X:reference number    first                           X:1, X:2
Z:transcription note  optional                        Z:from photocopy

Some additional notes on certain of the fields:-

T - tune title. Some tunes have more than one title and  so  this
field  can  be used more than once per tune - the first time will
generate the title whilst  subsequent  usage  will  generate  the
alternatives  in  small  print.   The  T:  field can also be used
within a tune to name parts of a tune - in this  case  it  should
come before any key or meter changes.

K - key; apart from major and minor  keys,  e.g.   K:D  or  K:Am,
mixolydian  and  dorian  modes  can  also  be specified with, for
example K:AMix  or  K:EDor.  In  addition,  there  are  two  keys
specifically  for  notating  highland bagpipe tunes; K:HP doesn't
put a key signature on the music, as is  common  with  many  tune
books  of  this music, while K:Hp marks the stave with F sharp, C
sharp and G natural.  Both force all the beams and staffs  to  go
downwards.

L - default note length; i.e.  L:1/4  -  quarter  note,  L:1/8  -
eighth  note,  L:1/16  -  sixteenth,  L:1/32 - thirty-second. The
default note length is also set automatically by the meter  field
M: (see below).

M - meter; apart from the normal meters, e.g.   M:6/8  or  M:4/4,
the   symbols  M:C  and  M:C|  give  common  time  and  cut  time
respectively.

P - parts; can be used in the header to state the order in  which
the  tune parts are played, i.e.  P:ABABCDCD, and then inside the
tune to mark each part, i.e.  P:A or P:B.

Q - tempo; can be used to specify the notes per minute, e.g.   if
the  default  note length is an eighth note then Q:120 or Q:C=120
is 120 eighth notes per minute. Similarly  Q:C3=40  would  be  40
dotted  quarter  notes per minute.  An absolute tempo may also be
set,  e.g.  Q:1/8=120  is  also  120  eighth  notes  per  minute,
irrespective of the default note length.

G - group; to group together tunes for indexing purposes.

H - history; can be used for multi-line stories/anecdotes, all of
which will be ignored until the next field occurs.


  abc tune notation
  =================

The following letters are used to represent notes:-


                                                      d'
                                                -c'- ----
                                             b
                                        -a- --- ---- ----
                                       g
 ------------------------------------f-------------------
                                   e
 --------------------------------d-----------------------
                               c
 ----------------------------B---------------------------
                           A
 ------------------------G-------------------------------
                       F
 --------------------E-----------------------------------
                   D
 ---- ---- ---- -C-
            B,
 ---- -A,-
  G,

and by extension, the notes C, D, E, F, a' and b' are  available.
Notes can be modified in length (see below).

  Rests
  =====

Rests are generated with a z and can be  modified  in  length  in
exactly the same way as notes can (see below).

  Note lengths
  ============

NB Throughout this document I refer to note lengths as sixteenth,
eighth,  etc.  The commonly used equivalents are sixteenth note =
semi-quaver, eighth = quaver,  quarter  =  crotchet  and  half  =
minim.

Each meter automatically sets a default note length and a  single
letter in the range A-G, a-g will generate a note of this length.
For example, in 3/4 the default note length is an eighth note and
so  the  input  DEF  represents  3 eighth notes. The default note
length can be calculated by computing the meter as a decimal;  if
it  is  less than 0.75 the default is a sixteenth note, otherwise
it is an eighth note. For example, 2/4 = 0.5, so the default note
length is a sixteenth note, while 4/4 = 1.0 or 6/8 = 0.75, so the
default is an eighth note. Common time  and  cut  time  (M:C  and
M:C|) have an eighth note as default.

Notes of differing lengths can be obtained by  simply  putting  a
multiplier  after the letter. Thus in 2/4, A or A1 is a sixteenth
note, A2 an eighth note, A3 a dotted eighth note,  A4  a  quarter
note,  A6 a dotted quarter note, A7 a double dotted quarter note,
A8 a half note, A12 a dotted half note, A14 a double dotted  half
note,  A15  a triple dotted half note and so on, whilst in 3/4, A
is an eighth note, A2 a quarter note, A3 a dotted  quarter  note,
A4 a half note, ...

To get shorter notes, either divide them - e.g. in 3/4, A/2 is  a
sixteenth  note,  A/4  is  a  thirty-second  note - or change the
default note length with the L:  field.   Alternatively,  if  the
music has a broken rhythm, e.g. dotted eighth note/sixteenth note
pairs, use broken rhythm markers (see below).  Note  that  A/  is
shorthand for A/2.

  Broken Rhythms
  ==============

A common occurrence in traditional music is the use of  a  dotted
or broken rhythm. For example, hornpipes, strathspeys and certain
morris jigs all have dotted eighth notes  followed  by  sixteenth
notes  as  well  as  vice-versa  in  the  case of strathspeys. To
support this abc notation uses a > to mean `the previous note  is
dotted, the next note halved' and < to mean `the previous note is
halved, the next dotted'. Thus the following lines all  mean  the
same thing (the third version is recommended):

  L:1/16
  a3b cd3 a2b2c2d2

  L:1/8
  a3/2b/2 c/2d3/2 abcd

  L:1/8
  a>b c<d abcd

As a logical extension, >> means that the first  note  is  double
dotted and the second quartered and >>> means that the first note
is triple dotted and the length of the second divided  by  eight.
Similarly for << and <<<.

  Duplets, Triplets, Quadruplets, etc.
  ====================================

These can be simply coded with the notation (2ab  for  a  duplet,
(3abc  for  a triplet or (4abcd for a quadruplet, etc., up to (9.
The musical meanings are (so I'm told):


 (2 2 notes in the time of 3
 (3 3 notes in the time of 2
 (4 4 notes in the time of 3
 (5 5 notes in the time of n
 (6 6 notes in the time of 2
 (7 7 notes in the time of n
 (8 8 notes in the time of 3
 (9 9 notes in the time of n

If the time signature is compound (3/8, 6/8, 9/8, 3/4, etc.) then
n is three, otherwise n is two.

  Beams
  =====

To group notes together under one beam  they  should  be  grouped
together  without spaces in the tune file. Thus in 2/4, A2BC will
produce an eighth note followed by two sixteenth notes under  one
beam  whilst  A2  B  C will produce the same notes separated. The
beam slopes and the choice of upper or lower staffs are generated
automatically.

  Repeat/bar symbols
  ==================

The symbols | || :| |: and :: generate a bar  line,  double  bar,
left repeat, right repeat and left/right repeat respectively.


  First and Second Repeats
  ========================

First and second repeats can be generated with the symbols |1 and
:|2,  e.g.  faf gfe|1 dfe dBA:|2 d2e dcB||. The previous notation
[1 and [2 is still  supported  but  produces  slightly  different
output. N.B. With regard to spaces | [1 is legal, | 1 is not.

  Accidentals
  ===========

The symbols ^ = and _  are  used  (before  a  note)  to  generate
respectively a sharp, natural or flat.

  Changing key, meter, and default note length mid-tune
  =====================================================

To change key, meter, or default note length, simply put in a new
line with a K: M: or L: field, e.g.
  ed|cecA B2ed|cAcA E2ed|cecA B2ed|c2A2 A2:|
  K:G
  AB|cdec BcdB|ABAF GFE2|cdec BcdB|c2A2 A2:|

To do this without generating a new line of music, put a \ at the
end of the first line, i.e.
  E2E EFE|E2E EFG|\
  M:9/8
  A2G F2E D2||

  Ties and Slurs
  ==============

You can tie two notes together either across or within a bar with
a - symbol, e.g. abc-|cba or abc-cba.  More general slurs can now
be put in and are started and terminated with  an  s  before  the
relevant note.  Thus sDEFsG puts a slur over the four notes DEFG.

  Gracings
  ========

With regard to gracings, I fall in the  Irish  music  camp  which
says that you transcribe gracings as little as possible and leave
it up to the players to make their own interpretation.  Thus  the
only  gracing  I  tend to use is to put a tie/slur marker under a
note which will generally mean a roll, cran or staccato  triplet.
This is achieved by putting a ~ before the note.

However, to explicitly write out every grace note, just put  them
in  curly  braces,  {}.  For example, a taorluath on the Highland
pipes would be written {GdGe}. The tune  `Athol  Brose'  (in  the
file  Xstrspys.abc)  has  an  example  of  complex  Highland pipe
gracing in all its glory.

  Accents
  =======

Staccato marks (a small dot above or below the note head) can  be
generated  by  a  dot before the note, i.e. a staccato triplet is
written as (3.a.b.c

For fiddlers, the letters u and v can be used  to  denote  up-bow
and down-bow, e.g. vAuBvA

  Chords
  ======

Chords (i.e. more than one note head on a  single  stem)  can  be
coded  with  +  signs  around the notes, e.g. +CEGc+ produces the
chord  of  c  major.  They  can  be  grouped   in   beams,   e.g.
+d2f2++ce++df+, but note the use of two + symbols, one to end the
first chord and one to start the second. Note that the code which
handles  this  part  of the output is a bit sensitive and you may
need to fiddle around a bit with the order of the  notes  in  the
chord to get it looking right. See the tune `Kitchen Girl' in the
file Xreels.abc for a simple example.

  Guitar Chords
  =============

Guitar chords can be put in under the melody  line  by  enclosing
the  chord  in  inverted  commas,  e.g.  "Am7"A2D2 . See the tune
`William and Nancy' in Xenglish.abc for an example.

  Order of Symbols
  ================

The order of symbols for one note is <guitar  chords>,  <accents>
(e.g. roll, staccato marker or up/downbow), <accidental>, <note>,
<octave>, <note length>, i.e. ~^c'3 or even "Gm7"v.=G,2

  Comments
  ========

A % symbol will cause the remainder  of  any  input  line  to  be
ignored. The file Xenglish.abc contains plenty of examples.

  Introducing New Notation
  ========================

The letters H-Z inclusive have been set aside to allow  users  to
introduce  their own additional symbols. One such example is J to
denote sliding up to a note.

  Line Breaking and Justification
  ===============================

Generally one line of abc  notation  will  produce  one  line  of
music,  although  if  the music is too long it will overflow onto
the next line. This can look very  effective,  but  it  can  also
completely  ruin  ties  across  bar  lines,  for example. You can
counteract this by changing either the internote spacing with the
E: field or break the line of abc notation. If, however, you wish
to use two lines of input to generate one line of music (see, for
example,  the  `Untitled Reel' in Xreels.abc) then simply put a \
at the end of the first line.  This is also useful  for  changing
meter or key in the middle of a line of music.

By default, lines of music  are  left-justified  but  not  right-
justified.  To  overcome this, a * at the end of each line of abc
notation will force a right-justified line-break. For  the  final
line  of  a  tune  put  ** (so as to not generate a new line). Be
warned, however,  that  if  a  line  is  not  very  long  or  has
overflowed  to  become  two lines, this can look very ugly as the
notes spread themselves out along the line. It can also give ugly
output  other  people  using  the abc file who may have different
layout parameters.

  Internote spacings
  ==================

The internote spacing is set by the information field E.  As  the
format  is set up now, I use E:8 and E:7 to squeeze long tunes up
a bit and E:10 and above  to  stretch  short  tunes.   Using  E:6
really looks too cramped to my eye.

  TeX Input
  =========

If there is a line in a tune file beginning with a \, it  is  put
directly into the output file (music.tex).



Ordinary keyboards, and the most common computer character sets, don't include accidentals, so ABC uses a scheme that works for the ASCII character set:

^G	G sharp
=G	G natural
_G	G flat
Note that these are somewhat pictorial, since ^ is a "high" letter and _ is a "low letter".
There's not much more to it, except that there are a few ABC programs that also accept a notation for quarter-tone accidentals. These are written with a backslash before the accidental:

\^G	G half-sharp
\_G	G half-flat
People dealing with music that uses quarter tones should check to see if a tool handles this notation. Note that there are several different ways to indicate quarter tones in staff notation, and different formatting tools may draw different characters. There may be more development of this idea in the future, so ask around if you're interested.

The simplest case, a triplet of notes, is easy:

	(3 FGA
This means the 3 notes FGA in the time of two notes. Note that there's no ) at the end, and spaces are irrelevant. For this simple case, the 3 notes should have the same length.
ABC can represent general n-tuplets using the syntax:

	(p:q:r ...
This means "put p notes into the time of q for the next r notes." There are a few special cases. If r is missing, it defaults to p. For example: If q is missing, it defaults to [undocumented at present].
Note that music formatting programs actually ignore the q value, though it is used by music playing programs to determine how long the p notes should take. A formatting program should produce the usual "bracket" marking the next r notes, and put the number p above or inside the bracket.

Special cases:

	(3::2 = (3:2:2
	(3    = (3:2:3


    ABC uses different symbols for ties and slurs, though most music publishers draw them with indistinguishable curved lines. The notation for ties is a hyphen ('-') after the first note. This should usually be used only between identical notes, though some software understands the use of ties between different notes. But most ABC software will give you a warning if the notes aren't the same.

Slurs are indicated with parentheses before the first note and after the second:

	| (DE)FG (AB)cd |
This is how you'd write the usual 2-1-1 "fiddle shuffle" bowing in a tune.
Slurs are also sometimes nested, with the longer (outer) pairs of parentheses used to indicate phrasing. This should work with most ABC software, though you might not hear the effect of the outer "phrase" parentheses from many ABC player programs

Examples? How about our Country Garden friend, this time with chords:

X: 3
T: Country Garden(s)
Z: 1997 by John Chambers <jc@trillian.mit.edu> http://trillian.mit.edu/~jc/music/abc/
P: A(A2B2C2B2)2
M: C|
L: 1/8
K: C
P: A
 | "G7"g2 g>f "C"e2 e2 | "D7"d2 d>c "G"B2 B>c | "G"d2 G2 "C"A2 c2 | "D7"B3A "G"G4 |]
P: B
[| "A7"g>a g>e "D"f2 d2 | "A7"g>a g>e "D"f4 | "A7"g2g>f e2a2 | f3e "D7"d2B>c |
| "G7"d2 g>f "C"e2 e2 | "D7"d>e d>c "G"B2 B>c | "G"d2 G2 "C"A2 c2 | "D7"B3A "G"G4 |]
P: C
[| "C"G2c2 c2e2 | "D7"d>e d>c "G"B2 B>c | "G"d2 G2 "C"A2 c2 | "D7"B3A "G"G4 |]

This represents the note e with two grace notes, c and d, before it. Music formatting programs will represent these as tiny notes. Playback programs will play them somehow, but exactly how isn't defined by ABC itself. A good way to write out complicated ornaments is to write the main notes as regular notes with their full time, and fill in between them with little notes. Here are some examples:
X:12
T:Gracenotes
L:1/8
M:C
K:D
| {E}FA{c}AF DF{^dc}A f{A}df f{AGA}df \
| {B}D2 {A}D2 {G}D2 {F}D2 {E}D2 \
| {E}c2 {F}c2 {G}c2 {A}c2 {B}c2 |
| {A}^c2 {gcd}c2 {gAGAG}A2{g}c<{GdG}e {Gdc}d>c {gBd}B<{e}G \
| {G}[G4e4] {FGAB}[^c4A4] {ef}[e4c4] {d'c'bagfedcB_AcBFGC}D4 |]

Here is a demo of three ways of writing a bass line:

X: 1
T: Three bass lines
K: C
V: 1 clef=bass
[| CDEF GABc | cdef gabc' | c'bag fedc | cBAG FEDC |]
w: C D E F G A B c c d e f g a b c' c' b a g f e d c c B A G F E D C
V: 2 clef=bass middle=D
[| C,D,E,F, G,A,B,C | CDEF GABc | cBAG FEDC | CB,A,G, F,E,D,C, |]
w: C, D, E, F, G, A, B, C C D E F G A B c c B A G F E D C C B, A, G, F, E, D, C,
V: 3 clef=bass,,
[| C,,D,,E,,F,, G,,A,,B,,C, | C,D,E,F, G,A,B,C | CB,A,G, F,E,D,C, | C,B,,A,,G,, F,,E,,D,,C,, |]
w: C,, D,, E,, F,, G,, A,, B,, C, C, D, E, F, G, A, B, C C B, A, G, F, E, D, C, C, B,, A,, G,, F,, E,, D,, C,,


One of the nice things about ABC notation is that it is fairly readable. Many people are already claiming that they can read ABC nearly as easily as standard music notation. However, as with anything, there is good and bad ABC notation. Here are some suggestions for making your ABC easy to read.
The main suggestion is to use spaces. Consider these lines of music:

|"C"EDC|GF"C7"E|"F"ccA/B/|c3|"C"GEC|CB,C|"D7"EDD|"G7"D2G|
|"C"GGE/F/|GG"C7"c|"F"ccA/B/|c2A|"C"GEC|"G7"DED|"C"C3-|C3||
	
Not very nice to read, is it? Now compare it with:
| "C"EDC    | GF "C7"E | "F"ccA/B/ | c3  | "C"GEC |    CB,C | "D7"EDD | "G7"D2G |
| "C"GGE/F/ | GG "C7"c | "F"ccA/B/ | c2A | "C"GEC | "G7"DED |  "C"C3- | C3     ||
	
You probably find this much easier to read. There are two ways that the spacing makes the second easier to read:
Putting spaces around the bar lines isn't required by ABC, but it really improves readability.
We also aligned the notes and chords vertically in these two parallel lines of music. This makes the chords stand out somewhat from the notes, and makes it easier for a reader to associate the notes with the rhythm.
A third, more subly thing that was done in both of the above examples was to make each phrase start a new line. This isn't always possible, just as it isn't with standard music notation, but when you can do it easily, you should.
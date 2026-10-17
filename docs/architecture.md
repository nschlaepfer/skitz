# Architecture

The `skitz` Python executable owns local music commands and launches a pinned
Prime Agent process for natural-language work. Prime retains its terminal,
sessions, recursive agents, Python kernel and provider implementation. Skitz
injects the music workflow and an executable `skitz-music` package. Authentication
uses Prime's existing ChatGPT Codex OAuth provider and refresh/storage logic.

`SKITZ_HOME` determines a separate configuration root, session directory, daemon
identity and kernel environment. API-key environment variables are stripped from
the launched runtime; model dispatch is restricted to the subscription provider.
The public login command stores OAuth credentials using Prime's locked, owner-only
auth storage. User sign-in happens in the browser; no credentials are copied from
other applications. Upstream update entry points are disabled under Skitz.

The same music operations are available as Python calls, JSON CLI output and local
MCP tools. The MCP service confines project paths to its configured workspace.
No extra model loop lives in the music package: Prime performs agent orchestration.
The benchmark direct-response adapter also uses Prime's provider implementation,
with no tools or durable state during each response.

## Score Ownership

Schema 2 supports exact rational quarter-unit positions, spelled pitches, event
IDs, rests, chords, ties and basic articulations, with meter and tempo maps that
change only at measure starts. A track is one rhythmic line; use separate tracks
for independent voices. JSON schemas reject extra fields and unsupported values.
Structure checking is independent of model output: no overlaps or gaps, ties
between equal pitch sets, whole measures of the meter map, equal track lengths and
no map changes past the end. Chorale warnings are separately labeled and have
located event evidence.

Every canonical score revision is addressed by SHA-256. Reads check the content
hash. A project lock serializes mutations; expected-revision checks reject stale
edits. Patch edits (`skitz schema patch`) apply in order to a working copy; nothing
shifts implicitly. The whole result must then pass the schema and structure
checks, every measure whose events, barlines, meter or tempo changed must be in
the declared allowed measures, new event IDs must be unused, IDs never move between
tracks, and protected tracks must equal the baseline. The baseline policy persists
across invocations. Rollback checks the same protected baseline. HEAD updates are
atomic; history is retained.

Schema-1 projects migrate on first use under the project lock. Each original
revision's hash is verified, its schema-2 form is written beside it,
`migrations.json` maps old revision IDs to new ones (old IDs keep working for
reads, patches and rollback), history records the migration and `format.json`
marks completion. Renders made before migration name the old revision, so
re-render before `skitz verify`. These guarantees cover use through the operations, not malicious direct
filesystem edits by an unrestricted agent.

MIDI, MusicXML and escaped LilyPond are derived from the canonical score. SATB
LilyPond has two staves with opposing stem directions. Render manifests link
versions, hashes, configuration and diagnostics to the exact source revision.
No cross-machine bit-identical rendering is claimed; MusicXML/PDF producers may
include timestamps. `skitz verify` independently checks saved hashes and protected
score content rather than trusting the agent's own verification prose.

## Execution Boundaries

Prime executes Python with user permissions. It is **not** sandboxed by Skitz.
Use trusted workspaces or externally sandbox the entire agent, with credentials
managed outside an untrusted worker. The editable-score API is not a boundary
against a malicious process with write access to its implementation or policy.

Notation and audio subprocesses run with a fresh credential-free environment,
temporary work directory, network denied, restricted file reads/writes, CPU time,
wall time, file size and descriptor limits. The macOS profile allows system
libraries/fonts, Homebrew dependencies and the job directory. A root-directory
read is required by current macOS dyld startup. The profile permits filesystem
metadata inspection but denies private file contents. Tests exercise successful
execution and denial, so a crashing worker cannot masquerade as isolation.

The compiler accepts raw LilyPond only inside this worker. Unsupported worker
platforms fail closed. This is a bounded local compiler backend, not a universal
hostile-code containment claim or a portable container runtime. Held-out grading
must be run separately outside the agent's writable project.

# Evaluation

Auggie (@aug5thmusic), author of Augmented Fifth, published
[The Bach Benchmark](https://aug5th.substack.com/p/the-bach-benchmark) on July 19,
2026. It motivates this repository's SATB, G-minor, 3/4 task and independent checks
of notation, voice ranges and part-writing. The article is a prompt-and-critique
exercise; Skitz does not claim it provides an official installable evaluation
suite, aggregate score, endorsement or a comprehensive definition of good music.

The task metadata is in `evals/bach-reproduction/task.json`. The bundled prompt
is a paraphrase. Exact reproductions require the user-supplied original prompt
file; its bytes and SHA-256 are saved in the run directory.

## Conditions

- `single-response`: one direct response through Prime's Codex subscription
  provider, with no tools or feedback. Compile afterward for measurement.
- `compiler-repair`: the same initial prompt, followed by explicit compiler
  feedback if needed. Each attempt and output is retained. Report first-attempt
  and final compiler success separately.
- `skitz-structured-score`: the Prime agent can use the music skill, score schema,
  diagnostics, patches and rendering. This is an agent-workflow experiment, not
  an exact one-shot LilyPond reproduction.

```sh
uv run skitz bench --condition compiler-repair --prompt-file original-prompt.txt \
  --output work/compiler-repair --model gpt-5.5 --max-attempts 3
```

The direct-response runner records actual prompt, model/provider, response text,
usage, elapsed time, compiler diagnostics and artifacts. It enforces a response
token limit and bounded attempts, and never falls back to API-key billing.
Compiler success says nothing about the quality of harmony or phrasing. The
notation may compile and still need expert musical review.

## Constrained Editing

`evals/verify-editing.py` is a deterministic harness acceptance test. It creates an
authored fixture, injects a known parallel octave, detects its specific event IDs,
repairs only the edited bass event, checks exact restoration and protected soprano
preservation, and renders all three stages. It does not call a model or count as
a musical benchmark result. The fixture has a separately disclosed baseline style
warning; the test verifies localized repair, not globally ideal composition.

The Python tests additionally reject stale revisions, protected edits, edits
outside allowed measures, invalid rhythm, orphan ties, corrupted revisions and
workspace traversal. The MCP integration test exercises real stdio tool discovery,
creation, inspection, rejection and editing.

For model comparisons use fresh state and matched models, tool versions, budgets
and SoundFonts. Compare direct generation, stock Prime with the same tools and
Skitz separately. Keep final grading and held-out tasks outside the writable
workspace. Freeze refinement and durable memory for formal runs. No comparative
improvement claim is established by the current smoke tests.

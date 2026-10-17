# Third-Party Notices

Skitz retains its original MIT license in `LICENSE`.

Prime Agent is imported from https://github.com/PrimeIntellect-ai/prime-agent at
`f771dfcedd684d1afff84ca2c6fa95c7a21efbc2`. Its full license is preserved at
`vendor/prime-agent/LICENSE`, including the notices for Mario Zechner and
Prime Intellect. All package-level notices and licenses in the imported source
are retained. Local patches and import provenance are documented in `docs/upstream.md`.

The Bach Benchmark task is attributed to Auggie of Augmented Fifth:
https://aug5th.substack.com/p/the-bach-benchmark (July 19, 2026).
Skitz includes a task paraphrase and links, not the article or model-generated
scores from it. No endorsement is implied.

Music operations depend on music21; notation rendering uses LilyPond; audio
rendering uses FluidSynth. These are separately installed dependencies with their
own licenses. Stem separation runs python-audio-separator and transcription runs
Spotify's basic-pitch (Apache-2.0); uv installs each into its own tool environment
on first use, and neither is redistributed. GeneralUser GS by S. Christian Collins
was used for development verification and is not redistributed. See its upstream
license at https://github.com/mrbumpy409/GeneralUser-GS/blob/main/documentation/LICENSE.txt.

# Security

Please report vulnerabilities privately through
[GitHub security advisories](https://github.com/nschlaepfer/skitz/security/advisories/new),
not in public issues.

Skitz stores sign-in state outside the repository: ChatGPT OAuth under
`~/.skitz/agent`, and service cookies such as Suno's in `~/.skitz/suno/cookie` (mode 600).
If you think one of these leaked, sign out of that service to end the session.
Then delete the local file, or reconnect with `skitz login`.

Prime's agent kernel is not a security sandbox. See `docs/architecture.md`.

# DockerDeck — Security Notes & Threat Model

DockerDeck is a **local operator console**. Its security model assumes
the machine running it is trusted and is under the control of the person
using it. It is not designed for shared, multi-user, or networked environments.

---

## What DockerDeck Handles

### Registry Credentials

- Passwords are **never** passed as CLI arguments.
- They are piped to `docker login` via **stdin** (`--password-stdin`).
- After `communicate()` returns, the password string reference is deleted (`del password`).
- A best-effort `ctypes.memset` is applied to the encoded bytes buffer.

**Honest limitation:** Python's string interning and garbage collector mean
we cannot guarantee the password is zeroed from RAM. This is a known limitation
of CPython's memory model. The code does the best that is reasonably possible
in pure Python. If you need stronger guarantees, use a native credential store
(e.g., Docker credential helpers configured in `~/.docker/config.json`).

### Deploy Presets

- Presets are stored in `~/.dockerdeck/presets.json`.
- They contain **configuration only** (image names, port mappings, env keys).
- Passwords and secrets are **never** included in presets — there is no field for them.
- If a preset file is corrupted, DockerDeck starts with empty presets rather than crashing.

### Input Validation

Every user-supplied value that touches a `docker` subprocess call is:
1. Checked against a **dangerous-character allowlist** (rejects `;`, `|`, `` ` ``, `$`, etc.)
2. Matched against a **format allowlist** (image name regex, port pattern, etc.)
3. Passed as a **separate argv token** — never interpolated into a shell string

Extra docker flags are validated against an explicit **allowlist of known-safe flags**.
Unknown flags are rejected with a clear error, not silently dropped.

### Confirmation Dialogs

Destructive operations (remove container, prune volumes, system prune, bulk remove)
require an explicit confirmation dialog before execution. The full command is shown
in the dialog so users can see exactly what will run.

---

## What Is Not Guaranteed

- **Memory safety of secrets:** Python cannot guarantee RAM zeroing. See above.
- **Multi-user isolation:** DockerDeck runs as the current user. If multiple users
  share a machine, their Docker sockets and presets are not isolated from each other.
- **Network security:** The GitHub update-check makes an outbound HTTPS request.
  It fails silently if blocked. No data is sent — only a `GET` to the releases API.
- **Compose file safety:** The Compose editor allows arbitrary YAML to be saved and
  run. DockerDeck does not validate compose file contents. Treat compose files as code.
- **Container trust:** DockerDeck pulls and runs images you specify. It does not
  verify image signatures or enforce content trust policies. Use Docker's own
  content trust features (`DOCKER_CONTENT_TRUST=1`) if this matters to you.

---

## Trust Boundary

```
[Trusted]  Local filesystem, local Docker socket, current user
[Untrusted] Network (registry, GitHub API), image contents, compose files
[Not in scope] Multi-user, networked daemon, CI/CD pipelines
```

---

## Reporting Issues

This is an open-source personal tool. If you find a security issue,
please open a GitHub issue with the label `security`. Do not include
live credentials or sensitive data in issue reports.

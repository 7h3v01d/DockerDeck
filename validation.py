"""
DockerDeck – validation.py
All input validation and sanitisation logic.
"""

import re

# Characters that are dangerous in shell contexts
_DANGEROUS_PATTERN = re.compile(r'[;&|`$<>\\!]')

# Allowlists
_PORT_PATTERN   = re.compile(r'^\d{1,5}:\d{1,5}(?:/(?:tcp|udp))?$')
_IMAGE_PATTERN  = re.compile(r'^[a-zA-Z0-9]([a-zA-Z0-9_.\-/:@]*[a-zA-Z0-9])?$')
_NAME_PATTERN   = re.compile(r'^[a-zA-Z0-9][a-zA-Z0-9_.\-]*$')
_ENV_PATTERN    = re.compile(r'^[A-Za-z_][A-Za-z0-9_]*=.*$')
_VOLUME_PATTERN = re.compile(r'^[^:]+:[^:]+(?::[a-z,]+)?$')

ALLOWED_EXTRA_FLAGS = {
    "--memory", "--memory-swap", "--cpus", "--cpu-shares",
    "--user", "--workdir", "--hostname", "--entrypoint",
    "--platform", "--pull", "--rm", "--read-only",
    "--shm-size", "--ulimit", "--cap-add", "--cap-drop",
    "--security-opt", "--log-driver", "--log-opt",
    "--health-cmd", "--health-interval", "--health-retries",
    "--no-healthcheck", "--init", "--privileged",
    "--label", "--annotation",
}


class ValidationError(ValueError):
    pass


def validate_image_name(val: str) -> str:
    val = val.strip()
    if not val:
        raise ValidationError("Image name cannot be empty.")
    if _DANGEROUS_PATTERN.search(val):
        raise ValidationError(f"Image name contains dangerous characters: {val!r}")
    if not _IMAGE_PATTERN.match(val):
        raise ValidationError(f"Image name format invalid: {val!r}")
    return val


def validate_container_name(val: str) -> str:
    val = val.strip()
    if not val:
        return val  # optional field
    if _DANGEROUS_PATTERN.search(val):
        raise ValidationError(f"Container name contains dangerous characters: {val!r}")
    if not _NAME_PATTERN.match(val):
        raise ValidationError(f"Container name must be alphanumeric/dash/dot: {val!r}")
    return val


def validate_ports(val: str) -> list:
    val = val.strip()
    if not val:
        return []
    ports = []
    for p in val.split(","):
        p = p.strip()
        if not p:
            continue
        if _DANGEROUS_PATTERN.search(p):
            raise ValidationError(f"Port contains dangerous characters: {p!r}")
        if not _PORT_PATTERN.match(p):
            raise ValidationError(f"Port format must be HOST:CONTAINER (e.g. 8080:80): {p!r}")
        ports.append(p)
    return ports


def validate_env_vars(val: str) -> list:
    val = val.strip()
    if not val:
        return []
    envs = []
    for e in val.split(","):
        e = e.strip()
        if not e:
            continue
        if _DANGEROUS_PATTERN.search(e):
            raise ValidationError(f"Env var contains dangerous characters: {e!r}")
        if not _ENV_PATTERN.match(e):
            raise ValidationError(f"Env var must be KEY=value format: {e!r}")
        envs.append(e)
    return envs


def validate_volumes(val: str) -> list:
    val = val.strip()
    if not val:
        return []
    vols = []
    for v in val.split(","):
        v = v.strip()
        if not v:
            continue
        safe_check = v.replace("/", "").replace("\\", "").replace(":", "")
        if _DANGEROUS_PATTERN.search(safe_check):
            raise ValidationError(f"Volume contains dangerous characters: {v!r}")
        if not _VOLUME_PATTERN.match(v):
            raise ValidationError(f"Volume must be SOURCE:DEST format: {v!r}")
        vols.append(v)
    return vols


def validate_extra_args(val: str) -> list:
    """
    Strict allowlist for extra args — only known safe flags.
    Handles both '--flag value' and '--flag=value' forms.
    Values following a flag are passed through (after danger-char check).
    """
    val = val.strip()
    if not val:
        return []
    tokens = val.split()
    result = []
    i = 0
    while i < len(tokens):
        tok = tokens[i]
        if _DANGEROUS_PATTERN.search(tok):
            raise ValidationError(f"Extra arg contains dangerous characters: {tok!r}")

        if "=" in tok:
            # '--flag=value' form — extract flag for allowlist check
            flag = tok.split("=")[0]
            if flag not in ALLOWED_EXTRA_FLAGS:
                raise ValidationError(
                    f"Extra arg '{flag}' is not on the allowlist.\n"
                    f"Allowed flags: {', '.join(sorted(ALLOWED_EXTRA_FLAGS))}"
                )
            result.append(tok)
        elif tok.startswith("-"):
            # '--flag value' form — check flag, then consume next token as value
            if tok not in ALLOWED_EXTRA_FLAGS:
                raise ValidationError(
                    f"Extra arg '{tok}' is not on the allowlist.\n"
                    f"Allowed flags: {', '.join(sorted(ALLOWED_EXTRA_FLAGS))}"
                )
            result.append(tok)
            # Boolean flags (no value) — skip value consumption for known bool flags
            BOOL_FLAGS = {"--rm", "--read-only", "--no-healthcheck", "--init", "--privileged"}
            if tok not in BOOL_FLAGS and i + 1 < len(tokens) and not tokens[i + 1].startswith("-"):
                i += 1
                val_tok = tokens[i]
                if _DANGEROUS_PATTERN.search(val_tok):
                    raise ValidationError(
                        f"Extra arg value contains dangerous characters: {val_tok!r}")
                result.append(val_tok)
        else:
            # Bare word not starting with '-' — skip (positional, ignore silently)
            pass
        i += 1
    return result

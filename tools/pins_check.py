#!/usr/bin/env python3
"""Fail if a compose image digest is not the manifest-list digest for its tag.

Run by `just pins`. NOT part of `just check` — it talks to a registry, and a
pre-commit hook that needs the network is a pre-commit hook people disable.

Why this exists: pinning by digest is only portable if the digest is the
manifest LIST. `podman image inspect ... RepoDigests` on an arm64 machine will
happily hand you the arm64 sub-manifest, which looks identical in compose.yaml
and pulls an unusable image on an amd64 host. That is exactly what happened
here — four of five pins were correct and the fifth was arm64-only, with
nothing in the file to distinguish them.

It reads the `# renovate: <repo>:<tag>` comment above each image as the claimed
version, resolves that tag against the registry, and compares.
"""

import json
import re
import sys
import urllib.error
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent / "lib"))

import report

GATE = "pins"
COMPOSE = "compose.yaml"

# `# renovate: repo:tag` on one line, `image: registry/repo@sha256:...` on a
# following line. The comment is the human-readable claim; the digest is what
# actually runs. This gate exists because those two can disagree silently.
PIN = re.compile(
    r"#\s*renovate:\s*(?P<repo>[\w./-]+):(?P<tag>[\w.-]+)\s*\n"
    r"\s*image:\s*(?P<registry>[\w.-]+)/(?P<path>[\w./-]+)@(?P<digest>sha256:[0-9a-f]{64})"
)

ACCEPT = ", ".join(
    (
        "application/vnd.oci.image.index.v1+json",
        "application/vnd.docker.distribution.manifest.list.v2+json",
        "application/vnd.oci.image.manifest.v1+json",
        "application/vnd.docker.distribution.manifest.v2+json",
    )
)

AUTH = "https://auth.docker.io/token?service=registry.docker.io&scope=repository:{repo}:pull"
MANIFEST = "https://registry-1.docker.io/v2/{repo}/manifests/{tag}"


class Unreachable(Exception):
    """The registry could not be consulted. Not a finding — an absence of one."""


def token(repo: str) -> str:
    try:
        with urllib.request.urlopen(AUTH.format(repo=repo), timeout=15) as response:  # noqa: S310
            return json.load(response)["token"]
    except (urllib.error.URLError, TimeoutError, ValueError, KeyError) as exc:
        raise Unreachable(str(exc)) from exc


def manifest_digest(repo: str, tag: str) -> str:
    request = urllib.request.Request(
        MANIFEST.format(repo=repo, tag=tag),
        headers={"Authorization": f"Bearer {token(repo)}", "Accept": ACCEPT},
        method="HEAD",
    )
    try:
        with urllib.request.urlopen(request, timeout=20) as response:  # noqa: S310
            digest = response.headers.get("Docker-Content-Digest")
    except (urllib.error.URLError, TimeoutError) as exc:
        raise Unreachable(str(exc)) from exc

    if not digest:
        raise Unreachable("registry returned no Docker-Content-Digest header")
    return digest


def main() -> int:
    report.enter_repo_root()

    text = Path(COMPOSE).read_text(encoding="utf-8")
    pins = list(PIN.finditer(text))

    # Negative control. Zero pins would satisfy every assertion below and
    # report a green result about nothing at all.
    if not pins:
        report.warn(GATE, f"{COMPOSE} has no `# renovate:` + digest pairs — cannot conclude")
        report.ok(GATE, "skipped: no pins found to check")
        return 0

    errors: list[str] = []
    for pin in pins:
        repo, tag = pin["repo"], pin["tag"]
        # Docker Hub namespaces single-word repos under library/.
        path = repo if "/" in repo else f"library/{repo}"

        try:
            actual = manifest_digest(path, tag)
        except Unreachable as exc:
            report.warn(GATE, f"{repo}:{tag} — registry unreachable ({exc})")
            report.ok(GATE, "skipped: could not reach the registry, nothing was verified")
            return 0

        if actual == pin["digest"]:
            print(f"  ✓ {repo}:{tag}")
        else:
            errors.append(
                f"{repo}:{tag} is pinned to {pin['digest']} but that tag's "
                f"manifest list is {actual} — either the digest is one "
                f"architecture's sub-manifest (unrunnable elsewhere) or the "
                f"`# renovate:` comment names a different version from the pin"
            )

    for error in errors:
        report.fail(GATE, error)
    if errors:
        return 1

    report.ok(GATE, f"{len(pins)} image pins match their tag's manifest list")
    return 0


if __name__ == "__main__":
    sys.exit(report.guard(GATE, main))

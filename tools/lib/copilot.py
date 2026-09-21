"""Locating the Copilot extension shipped inside VS Code.

Copilot is a BUILT-IN extension, not a marketplace install, so this directory
exists on any machine with VS Code — no seat and no sign-in required. That is
what lets the copilot-check and copilot-smoke gates verify claims for free.
"""

import os
import re
from pathlib import Path

# Basename only, deliberately. A string holding a slash followed by a scanned
# extension is read by the paths gate as a repo file that must exist, and this
# one does not live in the repo.
MANIFEST = "package.json"

_SUBPATH = "Contents/Resources/app/extensions/copilot"

_CANDIDATES = (
    f"/Applications/Visual Studio Code.app/{_SUBPATH}",
    f"/Applications/Visual Studio Code - Insiders.app/{_SUBPATH}",
    f"~/Applications/Visual Studio Code.app/{_SUBPATH}",
    "/usr/share/code/resources/app/extensions/copilot",
    "/usr/share/code-insiders/resources/app/extensions/copilot",
    "/opt/visual-studio-code/resources/app/extensions/copilot",
)


# The standalone CLI unpacks itself here, one directory per version under a
# platform directory. Kept with the tilde unexpanded: `just leaks` blocks a
# literal home path, and rightly so.
CLI_ROOT = "~/.copilot/pkg"
CLI_ENTRYPOINT = "app.js"

# The SQLite span store `otel.dbSpanExporter.enabled` writes. Tilde unexpanded
# for the same reason as CLI_ROOT.
TRACES_DB = "agent-traces.db"
_GLOBAL_STORAGE = (
    "~/Library/Application Support/Code/User/globalStorage/github.copilot-chat",
    "~/Library/Application Support/Code - Insiders/User/globalStorage/github.copilot-chat",
    "~/.config/Code/User/globalStorage/github.copilot-chat",
    "~/.config/Code - Insiders/User/globalStorage/github.copilot-chat",
)

# The extension's own bundled exporter code, relative to the extension dir.
BUNDLE = ("dist", "extension.js")


class OverrideMissing(Exception):
    """An explicit *_DIR override was set but holds nothing usable.

    Raised rather than falling through: an override that silently targets a
    different build reports a result for something other than what was asked
    about, which is the whole subject of this repository.
    """

    def __init__(self, variable: str, path: str, wanted: str) -> None:
        super().__init__(path)
        self.variable = variable
        self.path = path
        self.wanted = wanted

    def __str__(self) -> str:
        return (
            f"{self.variable}={self.path} holds no {self.wanted} — "
            f"refusing to fall back to another build"
        )


def ext_dir() -> Path | None:
    """The installed Copilot extension directory, or None if VS Code is absent.

    COPILOT_EXT_DIR overrides discovery. When it is set it is the ONLY
    candidate — see OverrideMissing.
    """
    override = os.environ.get("COPILOT_EXT_DIR")
    if override:
        if not (Path(override) / MANIFEST).is_file():
            raise OverrideMissing("COPILOT_EXT_DIR", override, MANIFEST)
        return Path(override)

    for candidate in _CANDIDATES:
        path = Path(candidate).expanduser()
        if (path / MANIFEST).is_file():
            return path

    return None


def version_key(name: str) -> tuple[int, ...]:
    """Sort dotted versions numerically. '1.0.54' must outrank '0.0.396'."""
    parts = []
    for chunk in name.split("."):
        digits = "".join(c for c in chunk if c.isdigit())
        parts.append(int(digits) if digits else 0)
    return tuple(parts)


def cli_runtime() -> tuple[Path, str] | None:
    """Newest installed Copilot CLI runtime and its version, or None.

    This is the standalone CLI, not the copy bundled inside the VS Code
    extension — a different implementation with its own behaviour, which is
    precisely why it is worth reading separately.

    COPILOT_CLI_DIR overrides discovery, and when set it is the ONLY candidate.
    """
    override = os.environ.get("COPILOT_CLI_DIR")
    if override:
        path = Path(override)
        if not (path / CLI_ENTRYPOINT).is_file():
            raise OverrideMissing("COPILOT_CLI_DIR", override, CLI_ENTRYPOINT)
        return path, path.name

    root = Path(CLI_ROOT).expanduser()
    if not root.is_dir():
        return None

    found: list[tuple[tuple[int, ...], Path]] = []
    for platform in sorted(root.iterdir()):
        if not platform.is_dir():
            continue
        for version in sorted(platform.iterdir()):
            if (version / CLI_ENTRYPOINT).is_file():
                found.append((version_key(version.name), version))

    if not found:
        return None

    newest = max(found)[1]
    return newest, newest.name


def traces_db() -> Path | None:
    """The SQLite span store, or None when dbSpanExporter has never run.

    COPILOT_TRACES_DB overrides discovery, and when set it is the ONLY
    candidate.
    """
    override = os.environ.get("COPILOT_TRACES_DB")
    if override:
        path = Path(override)
        if not path.is_file():
            raise OverrideMissing("COPILOT_TRACES_DB", override, TRACES_DB)
        return path

    for candidate in _GLOBAL_STORAGE:
        path = Path(candidate).expanduser() / TRACES_DB
        if path.is_file():
            return path

    return None


# The vendor's own DDL is the expected value. Reading it at run time rather
# than transcribing it is what stops this repository's description of the
# schema drifting away from the product that writes it.
_SPANS_DDL = re.compile(r"CREATE TABLE IF NOT EXISTS spans \(([^)]*)\)", re.DOTALL)


def expected_spans_columns(ext_dir: Path) -> set[str] | None:
    """Column names the installed bundle's `spans` DDL declares, or None.

    None means the DDL was not found where expected — the caller must treat
    that as "cannot compare", never as "no drift".
    """
    bundle = ext_dir.joinpath(*BUNDLE)
    if not bundle.is_file():
        return None

    found = _SPANS_DDL.search(bundle.read_text(encoding="utf-8", errors="replace"))
    if not found:
        return None

    columns = set()
    for line in found.group(1).replace("\\n", "\n").replace("\\t", " ").splitlines():
        for part in line.split(","):
            name = part.strip().split(" ")[0].strip()
            if name and name.isidentifier():
                columns.add(name)

    return columns or None

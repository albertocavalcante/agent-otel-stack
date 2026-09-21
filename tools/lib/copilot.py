"""Locating the Copilot extension shipped inside VS Code.

Copilot is a BUILT-IN extension, not a marketplace install, so this directory
exists on any machine with VS Code — no seat and no sign-in required. That is
what lets the copilot-check and copilot-smoke gates verify claims for free.
"""

import os
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


class OverrideMissing(Exception):
    """COPILOT_EXT_DIR was set but holds no manifest.

    Raised rather than falling through: an override that silently targets a
    different build reports a result for something other than what was asked
    about, which is the whole subject of this repository.
    """

    def __init__(self, path: str) -> None:
        super().__init__(path)
        self.path = path


def ext_dir() -> Path | None:
    """The installed Copilot extension directory, or None if VS Code is absent.

    COPILOT_EXT_DIR overrides discovery. When it is set it is the ONLY
    candidate — see OverrideMissing.
    """
    override = os.environ.get("COPILOT_EXT_DIR")
    if override:
        if not (Path(override) / MANIFEST).is_file():
            raise OverrideMissing(override)
        return Path(override)

    for candidate in _CANDIDATES:
        path = Path(candidate).expanduser()
        if (path / MANIFEST).is_file():
            return path

    return None

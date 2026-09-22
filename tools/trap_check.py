#!/usr/bin/env python3
"""Fail if the README's trap table has drifted from its own sections.

Run by `just trap-check`.

The trap table is the front door of this repository, and until now nothing
verified it. `just links` skips any target beginning with `#` and strips
fragments from the rest; `just refs` only handles reference-style links; `just
paths` needs a slash and a file extension. So a misspelled anchor rendered as a
dead link on GitHub and `just check` stayed green.

The count is part of the claim too. "Twelve of those differences are traps" is a
promise about the table beneath it, and a table that grew without the sentence
changing makes the landing page lie.

Since the write-ups moved to their own document, this reads BOTH files: rows
from the README, sections from docs/00-traps.md. A row's anchor now has to
resolve across a file boundary, which `just links` cannot see — it strips
fragments and never checks what they point at.
"""

import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent / "lib"))

import report

GATE = "trap-check"

# The table lives on the landing page; the twelve write-ups live in their own
# document. That split is why this gate reads two files: a row's link has to
# resolve to a heading in the OTHER file, which no other gate checks —
# `just links` strips fragments and never looks at what they point to.
DOC = "README.md"
TRAPS = "docs/00-traps.md"

ROW = re.compile(r"^\|\s*\[(\d+)\]\(" + re.escape(TRAPS) + r"#([^)]+)\)\s*\|")
HEADING = re.compile(r"^###\s+(\d+)\.\s+(.*?)\s*$")
# The count is claimed twice on the landing page: once in the opening
# paragraph and once in the section heading. Both are promises about the table
# beneath them, and a table that grows without them makes the front door lie.
COUNT_SENTENCE = re.compile(r"^(\w+) of those differences are traps", re.IGNORECASE)
SECTION_HEADING = re.compile(r"^##\s+The (\w+) traps\s*$", re.IGNORECASE)

NUMBER_WORDS = {
    1: "one", 2: "two", 3: "three", 4: "four", 5: "five", 6: "six", 7: "seven",
    8: "eight", 9: "nine", 10: "ten", 11: "eleven", 12: "twelve", 13: "thirteen",
    14: "fourteen", 15: "fifteen", 16: "sixteen", 17: "seventeen", 18: "eighteen",
    19: "nineteen", 20: "twenty",
}  # fmt: skip


def anchor_for(heading: str) -> str:
    """GitHub's anchor algorithm, as far as this document exercises it.

    All four rules below are exercised by the existing table: backticks in trap
    2 and 6, `://` in trap 2, and an underscore in trap 6 that must survive.
    """
    text = heading.lower()
    text = text.replace("`", "")
    text = re.sub(r"[^\w\s-]", "", text)  # drops . : / etc, keeps _ via \w
    # GitHub replaces each space with one hyphen. Collapsing runs of
    # whitespace would call a double-space heading's "a--b" anchor "a-b"
    # and certify a dead link.
    text = text.strip().replace(" ", "-")
    return text


def main() -> int:
    report.enter_repo_root()

    lines = Path(DOC).read_text(encoding="utf-8").splitlines()
    trap_lines = Path(TRAPS).read_text(encoding="utf-8").splitlines()

    rows: list[tuple[int, int, str]] = []
    headings: dict[int, tuple[int, str]] = {}
    stated_count: tuple[int, str] | None = None
    stated_heading: tuple[int, str] | None = None

    for n, line in enumerate(lines, 1):
        row = ROW.match(line)
        if row:
            rows.append((n, int(row.group(1)), row.group(2)))
        count = COUNT_SENTENCE.match(line)
        if count:
            stated_count = (n, count.group(1).lower())
        section = SECTION_HEADING.match(line)
        if section:
            stated_heading = (n, section.group(1).lower())

    for n, line in enumerate(trap_lines, 1):
        heading = HEADING.match(line)
        if heading:
            headings[int(heading.group(1))] = (n, heading.group(2))

    errors: list[str] = []

    # Negative control. Zero rows would otherwise satisfy every assertion below
    # and report a green table that does not exist.
    if not rows:
        report.warn(GATE, f"{DOC} has no trap table rows — cannot conclude")
        report.ok(GATE, "skipped: no trap table found to check")
        return 0

    for n, number, anchor in rows:
        if number not in headings:
            errors.append(f"{DOC}:{n} row {number} has no `### {number}.` section in {TRAPS}")
            continue
        heading_line, heading_text = headings[number]
        want = anchor_for(f"{number}. {heading_text}")
        if anchor != want:
            errors.append(
                f"{DOC}:{n} row {number} links to '#{anchor}' but its section at "
                f"{TRAPS}:{heading_line} anchors as '#{want}' — a dead link no "
                f"other gate sees"
            )

    numbers = [number for _, number, _ in rows]
    expected = list(range(1, len(numbers) + 1))
    if numbers != expected:
        errors.append(
            f"{DOC} trap rows are numbered {numbers}, which is not a contiguous "
            f"run from 1 — a reader cannot tell whether one is missing"
        )

    orphans = sorted(set(headings) - set(numbers))
    for number in orphans:
        errors.append(
            f"{TRAPS}:{headings[number][0]} has a `### {number}.` section with no "
            f"row in {DOC}'s trap table"
        )

    # Sections must appear in the order they are numbered. Anchors resolving and
    # the table being contiguous says nothing about where a section physically
    # sits — trap 12 was first written between traps 2 and 3, and every
    # assertion above passed.
    ordered = [number for number, _ in sorted(headings.items(), key=lambda kv: kv[1][0])]
    if ordered != sorted(ordered):
        errors.append(
            f"{TRAPS} trap sections appear in the order {ordered} — a reader "
            f"scrolling past trap 2 should meet trap 3, not trap 12"
        )

    word = NUMBER_WORDS.get(len(rows))
    for label, stated in (("count sentence", stated_count), ("section heading", stated_heading)):
        if stated is None:
            errors.append(f"{DOC} no longer states the trap count in its {label}")
        elif word and stated[1] != word:
            errors.append(
                f"{DOC}:{stated[0]} {label} says '{stated[1]}' but the table has "
                f"{len(rows)} rows ({word})"
            )

    for error in errors:
        report.fail(GATE, error)
    if errors:
        return 1

    report.ok(GATE, f"{len(rows)} traps: every anchor resolves and the count agrees")
    return 0


if __name__ == "__main__":
    sys.exit(report.guard(GATE, main))

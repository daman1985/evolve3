#!/usr/bin/env python3
"""Small Python entry point invoked by the wrapper test-SCRIPTs that
external, subprocess-driven reducers (Perses; later shrinkray) use as
their "is this still interesting?" test. Each invocation:

  1. appends one line to a counter file (so the real number of test-script
     invocations -- the external tool's own "calls" -- is measured exactly
     the same way an in-process Oracle's calls are: real executions only),
  2. re-derives the SAME predicate an in-process task would use for this
     corpus entry, straight from the files on disk (see corpus_recipe.py),
  3. evaluates it against the candidate file's current content, and exits
     0 (interesting -- keep reducing) or 1 (not interesting), the same
     "0 = interesting" convention picire's own SubprocessTest and every
     other delta-debugger test-script uses.

Usage: external_entry.py <entry_dir> <candidate_file> <counter_file>
"""
from __future__ import annotations

import sys
from pathlib import Path

# Make `crux` importable without requiring an editable install: this file
# lives at <repo_root>/crux/bench/external_entry.py.
_REPO_ROOT = Path(__file__).resolve().parents[2]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from crux.bench.corpus_recipe import predicate_for_entry_dir  # noqa: E402


def main(argv: list[str]) -> int:
    if len(argv) != 4:
        print(f"usage: {argv[0]} <entry_dir> <candidate_file> <counter_file>", file=sys.stderr)
        return 2

    entry_dir, candidate_file, counter_file = Path(argv[1]), Path(argv[2]), Path(argv[3])

    with open(counter_file, "a", encoding="utf-8") as f:
        f.write("1\n")

    predicate = predicate_for_entry_dir(entry_dir)
    text = candidate_file.read_text(encoding="utf-8", errors="surrogateescape")

    try:
        ok = predicate(text)
    except Exception:
        # Same contract as crux.crux.core.Oracle: an exception during
        # evaluation counts as a real call (already recorded above) and is
        # treated as "not interesting", never as a crash of the reducer
        # driving us.
        ok = False

    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv))

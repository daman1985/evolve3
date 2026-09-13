"""External adapter for Perses (Sun, Zhang, Zhang, Xu, Su, "Perses:
Syntax-Guided Program Reduction", ICSE 2018; github.com/uw-pluverse/perses,
prebuilt v2.7 deploy jar, per PLAN.md Amendment 1). 2026 surveys still cite
it as the state-of-the-art domain-agnostic reducer for hierarchically
structured input, which is most of this project's corpus.

Faithful-engineering constraint that makes this module different from
every other file in crux/baselines/: Perses is not an in-process
`(problem, kept) -> kept` reducer -- it is an external JVM process driven
entirely through a real file on disk and a real test SCRIPT. This module
exposes `run_perses(...)`, called from the harness (bench/run.py)
alongside, not through, the standard `reduce(problem, kept)` contract; see
bench/run.py's EXTERNAL_METHODS registry for how the two are unified into
one results schema.

Query counting: the generated wrapper test script appends one line to a
counter file on every REAL invocation, then defers to
bench/external_entry.py to evaluate the exact same predicate an in-process
task for this entry would use (see corpus_recipe.py) -- so `calls` here
means exactly what it means everywhere else: real test executions only.
Perses's own caches (--query-caching, --pass-level-caching, --edit-caching)
are left ON at their published defaults, so a config it already knows the
answer to never reaches the wrapper script at all, exactly analogous to
every in-process Oracle's own frozenset cache absorbing a repeat before it
becomes a real call.

Language selection: `--list-langs` on this jar (checked directly, not
assumed) supports c, cpp, go, java, javascript, python3, rust, scala,
jackson-yaml, xml, and several more, plus generic `line` /
`dyck-brace(-parenthesis)` modes -- but NOT json, css, or typescript as
their own grammars (typescript is close to javascript but not a strict
superset Perses can parse as such, so treating .ts as javascript would be
dishonest -- silently a different, weaker guarantee than "reduced under
its own grammar"). Corpus entries in those four formats fall back to the
generic `line` mode: still a real Perses run, just without a
language-specific grammar backing it, and recorded as such
(`used_fallback_lang=True`) rather than silently passed off as native
support.
"""
from __future__ import annotations

import shutil
import subprocess
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

DEFAULT_JAR = Path("/tmp/perses_deploy.jar")
_ENTRY_POINT = Path(__file__).resolve().parents[1] / "bench" / "external_entry.py"

# Verified this round via `java -jar perses_deploy.jar --list-langs`
# against the actual v2.7 jar, not assumed from documentation.
LANG_FOR_FORMAT = {
    "python": "python3",
    "cpp": "cpp",
    "go": "go",
    "javascript": "javascript",
    "rust": "rust",
}
FALLBACK_LANG = "line"


@dataclass
class PersesResult:
    text: str
    calls: int
    lang_used: str
    used_fallback_lang: bool
    seconds: float
    timed_out: bool
    returncode: Optional[int]
    error: Optional[str] = None


def run_perses(
    entry_dir: Path,
    original_path: Path,
    fmt: str,
    work_dir: Path,
    timeout: float,
    jar_path: Path = DEFAULT_JAR,
) -> PersesResult:
    # Perses changes the working directory to a fresh per-test scratch dir
    # for every single test-script invocation (verified this round), so
    # every path baked into the generated script other than the candidate
    # file itself must be absolute -- a relative entry_dir/work_dir would
    # resolve against whatever directory THAT invocation happens to be in,
    # not the one it was written relative to.
    entry_dir = Path(entry_dir).resolve()
    original_path = Path(original_path).resolve()
    work_dir = Path(work_dir).resolve()
    work_dir.mkdir(parents=True, exist_ok=True)

    input_copy = work_dir / original_path.name
    shutil.copyfile(original_path, input_copy)

    counter_path = work_dir / "counter.txt"
    counter_path.write_text("", encoding="utf-8")

    used_fallback_lang = fmt not in LANG_FOR_FORMAT
    lang = LANG_FOR_FORMAT.get(fmt, FALLBACK_LANG)

    # Perses copies the candidate into a fresh per-test working directory
    # (verified this round by direct observation) and runs the script with
    # cwd set there, expecting it to look at the file by its ORIGINAL
    # basename relative to cwd -- not a fixed absolute path, which would
    # silently keep re-testing the pristine original forever.
    script_path = work_dir / "test.sh"
    script_path.write_text(
        "#!/bin/bash\n"
        "set -e\n"
        f'exec python3 "{_ENTRY_POINT}" "{entry_dir}" "$(pwd)/{input_copy.name}" "{counter_path}"\n',
        encoding="utf-8",
    )
    script_path.chmod(0o755)

    output_dir = work_dir / "out"
    if output_dir.exists():
        shutil.rmtree(output_dir)
    output_dir.mkdir()

    cmd = [
        "java", "-jar", str(jar_path),
        "--test-script", str(script_path),
        "--input-file", str(input_copy),
        "--output-dir", str(output_dir),
        "--lang", lang,
        # Reproducible, single-threaded, quiet: a fair apples-to-apples run
        # against our own single-threaded/deterministic in-process
        # methods, per this round's brief.
        "--fully-deterministic-mode", "true",
        "--threads", "1",
        "--verbosity", "SEVERE",
        "--hide-timestamps", "true",
        # Perses' own published defaults -- left ON explicitly rather than
        # implicitly, per instruction not to weaken them.
        "--query-caching", "true",
        "--pass-level-caching", "true",
        "--edit-caching", "true",
    ]

    start = time.monotonic()
    timed_out = False
    returncode: Optional[int] = None
    error = None
    try:
        proc = subprocess.run(cmd, cwd=work_dir, capture_output=True, timeout=timeout, check=False)
        returncode = proc.returncode
        if returncode != 0:
            error = f"perses exited {returncode}: {proc.stderr.decode('utf-8', 'replace')[-2000:]}"
    except subprocess.TimeoutExpired:
        timed_out = True
        error = f"perses exceeded the {timeout:.0f}s per-task wall-clock cap"
    elapsed = time.monotonic() - start

    calls = 0
    if counter_path.exists():
        with counter_path.open(encoding="utf-8") as f:
            calls = sum(1 for _ in f)

    reduced_path = output_dir / input_copy.name
    if reduced_path.exists():
        text = reduced_path.read_text(encoding="utf-8", errors="surrogateescape")
    else:
        # Timed out or crashed before writing an output: fall back to the
        # original input so the harness always has *something* to
        # independently validate -- it will (correctly) score this as the
        # worst case, not silently drop the task.
        text = original_path.read_text(encoding="utf-8", errors="surrogateescape")
        if error is None:
            error = "perses produced no output file"

    return PersesResult(
        text=text,
        calls=calls,
        lang_used=lang,
        used_fallback_lang=used_fallback_lang,
        seconds=elapsed,
        timed_out=timed_out,
        returncode=returncode,
        error=error,
    )

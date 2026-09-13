"""Faithful reference implementations of competing reduction methods.

Every module here exposes a single ``reduce(problem, kept) -> kept``
function (except ``perses.py``, which drives an external process and is
wired into the benchmark harness separately -- see its module docstring).
Baselines must stay faithful to their publication: do not weaken and do not
"improve" them. Cite the paper's step in a comment for each non-obvious
line.
"""

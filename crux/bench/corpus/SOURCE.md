# Benchmark corpus provenance

The `original.*` inputs and `meta.json` descriptors in this directory are
copied verbatim from the evaluation corpus of **shrinkray**
(https://github.com/DRMacIver/shrinkray), MIT License, © 2023 David R. MacIver.
Commit fetched 2026-09-13, shrinkray version 26.7.8.0.

They are used here as *inputs only*. The oracles in `crux/bench/tasks/` are
written independently for this project (cheap in-process predicates that
approximate each bug's real requirement, so that a benchmark run costs seconds
rather than hours). `setup.sh` build scripts were deliberately not copied.

shrinkray's own published reduced sizes for these entries are recorded in
`crux/bench/shrinkray_published.json` and used as an external reference point
for final-size comparison.

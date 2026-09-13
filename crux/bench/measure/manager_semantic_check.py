"""Independent check: after snapping brace balance, WHY do cpp candidates fail?
Written without reading the architect's script, to avoid anchoring."""
import glob, os, random, re, subprocess, tempfile, collections

rng = random.Random(7)

def snap(text):
    """Grammar-free repair: drop unmatched closers, append missing closers."""
    out, stack = [], []
    pairs = {'(':')', '[':']', '{':'}'}
    closers = {v:k for k,v in pairs.items()}
    for ch in text:
        if ch in pairs: stack.append(ch); out.append(ch)
        elif ch in closers:
            if stack and stack[-1] == closers[ch]: stack.pop(); out.append(ch)
            else: pass                      # unmatched closer -> drop
        else: out.append(ch)
    while stack: out.append(pairs[stack.pop()])   # append missing closers
    return ''.join(out)

SYNTAX = re.compile(r"expected |extraneous |unterminated |stray |missing terminating|"
                    r"expected unqualified-id|expected expression|expected '")
SEMANTIC = re.compile(r"undeclared identifier|unknown type name|no member named|"
                      r"no matching |no template named|does not name a type|"
                      r"use of undeclared|implicit instantiation|incomplete type|"
                      r"cannot initialize|no type named|out-of-line definition")

def classify(err):
    first = ""
    for line in err.splitlines():
        if ": error: " in line: first = line.split(": error: ",1)[1]; break
    if not first: return "other", ""
    if SEMANTIC.search(first): return "semantic", first
    if SYNTAX.search(first): return "syntax", first
    return "other", first

tally = collections.Counter(); examples = collections.defaultdict(list); ok = tot = 0
for f in sorted(glob.glob('crux/bench/corpus/*/original.cpp')):
    text = open(f).read(); lines = text.splitlines(keepends=True); n = len(lines)
    for _ in range(40):
        k = max(1, int(n * rng.choice([0.1, 0.3, 0.5])))
        s = rng.randrange(0, max(1, n - k))
        cand = snap(''.join(l for i, l in enumerate(lines) if not (s <= i < s + k)))
        with tempfile.NamedTemporaryFile('w', suffix='.cpp', delete=False) as fh:
            fh.write(cand); p = fh.name
        try:
            r = subprocess.run(['clang','-std=c++14','-fsyntax-only',p],
                               capture_output=True, timeout=30, text=True)
        except Exception:
            os.unlink(p); continue
        os.unlink(p); tot += 1
        if r.returncode == 0: ok += 1; continue
        kind, msg = classify(r.stderr); tally[kind] += 1
        if len(examples[kind]) < 2 and msg: examples[kind].append(msg[:70])

fail = sum(tally.values())
print(f"balance-snapped cpp candidates: {tot} total, {ok} compile ({100*ok/tot:.1f}%), {fail} fail")
print("\nof the FAILURES:")
for k, v in tally.most_common():
    print(f"  {k:<10}{v:>5}  {100*v/fail:>5.1f}%   e.g. {examples[k][0] if examples[k] else ''}")

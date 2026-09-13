"""Follow-ups:
 (1) Python: does a grammar-free INDENTATION-BLOCK filter rescue .py the way Dyck
     balance rescues .js?  (Dyck filter moved .py only 32.3% -> 34.8%.)
 (2) C++: of the 77% of *balance-snapped* line candidates that still fail
     `clang -fsyntax-only`, how many fail at PARSE level vs SEMANTIC level?
     That decides whether a grammar-free layer can ever be enough for C++.
"""
import ast, random, subprocess, sys, os, glob, tempfile, re
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from syntax_filter_rates import lex_state, balanced_span, line_offsets  # reuse

rng = random.Random(1)

def py_ok(t):
    try: ast.parse(t); return True
    except Exception: return False

def cpp_err(t):
    with tempfile.NamedTemporaryFile('w', suffix='.cpp', delete=False) as f:
        f.write(t); p = f.name
    try:
        r = subprocess.run(['clang','-std=c++14','-fsyntax-only','-ferror-limit=1',p],
                           capture_output=True, timeout=30, text=True)
        if r.returncode == 0: return None
        m = re.search(r'error: (.*)', r.stderr)
        return m.group(1)[:90] if m else 'unknown'
    except Exception:
        return 'timeout'
    finally:
        os.unlink(p)

SEMANTIC = re.compile(r'undeclared|unknown type|no member|no matching|not a (class|type)|'
                      r'incomplete type|no template named|implicit instantiation|'
                      r'does not (name|refer)|redefinition|cannot initialize|'
                      r'no viable|use of undeclared|unknown class name|variable has', re.I)

# ---------- (1) Python indentation-block filter ----------
def indent_of(line):
    s = line.rstrip('\n')
    if not s.strip(): return None
    return len(s) - len(s.lstrip())

def suite_safe(lines, s, e):
    """Grammar-free: is deleting lines[s:e) indentation-safe?"""
    if s >= e: return False
    inds = [indent_of(l) for l in lines[s:e]]
    body = [i for i in inds if i is not None]
    if not body: return True
    base = min(body)
    # line after the span must dedent to at most base (else we orphan a deeper block)
    nxt = next((indent_of(l) for l in lines[e:] if indent_of(l) is not None), 0)
    if nxt > base: return False
    # preceding non-blank line: if it opens a suite (ends ':'), the suite must survive
    prev = next((l for l in reversed(lines[:s]) if l.strip()), None)
    if prev is not None and prev.rstrip().endswith(':'):
        pin = indent_of(prev)
        if nxt <= pin: return False          # suite would become empty
    return True

def snap_lines(pred, s, e):
    ee = e
    while ee > s and not pred(s, ee): ee -= 1
    if ee > s: return (s, ee)
    ss = s
    while ss < e and not pred(ss, e): ss += 1
    if ss < e: return (ss, e)
    return None

print("=== (1) Python line-granularity candidates ===")
tot = {'raw':[0,0], 'dyck':[0,0], 'indent':[0,0], 'both':[0,0]}
for f in sorted(glob.glob('/home/user/evolve3/crux/bench/corpus/*/original.py')):
    text = open(f).read()
    if not py_ok(text): continue
    lines = text.splitlines(keepends=True)
    offs  = line_offsets(text)
    depth, quiet = lex_state(text, '.py')
    nl = len(lines)
    if nl < 8: continue
    dyck = lambda s, e: balanced_span(depth, quiet, offs[s], offs[min(e, nl)])
    both = lambda s, e: dyck(s, e) and suite_safe(lines, s, e)
    for frac in (0.1, 0.3, 0.5):
        k = max(1, int(nl*frac))
        for _ in range(14):
            s = rng.randrange(0, max(1, nl-k)); e = min(s+k, nl)
            def score(bucket, sp):
                if sp is None: tot[bucket][1] += 1; return
                a, b = sp
                tot[bucket][0] += py_ok(''.join(lines[:a]) + ''.join(lines[b:]))
                tot[bucket][1] += 1
            tot['raw'][0] += py_ok(''.join(lines[:s]) + ''.join(lines[e:])); tot['raw'][1] += 1
            score('dyck',   snap_lines(dyck, s, e))
            score('indent', snap_lines(lambda a,b: suite_safe(lines,a,b), s, e))
            score('both',   snap_lines(both, s, e))
for k_, (ok, n) in tot.items():
    print(f"  {k_:<8} parses: {100*ok/max(1,n):5.1f}%  ({ok}/{n})")

# ---------- (2) C++ residual: syntax vs semantics ----------
print("\n=== (2) C++ balance-snapped line candidates that still fail ===")
syn = sem = ok = 0
examples = []
for f in sorted(glob.glob('/home/user/evolve3/crux/bench/corpus/*/original.cpp')):
    text = open(f).read()
    if cpp_err(text) is not None: continue
    offs = line_offsets(text); nl = len(offs)-1
    depth, quiet = lex_state(text, '.cpp')
    pred = lambda s, e: balanced_span(depth, quiet, offs[s], offs[min(e, nl)])
    for frac in (0.1, 0.3, 0.5):
        k = max(1, int(nl*frac))
        for _ in range(8):
            s = rng.randrange(0, max(1, nl-k)); e = min(s+k, nl)
            sp = snap_lines(pred, s, e)
            if sp is None: continue
            a, b = sp
            err = cpp_err(text[:offs[a]] + text[offs[b]:])
            if err is None: ok += 1
            elif SEMANTIC.search(err): sem += 1; examples.append(('SEM', err))
            else: syn += 1; examples.append(('SYN', err))
n = ok+sem+syn
print(f"  compiles clean : {ok:4d}  ({100*ok/max(1,n):.1f}%)")
print(f"  SEMANTIC error : {sem:4d}  ({100*sem/max(1,n):.1f}%)  <- needs a front-end, not a delimiter filter")
print(f"  SYNTAX   error : {syn:4d}  ({100*syn/max(1,n):.1f}%)  <- a better grammar-free filter could catch some")
print("  sample errors:")
seen = set()
for tag, e in examples:
    key = (tag, e.split("'")[0][:40])
    if key in seen: continue
    seen.add(key); print(f"    [{tag}] {e}")
    if len(seen) >= 10: break

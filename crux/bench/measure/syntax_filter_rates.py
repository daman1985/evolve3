"""Does a FREE local delimiter-balance filter rescue the parse rate?

Coordinator measured: contiguous chunk deletions parse 22.9% (line), 7.9% (char).
Question this answers: if the reducer refuses to *issue* a candidate whose deleted
span is not delimiter-balanced (a check it can do itself, 0 oracle calls), what is
the parse rate of the candidates it does issue -- and how many candidates survive?

Also measures SNAPPING: given an arbitrary proposed span, shrink it to the largest
balanced sub-span. That is what a generator would actually do (no rejection sampling).
"""
import ast, json, random, subprocess, sys, os, glob, tempfile

# ---------- real parsers ----------
def valid_py(t):
    try: ast.parse(t); return True
    except Exception: return False
def valid_json(t):
    try: json.loads(t); return True
    except Exception: return False
def _run(t, suffix, cmd):
    with tempfile.NamedTemporaryFile('w', suffix=suffix, delete=False) as f:
        f.write(t); p = f.name
    try:
        return subprocess.run(cmd + [p], capture_output=True, timeout=30).returncode == 0
    except Exception:
        return False
    finally:
        os.unlink(p)
def valid_js(t):  return _run(t, '.js',  ['node', '--check'])
def valid_cpp(t): return _run(t, '.cpp', ['clang', '-std=c++14', '-fsyntax-only'])

CHECK = {'.py': valid_py, '.json': valid_json, '.js': valid_js, '.cpp': valid_cpp}

# ---------- the free local filter: per-character lexical state ----------
OPEN, CLOSE = '([{', ')]}'
PAIR = {')': '(', ']': '[', '}': '{'}

def lex_state(text, ext):
    """depth[i] = bracket depth before char i; quiet[i] = True if char i is at a
    position not inside a string/comment. O(n), no grammar."""
    n = len(text)
    depth = [0]*(n+1)
    quiet = [True]*(n+1)
    d = 0
    i = 0
    instr = None        # quote char
    incomment = None    # 'line' | 'block'
    line_comment = ('#',) if ext == '.py' else ('//',)
    block = ext in ('.cpp', '.js')
    while i < n:
        depth[i] = d
        quiet[i] = (instr is None and incomment is None)
        c = text[i]
        if incomment == 'line':
            if c == '\n': incomment = None
            i += 1; continue
        if incomment == 'block':
            if c == '*' and i+1 < n and text[i+1] == '/':
                incomment = None; depth[i+1] = d; quiet[i+1] = False; i += 2; continue
            i += 1; continue
        if instr is not None:
            if c == '\\':
                if i+1 <= n: depth[i+1] = d; quiet[i+1] = False
                i += 2; continue
            if c == instr: instr = None
            i += 1; continue
        # quiet zone
        if ext != '.json' and text.startswith(line_comment[0], i):
            incomment = 'line'; i += len(line_comment[0]); continue
        if block and text.startswith('/*', i):
            incomment = 'block'; i += 2; continue
        if c in '"\'' and (ext != '.json' or c == '"'):
            instr = c; i += 1; continue
        if c in OPEN: d += 1
        elif c in CLOSE: d = max(0, d-1)
        i += 1
    depth[n] = d
    quiet[n] = (instr is None and incomment is None)
    return depth, quiet

def balanced_span(depth, quiet, i, j):
    """Can chars [i,j) be deleted without disturbing delimiter balance?"""
    if i >= j: return False
    if not (quiet[i] and quiet[j]): return False
    if depth[i] != depth[j]: return False
    base = depth[i]
    # never closes something opened before the span
    for t in range(i, j+1):
        if depth[t] < base: return False
    return True

def line_offsets(text):
    offs = [0]
    for ch_i, ch in enumerate(text):
        if ch == '\n': offs.append(ch_i+1)
    if offs[-1] != len(text): offs.append(len(text))
    return offs

def snap(depth, quiet, i, j):
    """Largest balanced sub-span of [i,j): shrink right edge then left edge."""
    jj = j
    while jj > i and not balanced_span(depth, quiet, i, jj): jj -= 1
    if jj > i: return (i, jj)
    ii = i
    while ii < j and not balanced_span(depth, quiet, ii, j): ii += 1
    if ii < j: return (ii, j)
    return None

# ---------- experiment ----------
rng = random.Random(0)
rows = []
CORPUS = sorted(glob.glob('/home/user/evolve3/crux/bench/corpus/*/'))

for d in CORPUS:
    for f in glob.glob(d+'original.*'):
        ext = os.path.splitext(f)[1]
        if ext not in CHECK: continue
        text = open(f).read()
        chk = CHECK[ext]
        if not chk(text): continue
        if len(text) > 12000: continue
        depth, quiet = lex_state(text, ext)
        offs = line_offsets(text)
        name = os.path.basename(d.rstrip('/'))

        for gran in ('line', 'char'):
            if gran == 'char' and len(text) > 4000: continue
            units = offs if gran == 'line' else list(range(len(text)+1))
            nu = len(units)-1
            if nu < 8: continue
            for frac in (0.1, 0.3, 0.5):
                k = max(1, int(nu*frac))
                for _ in range(8):
                    s = rng.randrange(0, max(1, nu-k))
                    i, j = units[s], units[min(s+k, nu)]
                    # A: raw contiguous chunk (coordinator's "chunk" cell)
                    raw_ok = chk(text[:i] + text[j:])
                    # B: is it balanced by the free filter?
                    bal = balanced_span(depth, quiet, i, j)
                    # C: snapped to largest balanced sub-span
                    sp = snap(depth, quiet, i, j)
                    if sp:
                        si, sj = sp
                        snap_ok = chk(text[:si] + text[sj:])
                        retain = (sj-si) / max(1, j-i)
                    else:
                        snap_ok, retain = None, 0.0
                    rows.append((name, ext, gran, frac, raw_ok, bal, snap_ok, retain))

def pct(num, den): return f"{100*num/den:5.1f}%  ({num}/{den})" if den else "   n/a"

print("=== A. raw contiguous chunk (baseline, should match coordinator) ===")
for gran in ('line','char'):
    r = [x for x in rows if x[2]==gran]
    print(f"  {gran:<6} parses: {pct(sum(1 for x in r if x[4]), len(r))}")

print("\n=== B. how many raw contiguous chunks pass the FREE balance filter (yield) ===")
for gran in ('line','char'):
    r = [x for x in rows if x[2]==gran]
    print(f"  {gran:<6} balanced: {pct(sum(1 for x in r if x[5]), len(r))}")

print("\n=== C. parse rate OF THE FILTERED CANDIDATES (balanced only) ===")
for gran in ('line','char'):
    r = [x for x in rows if x[2]==gran and x[5]]
    print(f"  {gran:<6} parses: {pct(sum(1 for x in r if x[4]), len(r))}")

print("\n=== D. parse rate after SNAPPING an arbitrary span to its largest balanced sub-span ===")
for gran in ('line','char'):
    r = [x for x in rows if x[2]==gran and x[6] is not None]
    tot = [x for x in rows if x[2]==gran]
    print(f"  {gran:<6} snap found: {pct(len(r), len(tot))}   parses: {pct(sum(1 for x in r if x[6]), len(r))}"
          f"   mean size retained: {100*sum(x[7] for x in r)/max(1,len(r)):.0f}%")

print("\n=== E. by language, line granularity, snapped ===")
langs = sorted({x[1] for x in rows})
for ext in langs:
    r = [x for x in rows if x[1]==ext and x[2]=='line']
    rb = [x for x in r if x[6] is not None]
    print(f"  {ext:<7} raw {pct(sum(1 for x in r if x[4]), len(r)):<20} snapped {pct(sum(1 for x in rb if x[6]), len(rb))}")

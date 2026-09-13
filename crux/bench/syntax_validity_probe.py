"""How often is a deletion candidate syntactically invalid? Measure, don't assume.
Uses REAL parsers (not our cheap oracle), on the real corpus files."""
import ast, json, random, subprocess, sys, os, glob, tempfile

def valid_py(t):
    try: ast.parse(t); return True
    except Exception: return False
def valid_json(t):
    try: json.loads(t); return True
    except Exception: return False
def valid_js(t):
    with tempfile.NamedTemporaryFile('w',suffix='.js',delete=False) as f: f.write(t); p=f.name
    try: return subprocess.run(['node','--check',p],capture_output=True,timeout=20).returncode==0
    except Exception: return False
    finally: os.unlink(p)
def valid_cpp(t):
    with tempfile.NamedTemporaryFile('w',suffix='.cpp',delete=False) as f: f.write(t); p=f.name
    try: return subprocess.run(['clang','-std=c++14','-fsyntax-only',p],capture_output=True,timeout=30).returncode==0
    except Exception: return False
    finally: os.unlink(p)

CHECK={'.py':valid_py,'.json':valid_json,'.js':valid_js,'.cpp':valid_cpp}
rng=random.Random(0)

def sample(elems, frac, mode):
    n=len(elems); k=max(1,int(n*frac))
    if mode=='scatter':                       # uniform random deletion (MUS/ProbDD-shaped)
        drop=set(rng.sample(range(n),k))
    else:                                     # contiguous chunk deletion (ddmin-shaped)
        s=rng.randrange(0,max(1,n-k)); drop=set(range(s,s+k))
    return ''.join(e for i,e in enumerate(elems) if i not in drop)

rows=[]
for d in sorted(glob.glob('crux/bench/corpus/*/')):
    for f in glob.glob(d+'original.*'):
        ext=os.path.splitext(f)[1]
        if ext not in CHECK: continue
        text=open(f).read(); chk=CHECK[ext]
        if not chk(text): continue            # only measure where the original itself parses
        for gran,elems in (('line',text.splitlines(keepends=True)),('char',list(text))):
            if gran=='char' and len(text)>4000: continue
            for mode in ('scatter','chunk'):
                for frac in (0.1,0.3,0.5):
                    trials=12; ok=sum(chk(sample(elems,frac,mode)) for _ in range(trials))
                    rows.append((os.path.basename(d.rstrip('/')),ext,gran,mode,frac,ok,trials))

agg={}
for _,ext,gran,mode,frac,ok,tr in rows:
    key=(gran,mode); a=agg.setdefault(key,[0,0]); a[0]+=ok; a[1]+=tr
print(f"{'granularity':<12}{'candidate shape':<18}{'parses OK':>12}")
for (gran,mode),(ok,tr) in sorted(agg.items()):
    print(f"{gran:<12}{mode:<18}{100*ok/tr:>11.1f}%   ({ok}/{tr})")
print()
per={}
for name,ext,gran,mode,frac,ok,tr in rows:
    if gran!='line' or mode!='scatter': continue
    a=per.setdefault(ext,[0,0]); a[0]+=ok; a[1]+=tr
print("line granularity, scattered deletion, by language:")
for ext,(ok,tr) in sorted(per.items()): print(f"  {ext:<8}{100*ok/tr:>6.1f}%  ({ok}/{tr})")

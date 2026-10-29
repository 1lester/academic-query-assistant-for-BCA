"""Question engine: split OCR'd papers into single questions, normalise them and
group repeats. No database code here, so it is easy to test."""
import re

STOP = set("""a an the of in on to for and or with by from is are was were be as at it its this that these those
what which who whom how why when where define explain write describe discuss state list give briefly short note
notes on about differentiate between distinguish compare following any all each example examples answer
marks mark write down mention brief detail detailed elaborate illustrate""".split())

INSTR = re.compile(r"answer any|answer all|marks|time\s*:|max\.?|maximum|note\s*:|instruction|section|"
                   r"part\s*[-:]?\s*[a-e]\b|seat no|register|reg\.? no|question paper|b\.?c\.?a|university|"
                   r"semester|duration|code\s*:|paper\s*code|\bcourse\b|each question|compulsory", re.I)

NUM = re.compile(r"^\s*(?:q\.?\s*)?(\d{1,2})\s*[.)\-:]\s+(.*)", re.I)
SUB = re.compile(r"^\s*\(?([a-j]|[ivx]{1,4})\s*[.)]\s+(.*)", re.I)


def split_questions(text):
    """Return a list of dicts {text, part} found in one paper's OCR text."""
    out, cur, part = [], "", ""
    def flush():
        nonlocal cur
        t = re.sub(r"\s+", " ", cur).strip(" -_|.")
        cur = ""
        t = re.sub(r"^\(?[a-j]\)\s*", "", t)
        if 18 <= len(t) <= 450 and not INSTR.search(t[:60]) and re.search(r"[A-Za-z]{3,}", t):
            out.append({"text": t, "part": part})
    for raw in text.splitlines():
        line = raw.strip()
        if not line:
            continue
        pm = re.search(r"\bpart\s*[-:]?\s*([a-e])\b", line, re.I)
        if pm and len(line) < 60:
            flush(); part = pm.group(1).upper(); continue
        m = NUM.match(line) or SUB.match(line)
        if m:
            flush(); cur = m.group(2)
        elif cur:
            cur += " " + line
    flush()
    return out


def norm_tokens(q):
    t = re.sub(r"[^a-z0-9 ]", " ", q.lower())
    t = re.sub(r"\b(\w+?)(?:es|s)\b", r"\1", t)          # crude plural removal
    return frozenset(w for w in t.split() if w not in STOP and len(w) > 1)


def similar(a, b):
    if not a or not b:
        return False
    inter = len(a & b)
    if inter == 0:
        return False
    jac = inter / len(a | b)
    contain = inter / min(len(a), len(b))
    return jac >= 0.7 or (contain >= 0.85 and min(len(a), len(b)) >= 3)


def group_questions(items):
    """items: list of dicts with 'tokens'. Returns list of groups (list of item indexes)."""
    groups = []   # each: {"rep": tokens, "idx": [..]}
    for i, it in enumerate(items):
        for g in groups:
            if similar(it["tokens"], g["rep"]):
                g["idx"].append(i)
                break
        else:
            groups.append({"rep": it["tokens"], "idx": [i]})
    return [g["idx"] for g in groups]


ORD = {1: "1st", 2: "2nd", 3: "3rd", 4: "4th", 5: "5th", 6: "6th"}

def parse_title(title):
    sem = None
    m = (re.search(r"\b([1-6])\s*(?:st|nd|rd|th)?\s*sem", title, re.I)
         or re.search(r"sem(?:ester)?\s*([1-6])\b", title, re.I))
    if m:
        sem = int(m.group(1))
    y = re.search(r"\b(20\d\d)\b", title)
    year = y.group(1) if y else "Other"
    last = title.split(" - ")[-1]
    subject = re.sub(r"\b[1-6]\s*(?:st|nd|rd|th)?\s*sem(?:ester)?\b", "", last, flags=re.I)
    subject = re.sub(r"\bBCA\b|\b20\d\d\b|\b(?:sep|sept|oct|march|july|august)\b[-/ ]*", "", subject, flags=re.I)
    subject = re.sub(r"\s+", " ", subject).strip(" -_,()")
    return sem, year, (subject if len(subject) > 2 else last.strip())


NOISE = set("""min max nep repeaters repeater regular old new paper papers question questions sem semester bca
nov dec jan feb mar apr may jun jul aug sep sept oct march july august f""".split())

def canon_subject(subject):
    """Clean messy folder/file names: 'Operating-System-min', 'Data-Structures2018' -> words only."""
    t = subject.lower()
    t = re.sub(r"\([^)]*\)?", " ", t)            # (NEP), (F, (15622) ...
    t = re.sub(r"[-_/.,]+", " ", t)
    t = re.sub(r"\b\d+\s*(?:st|nd|rd|th)\b", " ", t)   # 5th, 3rd
    t = re.sub(r"\d+", " ", t)                    # years, codes, numbers
    return " ".join(w for w in t.split() if w not in NOISE)

def subject_key(subject):
    k = re.sub(r"[^a-z]", "", canon_subject(subject))
    return k.rstrip("s") if len(k) > 3 else k

def merge_keys(counts):
    """counts: {key: n}. Maps near-identical keys (typos like engeering/engineering) to one key."""
    from difflib import SequenceMatcher
    canon, out = [], {}
    for k in sorted(counts, key=lambda x: -counts[x]):
        for c in canon:
            if SequenceMatcher(None, k, c).ratio() >= 0.88:
                out[k] = c
                break
        else:
            canon.append(k); out[k] = k
    return out


# ---------- Topics: which concepts keep coming back (more useful than exact repeats) ----------
GENERIC = set("""different type types various using use used give list name mention step steps advantage advantages
disadvantage disadvantages feature features characteristic characteristics role importance need purpose working work
application applications brief detail compare comparison difference differences merit merits demerit demerits
definition meaning concept concepts following based basic basics general overview introduction term terms
program programs programming question questions answer answers marks paper explain define write state
discuss describe illustrate elaborate summarise summarize ways way process steps involved also its their
what which where when why how whose there here does done make made like such some many most more less
good best simple small large major minor important main key common single multiple both either neither
given suitable proper correct example examples diagram diagrams figure draw neat""".split())
KEEP_SINGLE = {"process", "data"}   # too broad as one-word topics; still allowed inside phrases like "data structure"


def _stem(w):
    if len(w) > 4 and w.endswith("ies"):
        return w[:-3] + "y"
    if len(w) > 4 and w.endswith("s") and not w.endswith("ss"):
        return w[:-1]
    return w


def topic_terms(text):
    """Ordered list of (key, display) for 1- and 2-word phrases inside one question."""
    words = re.findall(r"[a-zA-Z]+", text.lower())
    runs, cur = [], []
    for w in words:
        if len(w) < 3 or w in STOP or w in GENERIC or _stem(w) in GENERIC:
            if cur: runs.append(cur); cur = []
        else:
            cur.append(w)
    if cur: runs.append(cur)
    out = []
    for run in runs:
        for w in run:
            if len(w) >= 4 and w not in KEEP_SINGLE:
                out.append((_stem(w), w))
        for a, b in zip(run, run[1:]):
            out.append((_stem(a) + " " + _stem(b), a + " " + b))
    return out


def extract_topics(items, min_years=2, top=40):
    """items: dicts with 'text' and 'year'. Returns topics ranked by number of different years."""
    stat = {}
    for it in items:
        seen = set()
        for key, disp in topic_terms(it["text"]):
            if key in seen:
                continue
            seen.add(key)
            s = stat.setdefault(key, {"years": set(), "n": 0, "disp": {}, "ex": []})
            s["years"].add(it["year"]); s["n"] += 1
            s["disp"][disp] = s["disp"].get(disp, 0) + 1
            if len(s["ex"]) < 40:
                s["ex"].append((it["year"], it["text"]))
    rows = []
    for key, s in stat.items():
        if len(s["years"]) < min_years:
            continue
        rows.append((key, s))
    # a one-word topic that is just part of a stronger phrase is dropped
    phrases = {k: s for k, s in rows if " " in k}
    keep = []
    for key, s in rows:
        if " " not in key:
            if any(key in p.split() and len(ps["years"]) >= 0.8 * len(s["years"]) for p, ps in phrases.items()):
                continue
        keep.append((key, s))
    keep.sort(key=lambda r: (-len(r[1]["years"]), -r[1]["n"], -len(r[0])))
    out = []
    for key, s in keep[:top]:
        disp = max(s["disp"], key=s["disp"].get).title()
        ex = sorted(s["ex"], key=lambda e: e[0], reverse=True)
        seen_t, examples = set(), []
        for y, t in ex:
            if t not in seen_t:
                seen_t.add(t); examples.append(f"{y}: {t}")
            if len(examples) == 3:
                break
        out.append({"topic": disp, "years": sorted(s["years"]), "n": s["n"], "examples": examples})
    return out

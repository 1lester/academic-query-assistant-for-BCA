"""Makes messy student texts easier for the search: SMS short forms, subject initials, roman semesters, typos.

  imp qs ds 1sem      ->  important questions discrete structures 1 sem   (1st sem decides which "ds")
  compputer arcihtecture -> computer architecture
Nothing here calls the AI; it only rewrites the query before the normal search. If anything goes wrong the
original query is used unchanged.
"""
import re
from difflib import get_close_matches

SMS = {"imp": "important", "imps": "important", "qs": "questions", "qn": "question", "qns": "questions", "ques": "questions",
       "ppr": "paper", "pprs": "papers", "papr": "paper", "prev": "previous", "yr": "year", "yrs": "years", "pls": "", "plz": "", "pls.": ""}
ROMAN = {"i": 1, "ii": 2, "iii": 3, "iv": 4, "v": 5, "vi": 6}
SMALL = {"is", "in", "it", "of", "on", "to", "at", "as", "an", "or", "be", "by", "do", "if", "me", "my", "no", "so", "up", "we", "he", "the",
         "and", "for", "are", "can", "you", "has", "was", "not", "all", "any", "how", "why", "who", "sem"}
QUERY_WORDS = ("important questions question topics topic latest recent paper papers repeated previous year years syllabus semester "
               "explain define difference between notes model mock likely expected please show give tell about unit chapter").split()
_cache = {}


def initials(name):
    w = [x for x in re.findall(r"[A-Za-z]+", name) if x.lower() not in ("and", "of", "to", "the", "using")]
    return "".join(x[0] for x in w).lower() if len(w) >= 2 else ""


def _index():
    if "idx" not in _cache:
        import features as F
        ab, vocab = {}, set(QUERY_WORDS)
        for e in F.subjects().values():
            for w in re.findall(r"[a-z]+", e["subject"].lower()):
                if len(w) > 3:
                    vocab.add(w)
            k = initials(e["subject"])
            if len(k) >= 2:
                ab.setdefault(k, []).append(e)
        _cache["idx"] = (ab, vocab, sorted(vocab))
    return _cache["idx"]


def reset():
    _cache.clear()


def detect_sem(t):
    m = re.search(r"\b([1-6])\s*(?:st|nd|rd|th)?\s*sem|\bsem\w*\s*([1-6])\b", t)
    return int(m.group(1) or m.group(2)) if m else None


def _norm(q):
    t = q.lower()
    t = re.sub(r"(\d)(sem)", r"\1 \2", t)                           # 1sem -> 1 sem
    t = re.sub(r"\bsem(\d)", r"sem \1", t)                          # sem1 -> sem 1
    return re.sub(r"\bsem\s+(vi|iv|v|iii|ii|i)\b", lambda m: "sem " + str(ROMAN[m.group(1)]), t)   # sem III -> sem 3


def ambiguous(q):
    """If a short form like 'ds' fits two different subjects (even after using the semester), return them, else None."""
    try:
        ab, vocab, _ = _index()
        t = _norm(q)
        sem = detect_sem(t)
        toks = re.findall(r"[a-z0-9+]+", t)
        if len(toks) > 10:
            return None
        for w in toks:
            w = SMS.get(w, w)
            if w in ab and w not in vocab and w not in SMALL:
                c = ab[w]
                c = [e for e in c if e["sem"] == sem] or c if sem else c
                names = {}
                for e in c:
                    names.setdefault(e["subject"].lower(), e)
                if len(names) > 1:
                    return [(e["subject"], e["sem"]) for e in names.values()]
        return None
    except Exception as ex:
        print("[QFIX-AMB]", str(ex)[:100])
        return None


def rerank(q, docs, limit):
    """The database search returns keyword matches; put the papers whose TITLE shares the most words with
    the question first (keeps 'c++' as a word, so C++ papers beat plain C or Java papers)."""
    qt = [w for w in re.findall(r"[a-z0-9+]+", _norm(q)) if len(w) > 1 and w not in SMALL]
    def key(i_d):
        i, d = i_d
        tt = set(re.findall(r"[a-z0-9+]+", (d.get("title") or "").lower()))
        return (-sum(1 for w in qt if w in tt), i)
    return [d for _, d in sorted(enumerate(docs), key=key)][:limit]


def expand(q):
    try:
        ab, vocab, vlist = _index()
        t = _norm(q)
        sem = detect_sem(t)
        toks = re.findall(r"[a-z0-9+]+", t)
        out = []
        for w in toks:
            w = SMS.get(w, w)
            if not w:
                continue
            if w in ab and w not in vocab and w not in SMALL and len(toks) <= 10:
                c = ab[w]
                c = [e for e in c if e["sem"] == sem] or c if sem else c
                out.append(max(c, key=lambda e: len(e["papers"]))["subject"].lower())
            elif len(w) >= 5 and w.isalpha() and w not in vocab:
                m = get_close_matches(w, vlist, n=1, cutoff=0.8)
                out.append(m[0] if m else w)
            else:
                out.append(w)
        return " ".join(out) or q
    except Exception as ex:
        print("[QFIX]", str(ex)[:100])
        return q

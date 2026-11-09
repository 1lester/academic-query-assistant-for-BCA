# Flask server: website -> database search (search.php) -> Groq AI -> answer
# Setup:  py -m pip install flask requests groq mysql-connector-python
#         py -m pip install ddgs                (free web search, no key needed)
#         set GROQ_API_KEY=your-key-here        (same cmd window, no quotes)
# Run:    py app.py      then open http://localhost:5000
import re
import time
import requests
from flask import Flask, request, jsonify, send_from_directory
from groq import Groq
from qengine import parse_title as qe_parse, subject_key, canon_subject, merge_keys, format_paper
from difflib import get_close_matches
import features

try:                                   # free web search (no API key)
    from ddgs import DDGS
except Exception:
    try:
        from duckduckgo_search import DDGS
    except Exception:
        DDGS = None

SEARCH_URL = "http://localhost/backend/search.php"
BROWSE_URL = "http://localhost/backend/browse.php"
# Tried in order. If one fails or is rate-limited, the next is used.
# Check current names with:  py list_models.py
MODELS = ["openai/gpt-oss-20b", "openai/gpt-oss-120b"]

app = Flask(__name__)
client = Groq(timeout=30.0, max_retries=1)     # reads GROQ_API_KEY automatically

SYSTEM = """You are an academic assistant for BCA students of Seshadripuram First Grade College (Bengaluru City University).
You get material in up to two parts:
 [PAPERS] = text of previous university question papers from the college database (OCR, may be messy)
 [WEB]    = short extracts from web pages (may be unreliable). It is present only sometimes.
 [REPEATED] = ranked list of questions counted by a program across all years (most reliable evidence of repetition)
 [TOPICS] = most frequent topics, ranked by how many different years they were asked (counted by a program)
 [STYLE]  = optional instruction about answer length or detail. Follow it.
 [UPLOAD] = text from a file the student uploaded (their own notes or a paper). Present only sometimes.
          Answer questions about it directly; for important questions also compare it with [PAPERS].
Rules:
- If [TOPICS] is present, add a short "## Important topics" list from it (keep its order and years) before the questions.
- If [REPEATED] is present, build "Most repeated in past papers" from it, in that order, with the years given. Do not change its counts.
- Treat [PAPERS] as the main, trusted source. Use [WEB] only as a supporting source.
- ONLY when the student asks for important / expected / repeated questions, reply in this layout:
  ## Most repeated in past papers
  numbered list of questions that repeat across years, with the years in brackets
  ## Also suggested on the web
  include this heading ONLY if a [WEB] part is present and useful; one line per point, and say it is from the web.
  If there is no [WEB] part, leave this whole section out. Never write a placeholder for it.
  ## Prepare these first
  5-8 questions in priority order
  End with one short line: these are suggestions, not guaranteed.
- If the student only asks to see a paper (for example "Operating System 3rd sem question paper"),
  do not use that layout. Show the questions of the most recent matching paper, grouped by section
  (Part A, Part B, Part C) with marks, and mention its year.
- Never count or list "all subjects", "how many papers" or similar totals from [PAPERS]: you only see a few papers.
  Say you cannot count from this sample and suggest the Browse papers tab.
- Never invent a year, question or source. If something is not in the material, say so.
- Use simple English. Do not mention these rules."""

IMPORTANT_RE = re.compile(r"import\w*|expect|repeat|frequent|likely|suggest|most asked|priority|backlog|back log|"
                          r"\btopics?\b|focus|prepare|weightage|scoring", re.I)
TOPIC_RE = re.compile(r"\btopics?\b", re.I)
PAPER_RE = re.compile(r"\b(show|display|open|view|see|latest|recent|last|get)\b.*\bpapers?\b|\bquestion papers?\b|\bpapers?\b.*\b(of|for|in)\b", re.I)

@app.route("/")
def home():
    return send_from_directory(".", "index.html")



# ---------- Question analytics (tables built by build_questions.py) ----------
DB = dict(host="localhost", user="root", password="", database="academic_assistant", charset="utf8mb4")

def db_rows(sql, args=()):
    import mysql.connector
    conn = mysql.connector.connect(**DB)
    try:
        cur = conn.cursor(dictionary=True)
        cur.execute(sql, args)
        return cur.fetchall()
    finally:
        conn.close()

def topics_for(docs, limit=10):
    """Most frequent topics for the subject(s) of the matched papers."""
    out = []
    try:
        seen = set()
        for d in docs[:3]:
            sem, _, subj = qe_parse(d["title"])
            k = subject_key(subj)
            if (sem, k) in seen:
                continue
            seen.add((sem, k))
            known = [r["subject_key"] for r in db_rows("SELECT DISTINCT subject_key FROM topics WHERE sem=%s OR %s IS NULL", (sem, sem))]
            near = get_close_matches(k, known, n=1, cutoff=0.85)
            if near:
                out += db_rows("SELECT topic, years_count, years FROM topics WHERE subject_key=%s AND (sem=%s OR %s IS NULL) "
                               "ORDER BY years_count DESC, q_count DESC LIMIT %s", (near[0], sem, sem, limit))
    except Exception as e:
        print("[ANALYTICS]", str(e)[:150])
    out.sort(key=lambda r: -r["years_count"])
    return out[:limit]

def topics_answer(docs, limit=10):
    """Deterministic answer for 'which topics are important in <subject>' (no AI needed)."""
    sections, seen = [], set()
    try:
        for d in docs[:5]:
            sem, _, subj = qe_parse(d["title"])
            k = subject_key(subj)
            if (sem, k) in seen:
                continue
            seen.add((sem, k))
            known = [r["subject_key"] for r in db_rows("SELECT DISTINCT subject_key FROM topics WHERE sem=%s OR %s IS NULL", (sem, sem))]
            near = get_close_matches(k, known, n=1, cutoff=0.85)
            if not near:
                continue
            rows = db_rows("SELECT topic, years_count, q_count, years, subject FROM topics WHERE subject_key=%s AND (sem=%s OR %s IS NULL) "
                           "ORDER BY years_count DESC, q_count DESC LIMIT %s", (near[0], sem, sem, limit))
            if rows:
                head = f"### {rows[0]['subject']}" + (f" ({ORD[sem]} sem)" if sem else "")
                lines = [head, "", "| No. | Topic | Years asked | In questions | Years |", "| --- | --- | --- | --- | --- |"]
                for i, r in enumerate(rows, 1):
                    lines.append(f"| {i} | {r['topic']} | {r['years_count']} | {r['q_count']} | {r['years']} |")
                sections.append("\n".join(lines))
            if len(sections) == 2:
                break
    except Exception as e:
        print("[TOPICS]", str(e)[:150])
        return None
    if not sections:
        return None
    return ("## Important topics (counted from past papers)\n\n" + "\n\n".join(sections) +
            "\n\nTopics are ranked by how many different years they were asked. Open the Analytics tab and click a topic to see example questions. "
            "These are suggestions, not guaranteed.")

def repeated_for(docs, limit=10):
    """Top repeated questions for the subject(s) of the matched papers."""
    keys = set()
    for d in docs[:3]:
        sem, _, subj = qe_parse(d["title"])
        keys.add((sem, subject_key(subj)))
    out = []
    try:
        for sem, k in keys:
            known = [r["subject_key"] for r in db_rows("SELECT DISTINCT subject_key FROM question_groups WHERE sem=%s OR %s IS NULL", (sem, sem))]
            near = get_close_matches(k, known, n=1, cutoff=0.85)
            if not near:
                continue
            k = near[0]
            rows = db_rows("SELECT text, freq, years FROM question_groups "
                           "WHERE subject_key=%s AND (sem=%s OR %s IS NULL) AND freq>=2 "
                           "ORDER BY freq DESC, last_year DESC LIMIT %s", (k, sem, sem, limit))
            out += rows
    except Exception as e:
        print("[ANALYTICS]", str(e)[:150])
        return []
    out.sort(key=lambda r: -r["freq"])
    return out[:limit]

@app.route("/api/stats")
def api_stats():
    try:
        tot = db_rows("SELECT (SELECT COUNT(*) FROM documents WHERE category='question_paper') papers,"
                      " (SELECT COUNT(*) FROM questions) questions,"
                      " (SELECT COUNT(*) FROM question_groups) unique_q,"
                      " (SELECT COUNT(*) FROM question_groups WHERE freq>=2) repeated,"
                      " (SELECT COUNT(*) FROM topics) topics")[0]
        per_sem = db_rows("SELECT sem, COUNT(*) n FROM topics GROUP BY sem ORDER BY sem")
        raw = db_rows("SELECT sem, subject_key, subject, MAX(freq) top, COUNT(*) n FROM question_groups "
                      "GROUP BY sem, subject_key, subject")
        merged = {}                      # one row per subject: the same subject can be spelled 3 ways in the PDFs' titles
        for r in raw:
            m = merged.setdefault((r["sem"], r["subject_key"]), {"sem": r["sem"], "names": {}, "top": 0, "n": 0})
            m["names"][r["subject"]] = m["names"].get(r["subject"], 0) + r["n"]
            m["top"], m["n"] = max(m["top"], r["top"]), m["n"] + r["n"]
        subjects = sorted(({"sem": m["sem"], "subject": max(m["names"], key=lambda x: (m["names"][x], " " in x, -len(x))),
                            "top": m["top"], "n": m["n"]} for m in merged.values()),
                          key=lambda r: (r["sem"] or 0, r["subject"]))
    except Exception:
        return jsonify(error="Analytics not ready. Run build_questions.py (and keep XAMPP running)."), 502
    return jsonify(totals=tot, per_sem=per_sem, subjects=subjects)

def _filters():
    sem = request.args.get("sem", type=int)
    subj = subject_key(request.args.get("subject", ""))
    where, args = [], []
    if sem:
        where.append("sem=%s"); args.append(sem)
    if subj:
        where.append("subject_key LIKE %s"); args.append("%" + subj + "%")
    return where, args

@app.route("/api/top")
def api_top():
    limit = max(1, min(request.args.get("limit", 15, type=int), 50))
    where, args = _filters()
    sql = ("SELECT text, freq, years, last_year, subject, sem FROM question_groups WHERE freq>=2"
           + "".join(" AND " + w for w in where) + " ORDER BY freq DESC, last_year DESC LIMIT %s")
    try:
        rows = db_rows(sql, tuple(args) + (limit,))
    except Exception as e:
        print("[ANALYTICS]", str(e)[:200])
        return jsonify(error="Analytics not ready. Run build_questions.py (and keep XAMPP running)."), 502
    return jsonify(results=rows)

@app.route("/api/topics")
def api_topics():
    limit = max(1, min(request.args.get("limit", 20, type=int), 60))
    where, args = _filters()
    sql = ("SELECT topic, years_count, q_count, years, examples, subject, sem FROM topics"
           + (" WHERE " + " AND ".join(where) if where else "")
           + " ORDER BY years_count DESC, q_count DESC LIMIT %s")
    try:
        rows = db_rows(sql, tuple(args) + (limit,))
    except Exception as e:
        print("[ANALYTICS]", str(e)[:200])
        return jsonify(error="Analytics not ready. Run build_questions.py (and keep XAMPP running)."), 502
    for r in rows:
        r["examples"] = [x for x in r["examples"].split("||") if x]
    return jsonify(results=rows)

# ---------- Browse papers: BCA -> semester -> year -> subject ----------
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

@app.route("/api/papers")
def papers():
    try:
        rows = requests.post(BROWSE_URL, timeout=10).json().get("papers", [])
    except Exception:
        return jsonify(error="Cannot reach the database. Is XAMPP running?"), 502
    tree = {}
    for p in rows:
        sem, year, subject = parse_title(p["title"])
        tree.setdefault(sem or 0, {}).setdefault(year, []).append({"id": p["id"], "subject": subject})
    out = []
    for sem in sorted(tree):
        years = [{"year": y, "papers": sorted(tree[sem][y], key=lambda x: x["subject"].lower())}
                 for y in sorted(tree[sem], reverse=True)]
        out.append({"label": f"{ORD[sem]} Semester" if sem else "Other",
                    "count": sum(len(y["papers"]) for y in years), "years": years})
    return jsonify(semesters=out)

@app.route("/api/paper/<int:pid>")
def paper(pid):
    try:
        d = requests.post(BROWSE_URL, data={"id": pid}, timeout=10).json()
    except Exception:
        return jsonify(error="Cannot reach the database. Is XAMPP running?"), 502
    p = d.get("paper")
    if not p:
        return jsonify({"error": "Not found"})
    sem, year, subj = qe_parse(p.get("title", ""))
    nice = canon_subject(subj).title() or p.get("title", "Question paper")
    if year != "Other":
        nice += f" ({year})"
    p["formatted"] = format_paper(nice, p.get("content", ""))
    return jsonify(p)


def web_search(q, n=4):
    """Free web search. Returns [{title,url,text}] or [] if anything fails."""
    if DDGS is None:
        return []
    out = []
    try:
        query = q + " BCA Bengaluru City University question paper important questions"
        for r in DDGS().text(query, max_results=n):
            url = r.get("href") or r.get("url") or ""
            out.append({"title": (r.get("title") or "")[:120], "url": url,
                        "text": (r.get("body") or "")[:600]})
    except Exception as e:
        print("[WEB] search failed:", str(e)[:150])
        return []
    # read the top 2 pages a little deeper
    for item in out[:2]:
        try:
            html = requests.get(item["url"], timeout=6, headers={"User-Agent": "Mozilla/5.0"}).text
            html = re.sub(r"(?is)<(script|style|nav|footer|header)[^>]*>.*?</\1>", " ", html)
            text = re.sub(r"\s+", " ", re.sub(r"(?s)<[^>]+>", " ", html)).strip()
            if len(text) > 200:
                item["text"] = text[:1800]
        except Exception:
            pass
    return out


STOP = {"the","and","for","with","from","what","when","where","which","who","how","are","is","of","in","on","at",
        "to","me","my","please","tell","give","show","about","paper","papers","question","questions","sem","semester",
        "important","expected","exam","imp","topic","topics","have","has","backlog","backlo","importand","importance",
        "can","you","need","want","most","repeated","frequently","asked","suggest","list","all"}

def clean_query(q):
    """Fix common typos, expand short names (ca), drop 1-2 letter words that match everything."""
    q = re.sub(r"\bca\b", "computer applications", q, flags=re.I)
    try:
        import qfix
        q = qfix.expand(q)           # SMS short forms, subject initials (+semester), typos
    except Exception as e:
        print("[QFIX]", str(e)[:100])
    t = re.sub(r"\b(\d)\s*(?:sts|nds|rds|ths|st|nd|rd|th)\b", lambda m: m.group(1) + {"1":"st","2":"nd","3":"rd"}.get(m.group(1), "th"), q.lower())
    words = [w for w in re.findall(r"[a-z0-9]+", t) if len(w) > 2 or w.isdigit()]
    return " ".join(words) or q

def best_chunks(content, q, maxlen=2500):
    """For long or combined PDFs: keep the header plus the blocks that match the question best."""
    if len(content) <= maxlen:
        return content
    keys = [w for w in re.findall(r"[a-z0-9]+", q.lower()) if len(w) > 2 and w not in STOP]
    blocks, cur = [], ""
    for line in content.splitlines():
        if len(cur) + len(line) > 700:
            blocks.append(cur); cur = ""
        cur += line + "\n"
    if cur.strip():
        blocks.append(cur)
    if not keys:
        return content[:maxlen]
    scored = sorted(range(len(blocks)), key=lambda i: -sum(blocks[i].lower().count(k) for k in keys))
    chosen, size = {0}, len(blocks[0])
    for i in scored:
        if i in chosen or sum(blocks[i].lower().count(k) for k in keys) == 0:
            continue
        if size + len(blocks[i]) > maxlen:
            continue
        chosen.add(i); size += len(blocks[i])
    return "\n...\n".join(blocks[i] for i in sorted(chosen))[:maxlen + 200]

def read_upload(f):
    """Text from an uploaded .pdf or .txt. Returns (text, note)."""
    if not f or not f.filename:
        return "", ""
    name = f.filename.lower()
    data = f.read()
    if len(data) > 8 * 1024 * 1024:
        return "", "The file is larger than 8 MB, so I skipped it."
    try:
        if name.endswith(".txt"):
            return data.decode("utf-8", errors="ignore")[:4000], ""
        if name.endswith(".pdf"):
            import io, pdfplumber
            with pdfplumber.open(io.BytesIO(data)) as pdf:
                text = "\n".join((p.extract_text() or "") for p in pdf.pages[:6]).strip()
            if len(text) < 30:
                return "", "That PDF looks scanned (no selectable text), so I could not read it."
            return text[:4000], ""
    except Exception as e:
        print("[UPLOAD] error:", str(e)[:150])
        return "", "I could not read that file."
    return "", "Only PDF and TXT files are supported."


# ---------- "What / how many subjects in 5th sem?" -> database + official BCU scheme, no AI needed ----------
JUNK = ("timetable", "time table", "class", "repeater", "syllabus", "circular", "notice", "scheme",
        "kannada", "hindi", "sanskrit", "tamil", "telugu", "urdu", "malayalam", "marathi", "french", "arabic")
CATALOG_RE = re.compile(r"\b(subjects?|courses?)\b", re.I)
WORD_SEM = {"first": 1, "second": 2, "third": 3, "fourth": 4, "fifth": 5, "sixth": 6}

def parse_sem(q):
    m = (re.search(r"\b([1-6])\s*(?:st|nd|rd|th)\b", q, re.I) or re.search(r"\bsem(?:ester)?\s*([1-6])\b", q, re.I)
         or re.search(r"\b([1-6])\s*sem", q, re.I))
    if m:
        return int(m.group(1))
    w = re.search(r"\b(first|second|third|fourth|fifth|sixth)\b", q, re.I)
    return WORD_SEM[w.group(1).lower()] if w else None

def load_scheme():
    import json, os
    try:
        with open(os.path.join(os.path.dirname(os.path.abspath(__file__)), "bcu_scheme.json"), encoding="utf-8") as f:
            return json.load(f)
    except Exception as e:
        print("[SCHEME]", str(e)[:120])
        return None

def subjects_catalog(sem):
    rows = requests.post(BROWSE_URL, timeout=10).json().get("papers", [])
    info = {}
    for p in rows:
        s, year, subject = qe_parse(p["title"])
        if s != sem or any(j in p["title"].lower() for j in JUNK):
            continue
        name = canon_subject(subject)
        k = subject_key(subject)
        if len(k) < 4:
            continue
        e = info.setdefault(k, {"names": {}, "papers": 0, "years": set()})
        e["names"][name.title()] = e["names"].get(name.title(), 0) + 1
        e["papers"] += 1
        if year != "Other":
            e["years"].add(year)
    kmap = merge_keys({k: v["papers"] for k, v in info.items()})
    merged = {}
    for k, v in info.items():
        m = merged.setdefault(kmap[k], {"names": {}, "papers": 0, "years": set()})
        for n, c in v["names"].items():
            m["names"][n] = m["names"].get(n, 0) + c
        m["papers"] += v["papers"]; m["years"] |= v["years"]
    out = [{"key": k, "subject": max(v["names"], key=v["names"].get), "papers": v["papers"], "years": sorted(v["years"])}
           for k, v in merged.items()]
    return sorted(out, key=lambda r: r["subject"])

def _yrs(ys):
    return (ys[0] + " to " + ys[-1]) if len(ys) > 1 else (ys[0] if ys else "-")

def _same(a, b):
    from difflib import SequenceMatcher
    if not a or not b:
        return False
    if len(a) >= 8 and len(b) >= 8 and (a in b or b in a):
        return True
    return SequenceMatcher(None, a, b).ratio() >= 0.82

def catalog_answer(q):
    if not CATALOG_RE.search(q) or re.search(r"important|expected|repeat|topic|question", q, re.I):
        return None
    sem = parse_sem(q)
    if not sem:
        return None
    db = [d for d in subjects_catalog(sem) if not re.search(r"b\s*com|bba", d["subject"], re.I)]
    yrs = sorted({y for d in db for y in d["years"] if y.isdigit()})
    if not yrs:
        return f"I could not find any subjects for semester {sem} in the database."
    latest = yrs[-1]
    cur = [d for d in db if latest in d["years"]]
    old = [d for d in db if latest not in d["years"]]
    lines = [f"## {ORD[sem].capitalize()} Semester subjects (latest: {latest})", "",
             f"These **{len(cur)} subjects** are from the newest question papers in your database ({latest}), so they follow the current scheme.", "",
             "| No. | Subject | Papers | Years available |", "| --- | --- | --- | --- |"]
    for n, d in enumerate(cur, 1):
        lines.append(f"| {n} | {d['subject']} | {d['papers']} | {_yrs(d['years'])} |")
    if old:
        lines += ["", f"**Older scheme (not in {latest}):** " + ", ".join(d["subject"] for d in old) + "."]
    syl = load_syllabus()
    if syl and str(sem) in syl["scheme"]:
        items = syl["scheme"][str(sem)]
        th = [f"{x[1]} ({x[0]})" for x in items if x[2] == "T"]
        other = [x[1] for x in items if x[2] != "T"]
        lines += ["", "**Official current scheme (Bengaluru City University):** " + ", ".join(th) + ".",
                  "", "Also in the scheme (no theory units): " + ", ".join(other) + "."]
    lines += ["", "Ask \"syllabus of <subject>\" for the official units, or \"important topics in <subject> " + ORD[sem] + " sem\" to prepare."]
    return "\n".join(lines)

SYL_RE = re.compile(r"\b(syllabus|syllabi|units?|curriculum|official|what (?:is|are) (?:taught|covered))\b", re.I)
ALIASES = {"dbms": "database management", "os": "operating system", "ada": "algorithm", "daa": "algorithm", "ai": "artificial intelligence",
           "c++": "c++", "vb.net": "vb.net", "vb net": "vb.net", "unix": "unix", "se": "software engineering",
           "networks": "networks", "networking": "networks", "java": "java", "web": "web programming",
           "computer organization": "computer architecture", "discrete": "discrete", "numerical": "numerical",
           "ds": "data structure", "python": "python", "ml": "machine learning", "c programming": "problem solving", "c": "problem solving"}

def load_syllabus():
    import json, os
    base = os.path.dirname(os.path.abspath(__file__))
    out = {"papers": [], "scheme": {}, "sources": {}, "note": ""}
    for fn, legacy in (("bcu_syllabus_nep.json", False), ("bcu_syllabus.json", True)):
        try:
            with open(os.path.join(base, fn), encoding="utf-8") as f:
                d = json.load(f)
        except Exception as e:
            print("[SYLLABUS]", fn, str(e)[:100]); continue
        for p in d["papers"]:
            p["legacy"] = legacy
            out["papers"].append(p)
        if not legacy:
            out["scheme"], out["sources"], out["note"] = d["scheme"], d["sources"], d["note"]
        else:
            out["legacy_source"] = d["source"]
    return out if out["papers"] else None

def syl_source(p, syl):
    if p.get("legacy"):
        return syl.get("legacy_source", "")
    return syl["sources"]["1-2" if p["sem"] <= 2 else "3-4" if p["sem"] <= 4 else "5-6"]

def find_paper(q, syl, sem=None):
    ql = " " + re.sub(r"[^a-z0-9+. ]", " ", q.lower()) + " "
    pool = [p for p in syl["papers"] if not sem or p["sem"] == sem]
    m = re.search(r"bca\s*(\d{3})\s*t?", q, re.I)
    if m:
        for p in pool:
            if p["code"].lower().startswith("bca" + m.group(1)):
                return p
    best, bs = None, 0
    for p in pool:
        words = [w for w in re.findall(r"[a-z0-9+.]+", p["name"].lower()) if w not in ("and", "of", "using", "to", "the")]
        if not words:
            continue
        sc = sum(1 for w in words if " " + w + " " in ql) / len(words)
        if sc > bs:
            best, bs = p, sc
    if best and bs >= 0.6:
        return best
    for a, frag in ALIASES.items():
        if " " + a + " " in ql:
            for p in pool:
                if frag in p["name"].lower():
                    return p
    return None

def paper_syllabus_md(p, syl):
    tag = "older 2019-20 scheme" if p.get("legacy") else p.get("scheme", "")
    lines = [f"## {p['name']} ({p['code']}) - official syllabus", "",
             f"{ORD[p['sem']].capitalize()} semester | {str(p['hours']) + ' teaching hours' if isinstance(p['hours'], int) else p['hours']} | {p['credits']} credits | {p['marks']} | Scheme: {tag}", ""]
    if not p["units"]:
        lines += ["The university PDF does not list units for this paper."]
    for u in p["units"]:
        h = f" ({u['hours']} hrs)" if u.get("hours") else ""
        lines += [f"### Unit {u['no']}: {u['title']}{h}"] + [f"- {t}" for t in u["topics"]] + [""]
    if p.get("labels_only"):
        lines += ["> The university text for this paper is inconsistent, so the unit titles above are my grouping of its topics. Verify against the PDF.", ""]
    lines += [f"Source: [Bengaluru City University syllabus PDF]({syl_source(p, syl)}). Summarised, so check the PDF for exact wording.",
              "", f"Ask \"important topics in {p['name']}\" to see which of these were asked most often in previous papers."]
    return "\n".join(lines)

def syllabus_answer(q):
    if not SYL_RE.search(q) or re.search(r"important|expected|repeat|question", q, re.I):
        return None
    syl = load_syllabus()
    if not syl:
        return None
    sem = parse_sem(q)
    p = find_paper(q, syl, sem)
    if p:
        return paper_syllabus_md(p, syl)
    if sem:
        ps = [x for x in syl["papers"] if x["sem"] == sem]
        if any(not x["legacy"] for x in ps):
            ps = [x for x in ps if not x["legacy"]]
        lines = [f"## {ORD[sem].capitalize()} semester - official syllabus overview", ""]
        for x in ps:
            lines += [f"### {x['name']} ({x['code']})", ""] + [f"{u['no']}. {u['title']}" for u in x["units"]] + [""]
        lines += [f"Source: [Bengaluru City University syllabus PDF]({syl_source(ps[0], syl)}). " + (syl["note"] if not ps[0]["legacy"] else ""), "", "Ask \"syllabus of <subject>\" for the full topics of any paper."]
        return "\n".join(lines)
    return None

@app.route("/ask", methods=["POST"])
def ask():
    if request.is_json:
        body = request.get_json(silent=True) or {}
        q = (body.get("question") or "").strip()
        use_web = bool(body.get("web", False))
        style = str(body.get("style", ""))
        upload_text, upload_note = "", ""
    else:
        q = (request.form.get("question") or "").strip()
        use_web = request.form.get("web", "0") == "1"
        style = request.form.get("style", "")
        upload_text, upload_note = read_upload(request.files.get("file"))
    if not q:
        q = "Give the important questions from this file" if upload_text else ""
    if not q:
        return jsonify(error="Please type a question"), 400

    if not upload_text:
        try:                                # "ds" could be two subjects: ask instead of guessing
            import qfix
            amb = qfix.ambiguous(q)
        except Exception:
            amb = None
        if amb:
            lines = "\n".join(f"- {n}" + (f" ({ORD[s]} sem)" if s else "") for n, s in amb[:5])
            return jsonify(answer="**Which subject do you mean?**\n\nThat short form fits more than one subject:\n\n" + lines +
                           "\n\nAsk again with the full name, for example: *important questions in " + amb[0][0] + "*.", sources=[])
        try:
            direct = syllabus_answer(q) or catalog_answer(q)
        except Exception as e:
            print("[CATALOG]", str(e)[:150]); direct = None
        if direct:
            return jsonify(answer=direct, sources=[])

    wants_important = bool(IMPORTANT_RE.search(q))
    limit = 5 if wants_important else 3        # free tier has a per-minute token limit

    try:
        r = requests.post(SEARCH_URL, data={"query": clean_query(q), "limit": 10}, timeout=10)
        docs = r.json().get("results", [])
        try:
            import qfix
            docs = qfix.rerank(q, docs, limit)      # papers whose title best matches the question first
        except Exception as e:
            print("[RERANK]", str(e)[:100]); docs = docs[:limit]
    except Exception:
        return jsonify(error="Cannot reach the database search. Is XAMPP running?"), 502
    try:                                    # semantic search rescues searches with no/few keyword hits
        docs = features.hybrid_merge(clean_query(q), docs, limit)
    except Exception as e:
        print("[HYBRID]", str(e)[:150])

    if not docs and not upload_text:
        return jsonify(answer=(upload_note + " " if upload_note else "") +
                       "I could not find any matching documents for that question.", sources=[])

    # keep only papers that match the most keywords (drops loosely related ones)
    if docs:
        top = max(d.get("score", 0) for d in docs)
        best = [d for d in docs if d.get("score", 0) >= top]
        docs = best if len(best) >= 3 else docs[:3]

    if docs and PAPER_RE.search(q) and not IMPORTANT_RE.search(q) and not upload_text:
        def _yr(d):
            y = qe_parse(d["title"])[1]
            return y if y.isdigit() else "0"
        newest = max(docs, key=_yr)
        sem_, year_, subj_ = qe_parse(newest["title"])
        nice = canon_subject(subj_).title() or newest["title"]
        if year_ != "Other":
            nice += f" ({year_})"
        shown = format_paper(nice, newest["content"])
        if shown:
            note = ("\n\n---\nShowing the most recent matching paper. Ask for **important topics** in this subject "
                    "to see what repeats across years.")
            return jsonify(answer=shown + note, sources=[newest["title"]])

    if docs and TOPIC_RE.search(q) and not upload_text:
        direct = topics_answer(docs)
        if direct:
            return jsonify(answer=direct, sources=[d["title"] for d in docs])

    context = "\n\n".join(f"### {d['title']}\n{best_chunks(d['content'], q)}" for d in docs)
    prompt = f"[PAPERS]\n{context}\n"
    if upload_text:
        prompt += f"\n[UPLOAD]\n{upload_text}\n"

    if wants_important and docs:
        tps = topics_for(docs)
        if tps:
            prompt += "\n[TOPICS]\n" + "\n".join(
                f"{i}. {t['topic']} (asked in {t['years_count']} different years: {t['years']})" for i, t in enumerate(tps, 1)) + "\n"
        rep = repeated_for(docs)
        if rep:
            prompt += "\n[REPEATED]\n" + "\n".join(
                f"{i}. {r['text']} (asked {r['freq']} times: {r['years']})" for i, r in enumerate(rep, 1)) + "\n"

    web = []
    if wants_important and use_web:
        web = web_search(q)
        if web:
            prompt += "\n[WEB]\n" + "\n\n".join(f"### {w['title']} ({w['url']})\n{w['text'][:1500]}" for w in web)
    hint = {"short": "Keep the answer short: no more than about 8 lines.",
            "detailed": "Explain in more detail, with one short example for each point."}.get(style)
    if hint:
        prompt += f"\n\n[STYLE] {hint}"
    prompt += f"\n\nStudent question: {q}"

    answer = None
    t0 = time.time()
    for model in MODELS:
        try:
            resp = client.chat.completions.create(
                model=model,
                messages=[{"role": "system", "content": SYSTEM},
                          {"role": "user", "content": prompt}],
                reasoning_effort="low",      # these models "think"; low = faster
                max_tokens=3000)
            answer = resp.choices[0].message.content
            print(f"[AI] {model} answered in {time.time()-t0:.1f}s")
            break
        except Exception as e:
            print(f"[AI] {model} error:", str(e)[:200])

    if not answer:
        # AI unavailable: still help by showing the matching paper text from the database
        shown = docs[:2]
        text = "The AI is slow or busy right now, so here are the matching papers from the database:\n\n"
        text += "\n\n".join((format_paper(d["title"], d["content"]) or f"**{d['title']}**\n{d['content'][:2000]}") for d in shown)
        return jsonify(answer=text, sources=[d["title"] for d in shown])

    if upload_note:
        answer = upload_note + "\n\n" + answer
    return jsonify(answer=answer, sources=[d["title"] for d in docs],
                   web=[{"title": w["title"], "url": w["url"]} for w in web])

# extra features: prediction, trend grid, semantic search, mock paper, quiz, answer checker, planner, admin
features.register(app, db_rows=db_rows, client=client, models=MODELS, load_syllabus=load_syllabus,
                  find_paper=find_paper, paper_syllabus_md=paper_syllabus_md, DB=DB)
# add-on tools: flashcards, viva, misconceptions, code, coverage, evolution, anomalies, trace, concept map, visual, debate
import addons
addons.register(app)

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, debug=False)   # 0.0.0.0 = reachable from other devices; debug stays off when sharing

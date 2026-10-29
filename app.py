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
from qengine import parse_title as qe_parse, subject_key, canon_subject, merge_keys
from difflib import get_close_matches

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

IMPORTANT_WORDS = ["important", "expected", "repeat", "frequent", "likely", "suggest", "most asked"]

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
        subjects = db_rows("SELECT sem, subject, MAX(freq) top, COUNT(*) n FROM question_groups "
                           "GROUP BY sem, subject_key, subject ORDER BY sem, subject")
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
    return jsonify(d.get("paper") or {"error": "Not found"})


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
        "important","expected","exam","imp"}

def clean_query(q):
    """Fix common typos, expand short names (ca), drop 1-2 letter words that match everything."""
    q = re.sub(r"\bca\b", "computer applications", q, flags=re.I)
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


# ---------- "How many subjects in 5th sem?" -> answered from the database, not by the AI ----------
JUNK = ("timetable", "time table", "class", "repeater", "syllabus", "circular", "notice", "scheme")
CATALOG_RE = re.compile(r"\b(how many|list|which|what|name|show|all)\b.*\bsubjects?\b|\bsubjects?\b.*\b(in|of|for)\b", re.I)

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
    out = [{"subject": max(v["names"], key=v["names"].get), "papers": v["papers"], "years": sorted(v["years"])}
           for v in merged.values()]
    return sorted(out, key=lambda r: r["subject"])

def catalog_answer(q):
    m = re.search(r"\b([1-6])\s*(?:st|nd|rd|th)?\s*sem", q, re.I) or re.search(r"sem(?:ester)?\s*([1-6])\b", q, re.I)
    if not m or not CATALOG_RE.search(q) or re.search(r"important|expected|repeat|question", q, re.I):
        return None
    sem = int(m.group(1))
    subs = subjects_catalog(sem)
    if not subs:
        return f"I could not find any subjects for semester {sem} in the database."
    lines = [f"## {ORD[sem]} Semester: {len(subs)} subjects found in the papers database", "",
             "| No. | Subject | Papers | Years available |", "| --- | --- | --- | --- |"]
    for i, s in enumerate(subs, 1):
        yrs = (s["years"][0] + " to " + s["years"][-1]) if len(s["years"]) > 1 else (s["years"][0] if s["years"] else "-")
        lines.append(f"| {i} | {s['subject']} | {s['papers']} | {yrs} |")
    lines += ["", "This list comes from the question papers uploaded to the database, so a subject with no uploaded paper will not appear. "
              "Ask for \"important questions in <subject> " + ORD[sem] + " sem\" to prepare any of them."]
    return "\n".join(lines)

@app.route("/ask", methods=["POST"])
def ask():
    if request.is_json:
        body = request.get_json(silent=True) or {}
        q = (body.get("question") or "").strip()
        use_web = bool(body.get("web", False))
        upload_text, upload_note = "", ""
    else:
        q = (request.form.get("question") or "").strip()
        use_web = request.form.get("web", "0") == "1"
        upload_text, upload_note = read_upload(request.files.get("file"))
    if not q:
        q = "Give the important questions from this file" if upload_text else ""
    if not q:
        return jsonify(error="Please type a question"), 400

    if not upload_text:
        try:
            direct = catalog_answer(q)
        except Exception as e:
            print("[CATALOG]", str(e)[:150]); direct = None
        if direct:
            return jsonify(answer=direct, sources=[])

    wants_important = any(w in q.lower() for w in IMPORTANT_WORDS)
    limit = 5 if wants_important else 3        # free tier has a per-minute token limit

    try:
        r = requests.post(SEARCH_URL, data={"query": clean_query(q), "limit": limit}, timeout=10)
        docs = r.json().get("results", [])
    except Exception:
        return jsonify(error="Cannot reach the database search. Is XAMPP running?"), 502

    if not docs and not upload_text:
        return jsonify(answer=(upload_note + " " if upload_note else "") +
                       "I could not find any matching documents for that question.", sources=[])

    # keep only papers that match the most keywords (drops loosely related ones)
    if docs:
        top = max(d.get("score", 0) for d in docs)
        best = [d for d in docs if d.get("score", 0) >= top]
        docs = best if len(best) >= 3 else docs[:3]

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
        text += "\n\n".join(f"**{d['title']}**\n{d['content'][:2000]}" for d in shown)
        return jsonify(answer=text, sources=[d["title"] for d in shown])

    if upload_note:
        answer = upload_note + "\n\n" + answer
    return jsonify(answer=answer, sources=[d["title"] for d in docs],
                   web=[{"title": w["title"], "url": w["url"]} for w in web])

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, debug=False)   # 0.0.0.0 = reachable from other devices; debug stays off when sharing

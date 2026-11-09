# Compares keyword search, semantic search and hybrid (both merged) on the same 60 test queries
# as evaluate.py. Needs XAMPP running.   Run:  py evaluate_hybrid.py
import csv, random
import mysql.connector, requests
import features, semantic
from qengine import parse_title, subject_key, canon_subject, ORD

DB = dict(host="localhost", user="root", password="", database="academic_assistant", charset="utf8mb4")
SEARCH = "http://localhost/backend/search.php"
BROWSE = "http://localhost/backend/browse.php"

def db_rows(sql, args=()):
    conn = mysql.connector.connect(**DB)
    try:
        cur = conn.cursor(dictionary=True); cur.execute(sql, args); return cur.fetchall()
    finally:
        conn.close()
features.CTX["db_rows"] = db_rows

random.seed(7)                                   # same tests as evaluate.py
papers = requests.post(BROWSE, timeout=15).json().get("papers", [])
cands = []
for p in papers:
    sem, year, subject = parse_title(p["title"])
    junk = any(w in subject.lower() for w in ("timetable", "class", "repeater", "syllabus", "circular", "notice"))
    if sem and len(subject_key(subject)) >= 4 and not junk:
        cands.append((sem, canon_subject(subject).title()))
cands = sorted(set(c for c in cands if c[1])); random.shuffle(cands); tests = cands[:30]

def rank_of(res, sem, subject):
    for i, r in enumerate(res, 1):
        s, _, subj = parse_title(r["title"])
        if subject_key(subj) == subject_key(subject) and s == sem:
            return i
    return 0

results = {"keyword": [], "semantic": [], "hybrid": []}
for sem, subject in tests:
    for q in (f"{subject} {ORD[sem]} sem question paper", f"important questions in {subject} {ORD[sem]} sem"):
        kw = requests.post(SEARCH, data={"query": q, "limit": 10}, timeout=15).json().get("results", [])
        sd = features.semantic_docs(q, 10)
        byid = {d["id"]: d for d in sd}; byid.update({d["id"]: d for d in kw})
        hy = [byid[i] for i in semantic.rrf([[d["id"] for d in kw], [d["id"] for d in sd]])]
        for name, res in (("keyword", kw[:5]), ("semantic", sd[:5]), ("hybrid", hy[:5])):
            results[name].append(rank_of(res, sem, subject))

print(f"Queries: {len(results['keyword'])}   semantic back-end: {features._dindex()[1].backend}\n")
print(f"{'method':10s} {'top-1':>7s} {'top-3':>7s} {'top-5':>7s} {'MRR':>7s}")
out = []
for name, rs in results.items():
    n = len(rs); t1 = 100 * sum(1 for r in rs if r == 1) / n; t3 = 100 * sum(1 for r in rs if 0 < r <= 3) / n
    t5 = 100 * sum(1 for r in rs if r > 0) / n; mrr = sum(1 / r for r in rs if r) / n
    print(f"{name:10s} {t1:6.1f}% {t3:6.1f}% {t5:6.1f}% {mrr:7.3f}"); out.append([name, round(t1, 1), round(t3, 1), round(t5, 1), round(mrr, 3)])
with open("hybrid_eval.csv", "w", newline="", encoding="utf-8") as f:
    w = csv.writer(f); w.writerow(["method", "top1_%", "top3_%", "top5_%", "MRR"]); w.writerows(out)
print("\nSaved hybrid_eval.csv. If hybrid beats keyword, set HYBRID_ALWAYS=1 before running app.py.")

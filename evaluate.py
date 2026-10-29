# Measures how accurate the search is. Needs XAMPP running. Run:  py evaluate.py
# For 30 random papers it asks the search the way a student would, and checks
# whether the right subject (and semester) comes back in the top results.
# Results are printed and saved to evaluation_results.csv (use them in your report).
import csv, random, time
import requests
from qengine import parse_title, subject_key, canon_subject, ORD

SEARCH = "http://localhost/backend/search.php"
BROWSE = "http://localhost/backend/browse.php"
N = 30
random.seed(7)                       # same tests every run -> repeatable numbers

papers = requests.post(BROWSE, timeout=15).json().get("papers", [])
cands = []
for p in papers:
    sem, year, subject = parse_title(p["title"])
    junk = any(w in subject.lower() for w in ("timetable", "class", "repeater", "syllabus", "circular", "notice"))
    if sem and len(subject_key(subject)) >= 4 and not junk:
        cands.append((sem, canon_subject(subject).title()))
cands = sorted(set(c for c in cands if c[1]))
random.shuffle(cands)
tests = cands[:N]
if not tests:
    raise SystemExit("No papers found. Import the PDFs first.")

def run(query, sem, subject):
    t0 = time.time()
    res = requests.post(SEARCH, data={"query": query, "limit": 5}, timeout=15).json().get("results", [])
    ms = (time.time() - t0) * 1000
    rank = 0
    for i, r in enumerate(res, 1):
        s, _, subj = parse_title(r["title"])
        if subject_key(subj) == subject_key(subject) and (s == sem):
            rank = i
            break
    return rank, ms

rows = []
for sem, subject in tests:
    for style, q in (("with semester", f"{subject} {ORD[sem]} sem question paper"),
                     ("important Q", f"important questions in {subject} {ORD[sem]} sem")):
        rank, ms = run(q, sem, subject)
        rows.append([style, q, sem, subject, rank, round(ms)])

def pct(f):
    return 100.0 * sum(1 for r in rows if f(r)) / len(rows)

print(f"\nTests run: {len(rows)} ({len(tests)} subjects x 2 query styles)")
print(f"Correct paper at rank 1 : {pct(lambda r: r[4] == 1):.1f}%")
print(f"Correct paper in top 3  : {pct(lambda r: 0 < r[4] <= 3):.1f}%")
print(f"Correct paper in top 5  : {pct(lambda r: r[4] > 0):.1f}%")
mrr = sum(1 / r[4] for r in rows if r[4]) / len(rows)
print(f"Mean reciprocal rank    : {mrr:.3f}")
print(f"Average search time     : {sum(r[5] for r in rows) / len(rows):.0f} ms")
for style in ("with semester", "important Q"):
    sub = [r for r in rows if r[0] == style]
    print(f"  {style:14s} top-3 accuracy: {100.0 * sum(1 for r in sub if 0 < r[4] <= 3) / len(sub):.1f}%")
print("\nFailed queries:")
for r in rows:
    if r[4] == 0:
        print("  -", r[1])

with open("evaluation_results.csv", "w", newline="", encoding="utf-8") as f:
    w = csv.writer(f)
    w.writerow(["style", "query", "semester", "subject", "rank_found(0=missed)", "ms"])
    w.writerows(rows)
print("\nSaved evaluation_results.csv")

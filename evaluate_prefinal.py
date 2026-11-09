"""Score the predictor against a real paper it has never seen (a college pre-final).
Run in the project folder with XAMPP running:   py evaluate_prefinal.py
Optional:  py evaluate_prefinal.py other_paper.json

For every question of the real paper it checks three things, using only the database:
  REPEATED  - a similar question already exists in the past BCU papers (question_groups)
  PREDICTED - the question contains one of the model's top-N predicted topics
  SYLLABUS  - the question matches a topic of the official syllabus for the subject
Prints hit rates and writes prefinal_eval.csv.
"""
import csv, json, sys
import app                                   # connects the database and registers features
import features as F
from qengine import norm_tokens, similar

path = sys.argv[1] if len(sys.argv) > 1 else "prefinal_se_2026.json"
paper = json.load(open(path, encoding="utf-8"))
sem, subj, qs = paper["sem"], paper["subject"], paper["questions"]
ents = F.find_subjects(sem, subj, 1) or F.find_subjects(None, subj, 1)
if not ents:
    sys.exit("Subject not found in the database. Run build_questions.py first.")
e = ents[0]
print(f"Subject in database: {e['subject']} (sem {e['sem']}), papers: {e['papers']}")

TOPN = 10
top = [p["topic"] for p in F.ranked(e)[:TOPN]]
cond, args = ("sem=%s", [e["sem"]]) if e["sem"] is not None else ("sem IS NULL", [])
groups = F._rows(f"SELECT text, freq FROM question_groups WHERE {cond} AND subject_key=%s", tuple(args) + (e["skey"],))
gt = [(norm_tokens(g["text"]), g) for g in groups]
syl_topics = []
try:
    syl = F.CTX["load_syllabus"](); sp = F.CTX["find_paper"](subj, syl, sem)
    syl_topics = [(u.get("title", ""), t) for u in (sp or {}).get("units", []) for t in u.get("topics", [])]
except Exception as ex:
    print("Syllabus not available:", ex)
st = [(norm_tokens(t), t) for _, t in syl_topics]

rows = []
for q in qs:
    qt = norm_tokens(q["text"])
    rep = next((g["text"] for t, g in gt if similar(qt, t)), "")
    pred = next((p for p in top if norm_tokens(p) and norm_tokens(p) <= qt), "")
    syl_hit = next((t for tk, t in st if tk and len(tk & qt) >= max(1, round(0.6 * len(tk)))), "")
    rows.append({"n": q["n"], "part": q["part"], "question": q["text"], "repeated": rep, "predicted_topic": pred, "syllabus_topic": syl_hit})

n = len(rows)
pct = lambda k: round(100 * sum(1 for r in rows if r[k]) / n)
any_ = round(100 * sum(1 for r in rows if r["repeated"] or r["predicted_topic"]) / n)
anyall = round(100 * sum(1 for r in rows if r["repeated"] or r["predicted_topic"] or r["syllabus_topic"]) / n)
used = [p for p in top if any(r["predicted_topic"] == p for r in rows)]
print(f"\nQuestions in the paper: {n}")
print(f"Already asked before in BCU papers (REPEATED):  {pct('repeated')}%")
print(f"Contain a top-{TOPN} predicted topic (PREDICTED): {pct('predicted_topic')}%   (topics that hit: {len(used)} of {len(top)})")
print(f"Match the official syllabus (SYLLABUS):          {pct('syllabus_topic') if syl_topics else 'n/a'}%")
print(f"Covered by repeated OR predicted:                {any_}%")
print(f"Covered by any of the three:                     {anyall}%\n")
for r in rows:
    flags = ("R" if r["repeated"] else "-") + ("P" if r["predicted_topic"] else "-") + ("S" if r["syllabus_topic"] else "-")
    print(f"{r['n']:>2} [{flags}] {r['question'][:80]}")
with open("prefinal_eval.csv", "w", newline="", encoding="utf-8-sig") as f:
    w = csv.DictWriter(f, fieldnames=list(rows[0])); w.writeheader(); w.writerows(rows)
print("\nSaved prefinal_eval.csv   (R = repeated, P = predicted, S = in syllabus)")

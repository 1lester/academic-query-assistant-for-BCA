# Answer-quality (grounding) test. For several subjects it asks the running app "important questions in X",
# then checks every claimed question + years against the database.   Needs app.py + XAMPP running.
# Run:  py evaluate_rag.py
import re
import mysql.connector, requests
from qengine import norm_tokens, subject_key

DB = dict(host="localhost", user="root", password="", database="academic_assistant", charset="utf8mb4")
SUBJECTS = ["Operating System", "Data Structures", "Java Programming", "Computer Networks", "Python Programming",
            "Software Engineering", "Web Technology", "Database Management System"]

def score_answer(answer, groups):
    """groups: [{'text','years'}]. A 'claim' is a numbered line that lists years, e.g. '1. Define X (2019, 2021)'.
    Grounded = the question text matches a stored question; years_ok = every year listed is a real year of that question."""
    gt = [(norm_tokens(g["text"]), set(re.findall(r"20\d\d", g["years"]))) for g in groups]
    claims = grounded = years_ok = 0
    for line in answer.splitlines():
        m = re.match(r"\s*\d+[.)]\s+(.*)", line)
        ys = set(re.findall(r"\b(20\d\d)\b", line)) if m else set()
        if not m or not ys:
            continue
        claims += 1
        t = norm_tokens(re.sub(r"\(.*?\)|\[.*?\]", " ", m.group(1)))
        best, by = 0.0, set()
        for tok, gy in gt:
            if not t or not tok:
                continue
            sc = len(t & tok) / max(1, min(len(t), len(tok)))
            if sc > best:
                best, by = sc, gy
        if best >= 0.6:
            grounded += 1
            years_ok += ys <= by
    return claims, grounded, years_ok

if __name__ == "__main__":
    conn = mysql.connector.connect(**DB); cur = conn.cursor(dictionary=True)
    cur.execute("SELECT subject_key, text, years FROM question_groups"); rows = cur.fetchall(); conn.close()
    tot = [0, 0, 0]
    for s in SUBJECTS:
        k = subject_key(s)
        groups = [r for r in rows if k in r["subject_key"] or r["subject_key"] in k]
        try:
            a = requests.post("http://localhost:5000/ask", json={"question": f"Important questions in {s}"}, timeout=90).json().get("answer", "")
        except Exception as e:
            print(f"{s:30s} request failed: {e}"); continue
        c, g, y = score_answer(a, groups)
        print(f"{s:30s} claims={c:2d} grounded={g:2d} years_correct={y:2d}")
        tot = [tot[0] + c, tot[1] + g, tot[2] + y]
    if tot[0]:
        print(f"\nTotal claims: {tot[0]}  grounded in the database: {100 * tot[1] / tot[0]:.1f}%  "
              f"with correct years: {100 * tot[2] / max(1, tot[1]):.1f}%")

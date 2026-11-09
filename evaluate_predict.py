# Tests the topic-prediction model on past years (walk-forward backtest). Needs XAMPP/MySQL running.
# Run:  py evaluate_predict.py      -> prints the numbers and saves predict_eval.csv (use them in your report)
import csv
import mysql.connector
import features

DB = dict(host="localhost", user="root", password="", database="academic_assistant", charset="utf8mb4")

def db_rows(sql, args=()):
    conn = mysql.connector.connect(**DB)
    try:
        cur = conn.cursor(dictionary=True); cur.execute(sql, args); return cur.fetchall()
    finally:
        conn.close()

features.CTX["db_rows"] = db_rows
subs = features.subjects()
print(f"Subjects with topics: {len(subs)}")
rows = []
for k in (5, 10):
    bt = features.predict.backtest(subs, test_years=2, k=k)
    if not bt.get("cases"):
        raise SystemExit("Not enough years of data to test. Run build_questions.py first.")
    print(f"\nTop-{k} topics, {bt['cases']} test cases (each uses only earlier years):")
    print(f"  Model (logistic regression) : {bt['model']}%")
    print(f"  Most frequent topics        : {bt['freq_baseline']}%")
    print(f"  Most recent topics          : {bt['recent_baseline']}%")
    print(f"  Random choice               : {bt['random_baseline']}%")
    rows += [[k, r["subject"], r["year"], round(100 * r["model"], 1), round(100 * r["freq"], 1), round(100 * r["recent"], 1), round(100 * r["base"], 1)] for r in bt["rows"]]
m = features.model()
print("\nLearned weights:", dict(zip(features.predict.FEATURE_NAMES, [round(w, 2) for w in m.w])))
with open("predict_eval.csv", "w", newline="", encoding="utf-8") as f:
    w = csv.writer(f); w.writerow(["k", "subject", "test_year", "model_%", "frequency_%", "recent_%", "random_%"]); w.writerows(rows)
print("Saved predict_eval.csv")
print("\nNote: only topics asked in 2+ years are ranked, so all scores are higher than for brand-new topics.")

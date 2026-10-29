# Compares your PDF folder with the database. Run:  py check_import.py
import os
import mysql.connector

ROOT = r"C:\Users\anshu\OneDrive\Desktop\portfiloio\projectclg"
SKIP_WORDS = ["kannada", "hindi", "sanskrit", "tamil"]

conn = mysql.connector.connect(host="localhost", user="root", password="",
                               database="academic_assistant", charset="utf8mb4")
cur = conn.cursor()
cur.execute("SELECT title FROM documents")
in_db = {row[0] for row in cur.fetchall()}
conn.close()

total = regional = 0
missing = []
for folder, _, files in os.walk(ROOT):
    for f in sorted(files):
        if not f.lower().endswith(".pdf"):
            continue
        total += 1
        rel = os.path.relpath(os.path.join(folder, f), ROOT)
        if any(w in rel.lower() for w in SKIP_WORDS):
            regional += 1
            continue
        title = " - ".join(rel[:-4].replace("_", " ").split(os.sep)[-3:])
        if title not in in_db:
            missing.append(rel)

print(f"PDF files found:            {total}")
print(f"Regional-language (skipped): {regional}")
print(f"Rows in database:           {len(in_db)}")
print(f"Missing from database:      {len(missing)}")
for m in missing:
    print("  -", m)

# Builds the question-analytics tables from the papers already in MySQL.
# Run AFTER the PDFs are imported:   py build_questions.py
# Safe to run again any time: it rebuilds the tables from scratch.
import json
import mysql.connector
from qengine import extract_topics, split_questions, norm_tokens, group_questions, parse_title, subject_key, merge_keys, canon_subject

DB = dict(host="localhost", user="root", password="", database="academic_assistant", charset="utf8mb4")

conn = mysql.connector.connect(**DB)
cur = conn.cursor()

cur.execute("DROP TABLE IF EXISTS topics")
cur.execute("""CREATE TABLE topics (
    id INT AUTO_INCREMENT PRIMARY KEY,
    sem TINYINT NULL,
    subject VARCHAR(150) NOT NULL,
    subject_key VARCHAR(150) NOT NULL,
    topic VARCHAR(150) NOT NULL,
    years_count INT NOT NULL,     -- in how many different years this topic was asked
    q_count INT NOT NULL,         -- in how many questions it appears
    years VARCHAR(255) NOT NULL,
    examples TEXT NOT NULL,       -- up to 3 recent questions, separated by ||
    INDEX (sem, subject_key), INDEX (years_count)
) CHARACTER SET utf8mb4""")
cur.execute("DROP TABLE IF EXISTS questions")
cur.execute("DROP TABLE IF EXISTS question_groups")
cur.execute("""CREATE TABLE question_groups (
    id INT AUTO_INCREMENT PRIMARY KEY,
    sem TINYINT NULL,
    subject VARCHAR(150) NOT NULL,
    subject_key VARCHAR(150) NOT NULL,
    text TEXT NOT NULL,
    freq INT NOT NULL,            -- in how many different papers/years it appeared
    years VARCHAR(255) NOT NULL,
    last_year VARCHAR(10) NOT NULL,
    INDEX (sem, subject_key), INDEX (freq)
) CHARACTER SET utf8mb4""")
cur.execute("""CREATE TABLE questions (
    id INT AUTO_INCREMENT PRIMARY KEY,
    doc_id INT NOT NULL,
    group_id INT NOT NULL,
    year VARCHAR(10) NOT NULL,
    part VARCHAR(2) NOT NULL,
    text TEXT NOT NULL,
    INDEX (doc_id), INDEX (group_id)
) CHARACTER SET utf8mb4""")

cur.execute("SELECT id, title, content FROM documents WHERE category='question_paper'")
papers = cur.fetchall()

# first pass: count subject keys per semester so near-identical names can be merged
parsed = []
key_counts = {}
for doc_id, title, content in papers:
    sem, year, subject = parse_title(title)
    k = subject_key(subject)
    parsed.append((doc_id, sem, year, subject, k, content))
    key_counts.setdefault(sem, {})
    key_counts[sem][k] = key_counts[sem].get(k, 0) + 1
key_map = {sem: merge_keys(c) for sem, c in key_counts.items()}

# bucket every question by (semester, subject)
buckets = {}
n_questions = 0
for doc_id, sem, year, subject, k, content in parsed:
    qs = split_questions(content or "")
    n_questions += len(qs)
    b = buckets.setdefault((sem, key_map[sem][k]), {"subject": canon_subject(subject).title() or subject, "items": []})
    for q in qs:
        b["items"].append({"doc": doc_id, "year": year, "part": q["part"], "text": q["text"],
                           "tokens": norm_tokens(q["text"])})

n_groups = 0
n_topics = 0
for (sem, skey), b in buckets.items():
    items = b["items"]
    for idx in group_questions(items):
        members = [items[i] for i in idx]
        years = sorted({m["year"] for m in members})
        latest = max(members, key=lambda m: (m["year"], len(m["text"])))
        cur.execute("INSERT INTO question_groups (sem, subject, subject_key, text, freq, years, last_year) "
                    "VALUES (%s,%s,%s,%s,%s,%s,%s)",
                    (sem, b["subject"], skey, latest["text"], len(years), ", ".join(years), years[-1]))
        gid = cur.lastrowid
        n_groups += 1
        cur.executemany("INSERT INTO questions (doc_id, group_id, year, part, text) VALUES (%s,%s,%s,%s,%s)",
                        [(m["doc"], gid, m["year"], m["part"], m["text"]) for m in members])
    for t in extract_topics(items):
        cur.execute("INSERT INTO topics (sem, subject, subject_key, topic, years_count, q_count, years, examples) "
                    "VALUES (%s,%s,%s,%s,%s,%s,%s,%s)",
                    (sem, b["subject"], skey, t["topic"], len(t["years"]), t["n"],
                     ", ".join(t["years"]), "||".join(t["examples"])))
        n_topics += 1
    conn.commit()

cur.execute("SELECT COUNT(*) FROM question_groups WHERE freq >= 2")
repeated = cur.fetchone()[0]
conn.close()
print(f"Papers read: {len(papers)}")
print(f"Questions found: {n_questions}")
print(f"Unique questions (after grouping repeats): {n_groups}")
print(f"Questions that repeat in 2 or more years: {repeated}")
print(f"Important topics found (asked in 2+ years): {n_topics}")

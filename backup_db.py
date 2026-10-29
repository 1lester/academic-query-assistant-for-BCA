# Exports the whole academic_assistant database to academic_assistant.sql
# Run:  py backup_db.py      (MySQL must be running in XAMPP)
import datetime
import mysql.connector
from mysql.connector.conversion import MySQLConverter

conv = MySQLConverter()
def q(v):
    if v is None:
        return "NULL"
    if isinstance(v, (int, float)):
        return str(v)
    if isinstance(v, (datetime.datetime, datetime.date)):
        return "'" + v.strftime("%Y-%m-%d %H:%M:%S") + "'"
    return "'" + conv.escape(str(v)) + "'"

conn = mysql.connector.connect(host="localhost", user="root", password="",
                               database="academic_assistant", charset="utf8mb4")
cur = conn.cursor()
cur.execute("SHOW CREATE TABLE documents")
create_sql = cur.fetchone()[1]
cur.execute("SELECT id, category, title, content, keywords, created_at FROM documents ORDER BY id")
rows = cur.fetchall()

with open("academic_assistant.sql", "w", encoding="utf-8") as f:
    f.write("CREATE DATABASE IF NOT EXISTS academic_assistant CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;\n")
    f.write("USE academic_assistant;\nSET NAMES utf8mb4;\nDROP TABLE IF EXISTS documents;\n")
    f.write(create_sql + ";\n\n")
    for r in rows:
        f.write("INSERT INTO documents (id, category, title, content, keywords, created_at) VALUES ("
                + ", ".join(q(v) for v in r) + ");\n")
conn.close()
print(f"Saved {len(rows)} papers to academic_assistant.sql")

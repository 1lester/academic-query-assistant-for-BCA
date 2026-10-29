# Re-reads PDFs that have MORE pages than the first import read (combined papers),
# and updates their rows in the database with the full text.
# Run AFTER import_pdfs.py has finished:   py reimport_long.py
# Safe to stop (Ctrl + C) and run again: finished files are remembered in reimported.txt
import os, re, pdfplumber, mysql.connector
import pypdfium2 as pdfium
import pytesseract

ROOT = r"C:\Users\anshu\OneDrive\Desktop\portfiloio\projectclg"
pytesseract.pytesseract.tesseract_cmd = r"C:\Program Files\Tesseract-OCR\tesseract.exe"
SKIP_WORDS = ["kannada", "hindi", "sanskrit", "tamil"]
FIRST_IMPORT_PAGES = 8      # the first import only read this many pages
MAX_PAGES_LONG = 60         # read up to this many pages of a long PDF
OCR_SCALE = 2.5
DONE_FILE = "reimported.txt"

DB = dict(host="localhost", user="root", password="",
          database="academic_assistant", charset="utf8mb4")

def guess_category(text):
    t = text.lower()
    if "syllabus" in t: return "syllabus"
    if "time" in t and "table" in t: return "timetable"
    if "circular" in t: return "circular"
    if "notice" in t: return "notice"
    if "question" in t or "paper" in t or "qp" in t or re.search(r"20\d\d", t): return "question_paper"
    return "general"

def full_text(path, pages):
    try:
        with pdfplumber.open(path) as pdf:
            text = "\n".join((p.extract_text() or "") for p in pdf.pages[:MAX_PAGES_LONG]).strip()
        if len(text) > 200:
            return text, "text"
    except Exception:
        pass
    pdf = pdfium.PdfDocument(path)
    out = []
    for i in range(min(pages, MAX_PAGES_LONG)):
        out.append(pytesseract.image_to_string(pdf[i].render(scale=OCR_SCALE).to_pil()))
    return "\n".join(out).strip(), "ocr"

done = set()
if os.path.exists(DONE_FILE):
    done = set(open(DONE_FILE, encoding="utf-8").read().splitlines())

conn = mysql.connector.connect(**DB)
cur = conn.cursor()
updated = 0

for folder, _, files in os.walk(ROOT):
    for f in sorted(files):
        if not f.lower().endswith(".pdf"):
            continue
        path = os.path.join(folder, f)
        rel = os.path.relpath(path, ROOT)
        if any(w in rel.lower() for w in SKIP_WORDS) or rel in done:
            continue
        try:
            pages = len(pdfium.PdfDocument(path))
        except Exception:
            continue
        if pages <= FIRST_IMPORT_PAGES:
            continue

        title = " - ".join(rel[:-4].replace("_", " ").split(os.sep)[-3:])
        print(f"Long PDF ({pages} pages): {rel}")
        try:
            text, method = full_text(path, pages)
        except Exception as e:
            print("   ERROR:", e); continue
        if len(text) < 30:
            print("   nothing readable, skipped"); continue

        cur.execute("SELECT id FROM documents WHERE title=%s", (title,))
        row = cur.fetchone()
        if row:
            cur.execute("UPDATE documents SET content=%s WHERE id=%s", (text, row[0]))
        else:
            words = sorted(set(re.findall(r"[a-z0-9]+", rel.lower())) - {"pdf"})
            cur.execute("INSERT INTO documents (category,title,content,keywords) VALUES (%s,%s,%s,%s)",
                        (guess_category(rel), title, text, ", ".join(words)))
        conn.commit()
        open(DONE_FILE, "a", encoding="utf-8").write(rel + "\n")
        updated += 1
        print(f"   saved full text ({method}, {len(text)} characters)")

conn.close()
print(f"\nDone. Updated {updated} long PDFs.")

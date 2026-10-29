# Imports PDFs (including scanned ones via OCR) into the documents table.
# One-time setup:
#   1) Install Tesseract OCR (Windows): https://github.com/UB-Mannheim/tesseract/wiki
#   2) py -m pip install pdfplumber mysql-connector-python pytesseract
# Run:  py import_pdfs.py
import os, re, pdfplumber, mysql.connector
import pypdfium2 as pdfium
import pytesseract

# ---------- SETTINGS (edit these) ----------
ROOT = r"C:\Users\anshu\OneDrive\Desktop\portfiloio\projectclg"
pytesseract.pytesseract.tesseract_cmd = r"C:\Program Files\Tesseract-OCR\tesseract.exe"

# To OCR only some files first, put words here. Example: ["2023", "2024"]
# Only files whose path contains one of these words are processed. [] = process everything.
ONLY_CONTAINS = []

# Files with these words in their path are skipped (Tesseract reads English only)
SKIP_WORDS = ["kannada", "hindi", "sanskrit", "tamil"]

MAX_PAGES = 40       # max pages to OCR per PDF
OCR_SCALE = 2.5      # higher = better accuracy, slower
# -------------------------------------------

DB = dict(host="localhost", user="root", password="",
          database="academic_assistant", charset="utf8mb4")

def guess_category(text):
    t = text.lower()
    if "syllabus" in t:                                   return "syllabus"
    if "time" in t and "table" in t:                      return "timetable"
    if "circular" in t:                                   return "circular"
    if "notice" in t:                                     return "notice"
    if "question" in t or "paper" in t or "qp" in t or re.search(r"20\d\d", t):
        return "question_paper"
    return "general"

def extract_text(path):
    # 1) normal text extraction
    try:
        with pdfplumber.open(path) as pdf:
            text = "\n".join((p.extract_text() or "") for p in pdf.pages).strip()
        if len(text) > 50:
            return text, "text"
    except Exception:
        pass
    # 2) OCR for scanned PDFs
    pdf = pdfium.PdfDocument(path)
    out = []
    for i in range(min(len(pdf), MAX_PAGES)):
        img = pdf[i].render(scale=OCR_SCALE).to_pil()
        out.append(pytesseract.image_to_string(img))
    return "\n".join(out).strip(), "ocr"

conn = mysql.connector.connect(**DB)
cur = conn.cursor()
ok = skipped = 0

for folder, _, files in os.walk(ROOT):
    for f in sorted(files):
        if not f.lower().endswith(".pdf"):
            continue
        path = os.path.join(folder, f)
        rel = os.path.relpath(path, ROOT)
        if any(w in rel.lower() for w in SKIP_WORDS):
            continue
        if ONLY_CONTAINS and not any(w.lower() in rel.lower() for w in ONLY_CONTAINS):
            continue

        parts = rel[:-4].replace("_", " ").split(os.sep)
        title = " - ".join(parts[-3:])
        category = guess_category(rel)

        cur.execute("SELECT id FROM documents WHERE title=%s", (title,))
        if cur.fetchone():
            print("Already imported:", rel); continue

        try:
            text, method = extract_text(path)
        except Exception as e:
            print("ERROR:", rel, "->", e); skipped += 1; continue

        if len(text) < 30:
            print("SKIPPED (nothing readable):", rel); skipped += 1; continue

        words = sorted(set(re.findall(r"[a-z0-9]+", rel.lower())) - {"pdf"})
        cur.execute("INSERT INTO documents (category,title,content,keywords) VALUES (%s,%s,%s,%s)",
                    (category, title, text, ", ".join(words)))
        conn.commit()                      # saved after every file
        print(f"Imported [{category}] ({method}):", rel); ok += 1

conn.close()
print(f"\nDone. Imported {ok}, skipped {skipped}.")

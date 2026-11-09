"""Add one new question-paper PDF to the database (used by the Admin page).
Same logic as import_pdfs.py: read real text first, OCR the pages if the PDF is a scan."""
import os
import re
import tempfile

MAX_PAGES = 40
OCR_SCALE = 2.5
ORD = {1: "1st", 2: "2nd", 3: "3rd", 4: "4th", 5: "5th", 6: "6th"}


def extract_text(path):
    import pdfplumber
    try:
        with pdfplumber.open(path) as pdf:
            text = "\n".join((p.extract_text() or "") for p in pdf.pages).strip()
        if len(text) > 50:
            return text, "text"
    except Exception:
        pass
    import pypdfium2 as pdfium
    import pytesseract
    cmd = os.environ.get("TESSERACT_CMD", r"C:\Program Files\Tesseract-OCR\tesseract.exe")
    if os.path.exists(cmd):
        pytesseract.pytesseract.tesseract_cmd = cmd
    pdf = pdfium.PdfDocument(path)
    out = []
    for i in range(min(len(pdf), MAX_PAGES)):
        out.append(pytesseract.image_to_string(pdf[i].render(scale=OCR_SCALE).to_pil()))
    return "\n".join(out).strip(), "ocr"


def make_title(sem, year, subject):
    subject = re.sub(r"[^A-Za-z0-9 &+.()-]", " ", subject)
    subject = re.sub(r"\s+", " ", subject).strip()
    return f"BCA {ORD[int(sem)]} Sem - {int(year)} - {subject}"


def add_pdf(file_storage, sem, year, subject, conn):
    """file_storage: a Flask uploaded file. conn: open MySQL connection. Returns (doc_id, method, chars)."""
    title = make_title(sem, year, subject)
    cur = conn.cursor()
    cur.execute("SELECT id FROM documents WHERE title=%s", (title,))
    if cur.fetchone():
        raise ValueError("A paper with this title already exists: " + title)
    with tempfile.TemporaryDirectory() as d:
        path = os.path.join(d, "upload.pdf")
        file_storage.save(path)
        with open(path, "rb") as f:
            if f.read(5) != b"%PDF-":
                raise ValueError("That file is not a PDF.")
        text, method = extract_text(path)
    if len(text) < 30:
        raise ValueError("Nothing readable was found in that PDF.")
    words = sorted(set(re.findall(r"[a-z0-9]+", title.lower())))
    cur.execute("INSERT INTO documents (category,title,content,keywords) VALUES (%s,%s,%s,%s)",
                ("question_paper", title, text, ", ".join(words)))
    conn.commit()
    return cur.lastrowid, method, len(text)

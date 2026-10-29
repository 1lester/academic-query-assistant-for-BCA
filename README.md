# AI-Powered Academic Query Assistant

A chatbot for BCA students (Seshadripuram First Grade College, Bengaluru) that answers from previous
question papers and shows which topics and questions repeat most across years.

**How it works:** scanned PDFs -> OCR -> MySQL -> keyword search (PHP) -> repeat/topic analytics (Python) -> LLM (Groq) writes the answer from the retrieved papers.

## Features
- Chat: ask for a paper or for important questions of a subject/semester
- Browse papers: semester -> year -> subject
- Analytics: important topics and most repeated questions per subject
- Upload your own PDF/TXT as extra material
- Accuracy test script (`evaluate.py`)

## Tech
Python (Flask), PHP, MySQL/MariaDB (XAMPP), Tesseract OCR, Groq API, HTML/CSS/JS.

## Setup (Windows)
1. Install XAMPP, start Apache and MySQL. Install Tesseract OCR and Python 3.
2. Copy `search.php`, `browse.php`, `db_connect.php` to `C:\xampp\htdocs\backend\`.
3. In phpMyAdmin run `schema.sql`.
4. `py -m pip install -r requirements.txt`
5. Put your question-paper PDFs in a folder and set `ROOT` in `import_pdfs.py` (the PDFs are not in this repo).
6. `py import_pdfs.py`, then `py reimport_long.py`, then `py build_questions.py`
7. `set GROQ_API_KEY=your-key` (get a free key at console.groq.com), then `py app.py`
8. Open http://localhost:5000

## Accuracy test
`py evaluate.py` runs 60 search tests and prints top-1/top-3/top-5 accuracy and MRR.

## Notes
- Never commit your API key. Use the environment variable only.
- Question papers are the college's material and are not included in this repository.

## Author and license
Copyright (c) 2026 Anshu Dharsimkar. BCA project, Seshadripuram First Grade College, Bengaluru.
Released under the MIT License (see `LICENSE`): you may use and modify the code, but the copyright
notice and author name must be kept.

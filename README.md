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

### Study tools (version 2)
- **Likely topics**: a small machine-learning model (logistic regression, `predict.py`) rates how likely each topic is to appear in the next paper, with a walk-forward backtest against simple baselines
- **When asked**: topic x year grid and year chips, so you can see in which years each topic or question appeared
- **Mock paper**: builds a practice paper (Part A/B/C pattern of the newest paper) from repeated questions and likely topics; print or save as PDF
- **Practice quiz**: AI-written multiple-choice questions from past questions, with scores saved in the browser
- **Answer checker**: the AI grades a typed answer 0-10 against the syllabus and lists missing points
- **Study plan**: day-by-day plan up to the exam date, most likely topics first
- **Semantic search**: finds questions by meaning (`semantic.py`); rescues searches where keywords find nothing
- **Admin page** (`/admin`): upload a new paper PDF, OCR it and rebuild the analytics

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

## Accuracy tests
- `py evaluate.py` : 60 search tests, top-1/top-3/top-5 accuracy and MRR
- `py evaluate_hybrid.py` : keyword vs semantic vs hybrid search on the same tests
- `py evaluate_predict.py` : backtest of the topic-prediction model against baselines
- `py evaluate_rag.py` : checks that the AI's listed questions and years really exist in the database (app.py must be running)

## Admin page
Set `ADMIN_KEY` (`set ADMIN_KEY=choose-a-password`) before `py app.py`, then open http://localhost:5000/admin on the same computer.
Optional: `set SEM_BACKEND=tfidf` forces the light semantic search; install `sentence-transformers` for real embeddings.
`set HYBRID_ALWAYS=1` makes every search use keyword + semantic together (turn on only if `evaluate_hybrid.py` shows it is better).

## Notes
- Never commit your API key. Use the environment variable only.
- Question papers are the college's material and are not included in this repository.

## Author and license
Copyright 2026 Anshu Dharsimkar. BCA project, Seshadripuram First Grade College, Bengaluru.

Licensed under the [PolyForm Noncommercial License 1.0.0](https://polyformproject.org/licenses/noncommercial/1.0.0):
free for learning, research, college and personal use. Commercial use (selling it, or using it in a business
or organisation for profit) needs written permission from the author.

# FREE version of the Flask server using Google Gemini (no credit card needed).
# Setup:  py -m pip install flask requests
#         set GEMINI_API_KEY=your-key-here       (get it free at aistudio.google.com)
# Run:    py app_gemini.py     then open http://localhost:5000
import os, requests
from flask import Flask, request, jsonify, send_from_directory

SEARCH_URL = "http://localhost/backend/search.php"
# If you get a "model not found" error, open aistudio.google.com and copy a current free model name.
MODEL = "gemini-2.5-flash"
API_KEY = os.environ.get("GEMINI_API_KEY", "")
GEMINI_URL = f"https://generativelanguage.googleapis.com/v1beta/models/{MODEL}:generateContent"

app = Flask(__name__)

SYSTEM = """You are an academic assistant for BCA students of Seshadripuram First Grade College.
You are given text from previous question papers (OCR text, so it may be slightly messy).
Rules:
- Answer ONLY from the documents provided. If the answer is not there, say so.
- If the student asks for important or expected questions: find questions and topics that
  repeat across years or papers, rank them (most repeated first), mention which years they
  appeared in, and give a short list of 5-8 questions to prepare. Say these are suggestions
  based on past papers, not guaranteed.
- Keep answers clear and short. Use simple English."""

IMPORTANT_WORDS = ["important", "expected", "repeat", "frequent", "likely", "suggest", "most asked"]

@app.route("/")
def home():
    return send_from_directory(".", "index.html")

@app.route("/ask", methods=["POST"])
def ask():
    q = ((request.get_json(silent=True) or {}).get("question") or "").strip()
    if not q:
        return jsonify(error="Please type a question"), 400
    if not API_KEY:
        return jsonify(error="GEMINI_API_KEY is not set. Run: set GEMINI_API_KEY=your-key"), 500

    limit = 12 if any(w in q.lower() for w in IMPORTANT_WORDS) else 5
    try:
        r = requests.post(SEARCH_URL, data={"query": q, "limit": limit}, timeout=10)
        docs = r.json().get("results", [])
    except Exception:
        return jsonify(error="Cannot reach the database search. Is XAMPP running?"), 502

    if not docs:
        return jsonify(answer="I could not find any matching documents for that question.", sources=[])

    context = "\n\n".join(f"### {d['title']}\n{d['content'][:6000]}" for d in docs)
    body = {
        "systemInstruction": {"parts": [{"text": SYSTEM}]},
        "contents": [{"role": "user",
                      "parts": [{"text": f"Documents:\n{context}\n\nStudent question: {q}"}]}],
        "generationConfig": {"maxOutputTokens": 3000},
    }
    try:
        g = requests.post(GEMINI_URL, json=body, timeout=60,
                          headers={"x-goog-api-key": API_KEY, "Content-Type": "application/json"})
        if g.status_code == 429:
            return jsonify(error="Free limit reached. Wait one minute and try again."), 429
        data = g.json()
        if "error" in data:
            return jsonify(error="AI error: " + data["error"].get("message", "unknown")), 502
        parts = data["candidates"][0]["content"]["parts"]
        answer = "".join(p.get("text", "") for p in parts).strip()
    except Exception as e:
        return jsonify(error=f"AI error: {e}"), 502

    return jsonify(answer=answer or "The AI returned an empty answer. Try again.",
                   sources=[d["title"] for d in docs])

if __name__ == "__main__":
    app.run(port=5000, debug=True)

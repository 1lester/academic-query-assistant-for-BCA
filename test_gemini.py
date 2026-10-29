# Quick speed test for Gemini. Run:  py test_gemini.py
import time
from google import genai
c = genai.Client()
for m in ["gemini-3.8-flash", "gemini-3.8-flash-lite"]:
    t = time.time()
    try:
        r = c.models.generate_content(model=m, contents="Say hello in one short sentence.")
        print(m, "OK in", round(time.time() - t, 1), "s ->", r.text.strip())
    except Exception as e:
        print(m, "FAILED after", round(time.time() - t, 1), "s ->", str(e)[:150])

# Quick speed test for Groq. Run:  py test_ai.py
import time
from groq import Groq
c = Groq()
for m in ["openai/gpt-oss-20b", "openai/gpt-oss-120b"]:
    t = time.time()
    try:
        r = c.chat.completions.create(model=m, messages=[{"role": "user", "content": "Say hello in one short sentence."}])
        print(m, "OK in", round(time.time() - t, 1), "s ->", r.choices[0].message.content.strip())
    except Exception as e:
        print(m, "FAILED after", round(time.time() - t, 1), "s ->", str(e)[:150])

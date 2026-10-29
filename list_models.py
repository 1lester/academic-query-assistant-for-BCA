# Lists the Groq models your key can use. Run:  py list_models.py
from groq import Groq
for m in Groq().models.list().data:
    print(m.id)

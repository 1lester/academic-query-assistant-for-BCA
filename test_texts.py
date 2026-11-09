"""500 test questions in different texting styles, checked against the search.

Run (XAMPP running, project folder):
    py test_texts.py              -> makes 500 questions from YOUR subjects, checks the search, prints a table
    py test_texts.py --ask 20     -> also sends 20 random ones to the real chat (/ask) and prints the replies' first line
It saves test_texts_results.csv (one row per question). No AI is used in the default run,
so it is fast and free. A question PASSES when the right subject is in the top 3 search results.
"""
import csv, random, re, sys, time
import requests
import app                                         # database connection + clean_query + search URL
import features as F
import qfix
from qengine import parse_title, subject_key

SEED, TOTAL = 11, 500
rnd = random.Random(SEED)
ORDW = {1: ("1st", "first", "I"), 2: ("2nd", "second", "II"), 3: ("3rd", "third", "III"),
        4: ("4th", "fourth", "IV"), 5: ("5th", "fifth", "V"), 6: ("6th", "sixth", "VI")}
NEAR = {"a": "s", "e": "r", "i": "o", "o": "p", "n": "m", "t": "y", "s": "d", "r": "t", "l": "k", "u": "y", "d": "f", "c": "v"}


def typo(word):
    if len(word) < 5:
        return word
    i, k = rnd.randrange(1, len(word) - 1), rnd.choice("swap drop double near".split())
    if k == "swap":
        return word[:i] + word[i + 1] + word[i] + word[i + 2:]
    if k == "drop":
        return word[:i] + word[i + 1:]
    if k == "double":
        return word[:i] + word[i] + word[i:]
    return word[:i] + NEAR.get(word[i], word[i]) + word[i + 1:]


def typos(text):
    return " ".join(typo(w) if rnd.random() < 0.6 else w for w in text.split())


def initials(name):
    w = [x for x in re.findall(r"[A-Za-z]+", name) if x.lower() not in ("and", "of", "to", "the", "using")]
    return "".join(x[0] for x in w).lower() if len(w) >= 2 else name.lower()


INTENTS = ["important questions", "latest paper", "repeated questions", "important topics", "previous year questions"]


def make(style, subj, sem, intent):
    n, ordn = subj.lower(), ORDW[sem]
    ab = initials(subj)
    if style == "formal":
        return f"Could you please show the {intent} for {subj} in the {ordn[0]} semester?"
    if style == "casual":
        return f"{intent} of {n} {ordn[0]} sem"
    if style == "typos":
        return typos(f"{intent} in {n} {ordn[0]} sem")
    if style == "sms":
        return f"imp qs {ab} {sem}sem" if intent != "latest paper" else f"latest ppr {ab} sem{sem}"
    if style == "hinglish":
        return rnd.choice([f"{n} ke {intent} batao {ordn[0]} sem", f"bhai {n} {ordn[0]} sem ka {intent} dikhao", f"{n} me kya kya aata hai {ordn[0]} sem"])
    if style == "voice":
        return f"hey can you tell me the {intent} for {n} in {ordn[1]} semester please"
    if style == "caps":
        return f"{intent} IN {subj} {ordn[0]} SEM".upper()
    if style == "emoji":
        return f"📚 {intent} {n} {ordn[0]} sem pls 🙏"
    if style == "roman":
        return f"{intent} {n} sem {ordn[2]}"
    if style == "words_sem":
        return f"{intent} of {n} {ordn[1]} semester"
    if style == "spaced":
        return f"  {intent}   {n}    {ordn[0]}   sem ???  "
    return f"{n}"                                                   # "bare": only the subject name


STYLES = ["formal", "casual", "typos", "sms", "hinglish", "voice", "caps", "emoji", "roman", "words_sem", "spaced", "bare"]


def main():
    ents = [e for e in F.subjects().values() if e["sem"] and len(e["papers"]) >= 2 and len(subject_key(e["subject"])) >= 4]
    ents.sort(key=lambda e: -len(e["papers"]))
    ents = ents[:30]
    if not ents:
        sys.exit("No subjects found. Run build_questions.py first.")
    tests = []
    for i in range(TOTAL):
        e, st = ents[i % len(ents)], STYLES[i % len(STYLES)]
        e = rnd.choice(ents)
        tests.append({"id": i + 1, "style": st, "subject": e["subject"], "sem": e["sem"], "text": make(st, e["subject"], e["sem"], rnd.choice(INTENTS))})
    rows, t0 = [], time.time()
    for t in tests:
        try:
            if qfix.ambiguous(t["text"]):
                rows.append(dict(t, rank=-1, passed=0, asked=1)); continue          # the chat asks "which subject?"
            r = requests.post(app.SEARCH_URL, data={"query": app.clean_query(t["text"]), "limit": 10}, timeout=10).json().get("results", [])
            r = qfix.rerank(t["text"], r, 3)
            r = F.hybrid_merge(app.clean_query(t["text"]), r, 3)
        except Exception as ex:
            r = []
            t["error"] = str(ex)[:60]
        rank = 0
        for i, d in enumerate(r, 1):
            s, _, subj = parse_title(d["title"])
            if subject_key(subj) == subject_key(t["subject"]):
                rank = i
                break
        rows.append(dict(t, rank=rank, passed=int(rank > 0), asked=0))
    print(f"\n{TOTAL} questions in {len(STYLES)} styles, {len(ents)} subjects, {time.time() - t0:.0f}s\n")
    print(f"{'style':<11}{'tests':>6}{'passed':>8}{'asked':>7}{'rate':>7}")
    for st in STYLES:
        g = [r for r in rows if r["style"] == st]
        print(f"{st:<11}{len(g):>6}{sum(r['passed'] for r in g):>8}{sum(r['asked'] for r in g):>7}{round(100 * sum(r['passed'] for r in g) / max(1, len(g))):>6}%")
    tot, ask = sum(r["passed"] for r in rows), sum(r["asked"] for r in rows)
    print(f"{'ALL':<11}{len(rows):>6}{tot:>8}{ask:>7}{round(100 * tot / len(rows)):>6}%")
    print(f"('asked' = short form fits 2 subjects, so the chat asks which one you mean; not counted as passed or failed.)")
    print(f"Passed or asked: {round(100 * (tot + ask) / len(rows))}%   Real failures: {len(rows) - tot - ask}")
    print("\nSome failures:")
    for r in [r for r in rows if not r["passed"] and not r["asked"]][:12]:
        print(f"  [{r['style']}] {r['text'].strip()[:70]}   (wanted: {r['subject']})")
    with open("test_texts_results.csv", "w", newline="", encoding="utf-8-sig") as f:
        w = csv.DictWriter(f, fieldnames=["id", "style", "subject", "sem", "text", "rank", "passed", "asked"], extrasaction="ignore")
        w.writeheader(); w.writerows(rows)
    print("\nSaved test_texts_results.csv")
    if "--ask" in sys.argv:
        n = int(sys.argv[sys.argv.index("--ask") + 1]) if len(sys.argv) > sys.argv.index("--ask") + 1 else 10
        print(f"\nSending {n} random ones to the real chat (one every 4 seconds, to stay under the AI rate limit)...")
        for t in rnd.sample(tests, min(n, len(tests))):
            try:
                a = requests.post("http://localhost:5000/ask", json={"question": t["text"].strip()}, timeout=60).json()
                line = (a.get("answer") or a.get("error") or "")[:90].replace("\n", " ")
            except Exception as ex:
                line = "ERROR " + str(ex)[:60]
            print(f"[{t['style']}] {t['text'].strip()[:50]}\n     -> {line}")
            time.sleep(4)


if __name__ == "__main__":
    main()

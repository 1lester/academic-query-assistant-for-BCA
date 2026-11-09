"""Topic prediction: which topics are most likely in the NEXT paper of a subject.

No database code here. A small logistic-regression model (numpy, gradient
descent) learns from history: for every (subject, year) it looks only at the years
BEFORE that year and learns which patterns predict that a topic comes back.

Features of a topic (all between 0 and 1), computed from earlier years only:
  freq    = in what share of the earlier papers the topic was asked
  recency = 0.5 ** (papers since it was last asked)      (1 = asked in the latest paper)
  due     = how overdue it is compared with its usual gap  (0 = just asked, 1 = overdue)
  streak  = share of the last 3 papers that contained it
"""
import math
import re


def parse_years(s):
    return sorted({int(y) for y in re.findall(r"\b(20\d\d)\b", s or "")})


def features(topic_years, paper_years, target):
    """topic_years / paper_years: sorted int lists. Uses only years < target.
    Returns None if the topic was never asked before the target year."""
    P = [y for y in paper_years if y < target]
    H = [y for y in topic_years if y < target and y in P]
    if not P or not H:
        return None
    n = len(P)
    freq = len(H) / n
    since = sum(1 for y in P if y > max(H))                  # papers since last asked
    recency = 0.5 ** since
    avg_gap = n / len(H)
    due = min(since / avg_gap, 2.0) / 2.0 if avg_gap > 0 else 0.0
    last3 = P[-3:]
    streak = sum(1 for y in last3 if y in H) / len(last3)
    return [freq, recency, due, streak]


FEATURE_NAMES = ["freq", "recency", "due", "streak"]


def _sigmoid(z):
    if z < -30:
        return 0.0
    if z > 30:
        return 1.0
    return 1.0 / (1.0 + math.exp(-z))


class Model:
    """Logistic regression trained with batch gradient descent + L2 penalty."""
    def __init__(self):
        self.w = [0.0] * len(FEATURE_NAMES)
        self.b = 0.0
        self.trained_on = 0

    def fit(self, X, y, epochs=400, lr=1.0, l2=0.01):
        import numpy as np
        n = len(X)
        self.trained_on = n
        if n == 0 or len(set(y)) < 2:
            return self
        A, t = np.asarray(X, dtype=float), np.asarray(y, dtype=float)
        w, b = np.zeros(A.shape[1]), 0.0
        for _ in range(epochs):
            p = 1.0 / (1.0 + np.exp(-np.clip(A @ w + b, -30, 30)))
            e = p - t
            w -= lr * (A.T @ e / n + l2 * w)
            b -= lr * e.mean()
        self.w, self.b = [float(v) for v in w], float(b)
        return self

    def prob(self, x):
        return _sigmoid(sum(wj * xj for wj, xj in zip(self.w, x)) + self.b)


def build_samples(subjects, upto=None):
    """subjects: {key: {"papers": [years], "topics": {topic: [years]}}}.
    One sample per (subject, topic, year Y): features from years < Y, label = asked in Y.
    Only years < `upto` are used when given (to keep a test year out of training)."""
    X, y, meta = [], [], []
    for key, s in subjects.items():
        for Y in s["papers"]:
            if upto is not None and Y >= upto:
                continue
            for topic, ty in s["topics"].items():
                f = features(ty, s["papers"], Y)
                if f is None:
                    continue
                X.append(f)
                y.append(1 if Y in ty else 0)
                meta.append((key, topic, Y))
    return X, y, meta


def train(subjects, upto=None):
    X, y, _ = build_samples(subjects, upto)
    return Model().fit(X, y)


def predict_subject(model, s, target=None):
    """Ranked topics for the next paper of one subject."""
    target = target or (max(s["papers"]) + 1)
    out = []
    for topic, ty in s["topics"].items():
        f = features(ty, s["papers"], target)
        if f is None:
            continue
        out.append({"topic": topic, "prob": model.prob(f), "years": [y for y in ty if y < target],
                    "features": dict(zip(FEATURE_NAMES, [round(v, 2) for v in f]))})
    out.sort(key=lambda r: (-r["prob"], r["topic"]))
    return out


# ---------- walk-forward backtest ----------
def _p_at_k(ranked_topics, actual, k):
    top = ranked_topics[:k]
    return (sum(1 for t in top if t in actual) / len(top)) if top else None


def backtest(subjects, test_years=2, k=10, min_candidates=5):
    """For each subject and each of its last `test_years` paper-years Y: train on years < Y
    only, rank the topics, and check how many of the top-k were really asked in Y.
    Compared with two simple baselines (most frequent / most recent) and with picking at
    random (= the base rate). Returns a dict of averages."""
    rows = []
    for key, s in subjects.items():
        yrs = s["papers"]
        for Y in yrs[-test_years:]:
            if len([p for p in yrs if p < Y]) < 2:
                continue
            cands = {t: ty for t, ty in s["topics"].items() if features(ty, yrs, Y) is not None}
            if len(cands) < min_candidates:
                continue
            actual = {t for t, ty in cands.items() if Y in ty}
            kk = min(k, len(cands))
            model = train(subjects, upto=Y)
            fx = {t: features(ty, yrs, Y) for t, ty in cands.items()}
            by_model = sorted(cands, key=lambda t: (-model.prob(fx[t]), t))
            by_freq = sorted(cands, key=lambda t: (-fx[t][0], t))
            by_rec = sorted(cands, key=lambda t: (-fx[t][1], -fx[t][0], t))
            rows.append({"subject": key, "year": Y, "k": kk, "base": len(actual) / len(cands),
                         "model": _p_at_k(by_model, actual, kk), "freq": _p_at_k(by_freq, actual, kk),
                         "recent": _p_at_k(by_rec, actual, kk)})
    if not rows:
        return {"cases": 0}
    avg = lambda key: round(100 * sum(r[key] for r in rows) / len(rows), 1)
    return {"cases": len(rows), "k": k, "model": avg("model"), "freq_baseline": avg("freq"),
            "recent_baseline": avg("recent"), "random_baseline": avg("base"), "rows": rows}

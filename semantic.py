"""Semantic (meaning-based) search that works next to the keyword search.

Two back-ends, chosen automatically:
  1) sentence-transformers (all-MiniLM-L6-v2)  - real embeddings, if the package is installed
  2) TF-IDF + LSA (scikit-learn)               - lightweight fallback; learns that words which
                                                  appear in the same kinds of questions are related
Set SEM_BACKEND=tfidf to force the lightweight one.

Used for: (a) finding similar questions,  (b) rescuing searches where the keyword
search finds nothing,  (c) 'hybrid' ranking = keyword + semantic merged with Reciprocal Rank Fusion.
"""
import os
import re

import numpy as np


class SemIndex:
    def __init__(self, texts, backend=None):
        self.texts = texts
        self.backend = None
        want = (backend or os.environ.get("SEM_BACKEND", "auto")).lower()
        if want in ("auto", "st"):
            try:
                from sentence_transformers import SentenceTransformer
                self.model = SentenceTransformer("all-MiniLM-L6-v2")
                self.M = np.asarray(self.model.encode(texts, normalize_embeddings=True, show_progress_bar=False))
                self.backend = "sentence-transformers"
            except Exception:
                self.backend = None
        if self.backend is None:
            from sklearn.feature_extraction.text import TfidfVectorizer
            from sklearn.decomposition import TruncatedSVD
            self.vec = TfidfVectorizer(ngram_range=(1, 2), sublinear_tf=True, min_df=1, stop_words="english")
            X = self.vec.fit_transform(texts)
            k = max(2, min(120, X.shape[0] - 1, X.shape[1] - 1))
            self.svd = TruncatedSVD(n_components=k, random_state=1)
            Z = self.svd.fit_transform(X)
            self.M = self._norm(np.hstack([Z, 0.35 * self._norm(X.toarray())]))   # LSA + exact-word part
            self.backend = "tfidf-lsa"

    @staticmethod
    def _norm(A):
        n = np.linalg.norm(A, axis=1, keepdims=True)
        n[n == 0] = 1
        return A / n

    def _encode_query(self, q):
        if self.backend == "sentence-transformers":
            return np.asarray(self.model.encode([q], normalize_embeddings=True, show_progress_bar=False))[0]
        x = self.vec.transform([q])
        z = self.svd.transform(x)
        v = np.hstack([z, 0.35 * self._norm(x.toarray())])
        return self._norm(v)[0]

    def search(self, q, k=5):
        """Returns [(index, cosine_score), ...] best first."""
        if not self.texts or not q.strip():
            return []
        s = self.M @ self._encode_query(q)
        order = np.argsort(-s)[:k]
        return [(int(i), float(s[i])) for i in order if s[i] > 0.05]


def rrf(rankings, k=60, weights=None):
    """Reciprocal Rank Fusion. rankings: list of lists of ids (best first). Returns ids best first."""
    score = {}
    for n, r in enumerate(rankings):
        w = (weights or [1] * len(rankings))[n]
        for pos, i in enumerate(r, 1):
            score[i] = score.get(i, 0.0) + w / (k + pos)
    return sorted(score, key=lambda i: -score[i])


def doc_text(title, content, n=2500):
    t = re.sub(r"\s+", " ", content or "")[:n]
    return f"{title}. {title}. {t}"

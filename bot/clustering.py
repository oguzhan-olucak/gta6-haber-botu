"""Olay kümeleme motoru: farklı başlıklarla yayınlanan aynı haberi tek kümede toplar.

Benzerlik puanı üç sinyalin ağırlıklı toplamıdır:

* **TF-IDF kosinüs** (başlık ×2 + özetin ilk 300 karakteri), havuzdaki belgelerden öğrenilen IDF ile.
  Her haberde geçen "gta", "rockstar" gibi kelimeler otomatik olarak düşük ağırlık alır.
* **Karakter 3-gram Jaccard** (yalnızca başlık): farklı çekimler ve yazımlar için dayanıklılık.
* **Varlık/sayı örtüşmesi**: özel isimler (Lucia, PlayStation, Leonida...), sayılar ve sıra
  sayıları ("third" → 3) üzerinden Jaccard.

Yanlış birleştirmeye karşı sert kurallar:

* Her iki başlıkta da sayı varsa ve hiç ortak sayı yoksa birleştirme yok ("Trailer 2" ≠ "Trailer 3").
* Yayın zamanları ``max_gap_hours`` saatten fazla ayrıksa birleştirme yok.
* Kümeler **ortalama bağlantı** (average linkage) ile birleşir: bir kümeye katılan haberin
  kümedeki TÜM haberlere ortalama benzerliği eşiği geçmelidir. Tek bağlantı zincirlenmesi olmaz.

Aynı canonical URL veya aynı içerik özeti her zaman aynı kümededir.
"""
from __future__ import annotations

import math
import re
import unicodedata
from collections import Counter
from dataclasses import dataclass, field
from datetime import datetime
from typing import Sequence

from . import parse_iso

WEIGHT_TFIDF = 0.5
WEIGHT_CHARGRAM = 0.3
WEIGHT_ENTITY = 0.2
ENTITY_CONFLICT_FACTOR = 0.5
DEFAULT_THRESHOLD = 0.27

STOPWORDS: frozenset[str] = frozenset("""
a an the and or of to in on for with at by is are was were be been being as its it this that these those from
new about after before over into out up how what why when who which you your will would can could has have had
here more most just now first look looks says said report reports reportedly via according get gets got
not no yes all any some than then there their they them our we us his her he she it's also
gta vi grand theft auto rockstar games game 6
bir ve ile icin bu su o da de mi mu ne gibi daha cok en ama veya hem ise olarak oldu olan
""".split())

ORDINALS: dict[str, str] = {
    "first": "1", "second": "2", "third": "3", "fourth": "4", "fifth": "5", "sixth": "6", "seventh": "7",
    "eighth": "8", "ninth": "9", "tenth": "10", "1st": "1", "2nd": "2", "3rd": "3", "4th": "4", "5th": "5",
    "birinci": "1", "ikinci": "2", "ucuncu": "3", "dorduncu": "4", "besinci": "5",
}

_WORD_RE = re.compile(r"[a-z0-9]+")
_CAP_RE = re.compile(r"(?<![.!?:]\s)(?<!^)\b([A-Z][a-z]+(?:[A-Z][a-z]+)+|[A-ZÇĞİÖŞÜ][a-zçğıöşü]+|[A-Z]{2,}[0-9]*"
                     r"|[A-Za-z]+[0-9]+[A-Za-z0-9]*)\b")
ALIASES: dict[str, str] = {"ps5": "playstation", "ps4": "playstation", "xsx": "xbox", "trailers": "trailer",
                           "fragman": "trailer", "fiyat": "price", "cikis": "release"}


def fold(text: str) -> str:
    """Küçük harfe çevir, aksanları/Türkçe işaretleri at (ı→i, ş→s ...), yalnızca harf/rakam bırak."""
    text = (text or "").replace("İ", "i").replace("I", "ı").lower().replace("ı", "i")
    text = unicodedata.normalize("NFKD", text)
    text = "".join(ch for ch in text if not unicodedata.combining(ch))
    return re.sub(r"[^a-z0-9]+", " ", text).strip()


def _stem(token: str) -> str:
    """Çok hafif İngilizce kök: sondaki 's' / 'es' atılır (trailers → trailer)."""
    if len(token) > 4 and token.endswith("es") and not token.endswith("ses"):
        return token[:-2]
    if len(token) > 3 and token.endswith("s") and not token.endswith("ss"):
        return token[:-1]
    return token


def tokens(text: str) -> list[str]:
    """Durak kelimeleri çıkarılmış, sıra sayıları rakama çevrilmiş, kökleri alınmış kelime listesi."""
    out: list[str] = []
    for raw in _WORD_RE.findall(fold(text)):
        tok = ALIASES.get(raw, ORDINALS.get(raw, raw))
        if tok in STOPWORDS or (len(tok) < 2 and not tok.isdigit()):
            continue
        out.append(tok if tok.isdigit() else _stem(tok))
    return out


def numbers(text: str) -> set[str]:
    """Başlıktaki anlamlı sayılar (GTA '6' hariç; sıra sayıları dahil)."""
    return {t for t in tokens(text) if t.isdigit() and t != "6"}


def _is_title_case(title: str) -> bool:
    words = [w for w in re.findall(r"[A-Za-zÇĞİÖŞÜçğıöşü]+", title) if len(w) > 3]
    if not words:
        return False
    return sum(w[0].isupper() for w in words) / len(words) >= 0.6


def entities(title: str, summary: str) -> set[str]:
    """Özel isim adayları: cümle ortasında büyük harfle başlayan kelimeler, CamelCase
    (PlayStation), harf+rakam karışımları (PS5) ve sayılar.

    Başlıklar çoğu zaman "Title Case" yazıldığından, başlıktaki büyük harfli kelimeler
    yalnızca başlık cümle düzeninde (sentence case) yazılmışsa varlık sayılır."""
    found: set[str] = set()
    texts = [summary] if summary and len(summary) > 40 else []
    if not _is_title_case(title):
        texts.append(title)
    for text in texts:
        for m in _CAP_RE.finditer(text):
            found.update(tokens(m.group(1)))
    if not texts:
        found.update(tokens(title))
    found.update(t for t in tokens(title) if any(c.isdigit() for c in t))
    return {e for e in found if e != "6"}


def char_ngrams(text: str, n: int = 3) -> set[str]:
    """Durak kelimesiz başlığın karakter n-gramları."""
    joined = " ".join(tokens(text))
    return {joined[i:i + n] for i in range(max(0, len(joined) - n + 1))}


def jaccard(a: set[str], b: set[str]) -> float:
    """İki kümenin Jaccard benzerliği; ikisi de boşsa 0."""
    if not a or not b:
        return 0.0
    return len(a & b) / len(a | b)


@dataclass
class Doc:
    """Kümelemeye giren tek haber."""
    key: str
    title: str
    summary: str = ""
    url: str = ""
    content_hash: str = ""
    published_at: str | None = None
    terms: Counter[str] = field(default_factory=Counter)
    vocab: set[str] = field(default_factory=set)
    grams: set[str] = field(default_factory=set)
    ents: set[str] = field(default_factory=set)
    nums: set[str] = field(default_factory=set)
    when: datetime | None = None

    def prepare(self) -> "Doc":
        """Özellikleri bir kez hesapla."""
        self.terms = Counter(tokens(self.title) * 2 + tokens(self.summary[:300]))
        self.vocab = set(self.terms) | set(tokens(self.summary))
        self.grams = char_ngrams(self.title)
        self.ents = entities(self.title, self.summary)
        self.nums = numbers(self.title)
        self.when = parse_iso(self.published_at)
        return self


class SimilarityEngine:
    """Havuz üzerinde IDF öğrenip çift benzerliklerini hesaplayan motor."""

    def __init__(self, docs: Sequence[Doc], *, max_gap_hours: float = 72.0):
        self.docs = [d.prepare() if not d.terms else d for d in docs]
        self.max_gap_hours = max_gap_hours
        df: Counter[str] = Counter()
        for d in self.docs:
            df.update(set(d.terms))
        n = max(1, len(self.docs))
        self.idf = {t: math.log((1 + n) / (1 + c)) + 1.0 for t, c in df.items()}
        self._vec = [self._tfidf(d) for d in self.docs]

    def _tfidf(self, d: Doc) -> dict[str, float]:
        vec = {t: (1 + math.log(c)) * self.idf.get(t, 1.0) for t, c in d.terms.items()}
        norm = math.sqrt(sum(v * v for v in vec.values())) or 1.0
        return {t: v / norm for t, v in vec.items()}

    def _cosine(self, i: int, j: int) -> float:
        a, b = self._vec[i], self._vec[j]
        if len(a) > len(b):
            a, b = b, a
        return sum(v * b.get(t, 0.0) for t, v in a.items())

    def blocked(self, i: int, j: int) -> bool:
        """Sert engel: çelişen sayılar veya çok uzak yayın zamanı."""
        a, b = self.docs[i], self.docs[j]
        if a.nums and b.nums and not (a.nums & b.nums):
            return True
        if a.when and b.when and abs((a.when - b.when).total_seconds()) > self.max_gap_hours * 3600:
            return True
        return False

    def score(self, i: int, j: int) -> float:
        """0-1 arası birleşik benzerlik; sert engel varsa 0."""
        a, b = self.docs[i], self.docs[j]
        if (a.url and a.url == b.url) or (a.content_hash and a.content_hash == b.content_hash):
            return 1.0
        if self.blocked(i, j):
            return 0.0
        base = (WEIGHT_TFIDF * self._cosine(i, j)
                + WEIGHT_CHARGRAM * jaccard(a.grams, b.grams)
                + WEIGHT_ENTITY * jaccard(a.ents, b.ents))
        return base * ENTITY_CONFLICT_FACTOR if self.entity_conflict(i, j) else base

    def entity_conflict(self, i: int, j: int) -> bool:
        """Her iki haberin de diğerinde hiç geçmeyen ayırt edici bir özel ismi varsa
        (ör. "Lucia" ↔ "Jason", "Borderlands" ↔ "November") farklı olay olma ihtimali yüksektir."""
        a, b = self.docs[i], self.docs[j]
        a_only = {e for e in a.ents if not e.isdigit() and e not in b.vocab}
        b_only = {e for e in b.ents if not e.isdigit() and e not in a.vocab}
        return bool(a_only) and bool(b_only)


def cluster_docs(docs: Sequence[Doc], threshold: float, *, max_gap_hours: float = 72.0) -> list[list[int]]:
    """Ortalama bağlantılı aglomeratif kümeleme. Dönüş: doc indeks grupları."""
    n = len(docs)
    if n == 0:
        return []
    eng = SimilarityEngine(docs, max_gap_hours=max_gap_hours)
    sim = [[0.0] * n for _ in range(n)]
    blk = [[False] * n for _ in range(n)]
    for i in range(n):
        for j in range(i + 1, n):
            sim[i][j] = sim[j][i] = eng.score(i, j)
            blk[i][j] = blk[j][i] = sim[i][j] < 1.0 and eng.blocked(i, j)
    clusters: list[list[int]] = [[i] for i in range(n)]
    while True:
        best_score, pair = 0.0, None
        for x in range(len(clusters)):
            for y in range(x + 1, len(clusters)):
                cand = _linkage(clusters[x], clusters[y], sim, blk, threshold)
                if cand is not None and cand > best_score:
                    best_score, pair = cand, (x, y)
        if pair is None:
            break
        x, y = pair
        clusters[x] = clusters[x] + clusters[y]
        del clusters[y]
    return clusters


def _linkage(cx: list[int], cy: list[int], sim: list[list[float]], blk: list[list[bool]],
             threshold: float) -> float | None:
    """İki kümenin birleşme puanı; birleşmemeleri gerekiyorsa None.
    Zorunlu eşleşme (aynı URL/hash) 2.0 ile önceliklidir; sert engel varsa birleşme yok."""
    pairs = [(i, j) for i in cx for j in cy]
    if any(sim[i][j] >= 1.0 for i, j in pairs):
        return 2.0
    if any(blk[i][j] for i, j in pairs):
        return None
    avg = sum(sim[i][j] for i, j in pairs) / len(pairs)
    return avg if avg >= threshold else None


def best_match(title: str, candidates: Sequence[str], threshold: float) -> float:
    """Bir başlığın geçmişteki başlıklarla en yüksek benzerliği (eşik altıysa 0).
    Geçmiş kayıtlarda özet olmadığı için yalnızca başlık sinyalleri kullanılır."""
    if not candidates:
        return 0.0
    docs = [Doc(key="q", title=title)] + [Doc(key=str(i), title=t) for i, t in enumerate(candidates)]
    eng = SimilarityEngine(docs)
    best = max(eng.score(0, j) for j in range(1, len(docs)))
    return best if best >= threshold else 0.0

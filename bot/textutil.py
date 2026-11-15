"""Metin temizleme: HTML'den düz metin, Unicode normalizasyonu, bozuk UTF-8 / mojibake onarımı,
görünmez kontrol karakterlerinin atılması ve güvenli kırpma.

Görünmez biçim karakterleri (sıfır genişlikli boşluk, yön değiştiren bidi işaretleri vb.)
prompt injection gizlemek için kullanılabildiğinden tamamen atılır.
"""
from __future__ import annotations

import html
import re
import unicodedata
from html.parser import HTMLParser

_ENCODING_DECL_RE = re.compile(rb"""<\?xml[^>]*encoding=["']([A-Za-z0-9_.:-]+)["']""")
_MOJIBAKE_HINT_RE = re.compile("[ÃÄÅÂ][\u0080-ÿŒ-˜–-›]")
_WS_RE = re.compile(r"\s+")


class _TextExtractor(HTMLParser):
    """script/style içeriğini atlayan basit HTML → metin çıkarıcı."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []
        self._skip = 0

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        """HTMLParser geri çağrısı: açılış etiketi."""
        if tag in ("script", "style"):
            self._skip += 1

    def handle_endtag(self, tag: str) -> None:
        """HTMLParser geri çağrısı: kapanış etiketi."""
        if tag in ("script", "style") and self._skip:
            self._skip -= 1

    def handle_data(self, data: str) -> None:
        """HTMLParser geri çağrısı: metin verisi."""
        if not self._skip:
            self.parts.append(data)


def strip_invisible(text: str) -> str:
    """Kontrol (Cc), biçim (Cf: ZWSP, bidi override...), vekil ve özel kullanım karakterlerini atar."""
    return "".join(ch for ch in text if ch in "\n\t " or unicodedata.category(ch)[0] != "C")


def fix_mojibake(text: str) -> str:
    """UTF-8 baytlarının Latin-1/CP1252 sanılmasıyla oluşan bozulmayı onarır
    ("Ä±ÅŸÄ±k" → "ışık"). Onarım yalnızca sonuç daha az şüpheli karakter içeriyorsa uygulanır."""
    if not text or not _MOJIBAKE_HINT_RE.search(text):
        return text
    for enc in ("cp1252", "latin-1"):
        try:
            repaired = text.encode(enc).decode("utf-8")
        except (UnicodeEncodeError, UnicodeDecodeError):
            continue
        if len(_MOJIBAKE_HINT_RE.findall(repaired)) < len(_MOJIBAKE_HINT_RE.findall(text)):
            return repaired
    return text


def strip_html(text: str) -> str:
    """HTML etiketlerini atar, varlıkları çözer, NFC normalize eder, görünmez karakterleri siler,
    mojibake onarır ve boşlukları tek boşluğa indirir."""
    if not text:
        return ""
    parser = _TextExtractor()
    try:
        parser.feed(text)
        parser.close()
        out = " ".join(parser.parts)
    except Exception:  # bozuk HTML: kaba temizlik
        out = re.sub(r"<[^>]+>", " ", text)
    out = html.unescape(out)
    out = fix_mojibake(out)
    out = unicodedata.normalize("NFC", out)
    out = strip_invisible(out).replace("�", "")
    return _WS_RE.sub(" ", out).strip()


def truncate(text: str, max_chars: int, ellipsis: str = "…") -> str:
    """Metni kelime sınırında güvenle kırpar. Kırpılırsa sona ``…`` eklenir;
    sonuç hiçbir zaman ``max_chars`` uzunluğunu aşmaz ve vekil çiftleri bölünmez."""
    if max_chars <= 0:
        return ""
    if len(text) <= max_chars:
        return text
    limit = max_chars - len(ellipsis)
    if limit <= 0:
        return text[:max_chars]
    cut = text[:limit]
    space = cut.rfind(" ")
    if space >= limit * 0.6:
        cut = cut[:space]
    return cut.rstrip(" ,;:-–—") + ellipsis


# Latin harflere benzeyen Kiril/Yunan harfleri (homoglif). Enjeksiyon dedektörünü atlatmak için kullanılır.
_CONFUSABLES = str.maketrans({
    "а": "a", "е": "e", "о": "o", "р": "p", "с": "c", "у": "y", "х": "x", "і": "i", "ј": "j", "ѕ": "s",
    "ԁ": "d", "һ": "h", "ӏ": "l", "ԛ": "q", "ԝ": "w", "А": "A", "В": "B", "Е": "E", "К": "K", "М": "M",
    "Н": "H", "О": "O", "Р": "P", "С": "C", "Т": "T", "Х": "X", "І": "I", "Ј": "J", "Ѕ": "S",
    "α": "a", "ο": "o", "ρ": "p", "ε": "e", "ι": "i", "κ": "k", "ν": "v", "τ": "t", "υ": "u",
    "Α": "A", "Β": "B", "Ε": "E", "Ι": "I", "Κ": "K", "Μ": "M", "Ν": "N", "Ο": "O", "Ρ": "P", "Τ": "T",
    "Χ": "X", "Υ": "Y", "Ζ": "Z",
})


def fold_confusables(text: str) -> str:
    """Kiril/Yunan homogliflerini Latin karşılıklarına çevirir (yalnızca güvenlik denetimi için;
    yayınlanan metne uygulanmaz)."""
    return (text or "").translate(_CONFUSABLES)


def normalize_text(text: str) -> str:
    """Karşılaştırma için: küçük harf, aksansız, yalnızca a-z0-9 ve boşluk.
    Türkçe İ/ı doğru katlanır (İ → i, ı → i)."""
    text = (text or "").replace("İ", "i").replace("I", "ı").lower().replace("ı", "i")
    text = unicodedata.normalize("NFKD", text)
    text = "".join(ch for ch in text if not unicodedata.combining(ch))
    return re.sub(r"[^a-z0-9 ]+", " ", text).strip()


def tr_upper(text: str) -> str:
    """Türkçe büyük harf: i → İ, ı → I (``str.upper`` 'i'yi 'I' yapar)."""
    return (text or "").replace("i", "İ").replace("ı", "I").upper()


def repair_feed_bytes(content: bytes) -> str:
    """Geçersiz bayt içeren beslemeyi, bildirilen kodlamayla (yoksa UTF-8) ``errors='replace'``
    kullanarak metne çevirir ve XML bildirimini kaldırır (ayrıştırıcı str ile çalışsın diye)."""
    if content.startswith(b"\xef\xbb\xbf"):
        content = content[3:]
    m = _ENCODING_DECL_RE.search(content[:200])
    encoding = m.group(1).decode("ascii", "ignore") if m else "utf-8"
    try:
        text = content.decode(encoding, errors="replace")
    except LookupError:
        text = content.decode("utf-8", errors="replace")
    return re.sub(r"^\s*<\?xml[^>]*\?>", "", text, count=1)

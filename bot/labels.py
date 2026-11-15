"""Yayın etiketleri ve deterministik değerlendirme sonucunun veri tipi.

Etiketi her zaman Python kodu belirler; LLM çıktısı etiketi değiştiremez.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Literal

from .collector import Item

OFFICIAL_DOMAINS: tuple[str, ...] = ("rockstargames.com", "take2games.com")


class Label(str, Enum):
    """Kanal gönderisinin doğrulama düzeyi."""
    OFFICIAL = "OFFICIAL"
    MULTI_SOURCE = "MULTI_SOURCE"
    SINGLE_SOURCE = "SINGLE_SOURCE"
    LEAK_CLAIM = "LEAK_CLAIM"
    COMMUNITY_CLAIM = "COMMUNITY_CLAIM"


LABEL_TEXT: dict[Label, str] = {
    Label.OFFICIAL: "RESMÎ AÇIKLAMA",
    Label.MULTI_SOURCE: "ÇOKLU KAYNAK",
    Label.SINGLE_SOURCE: "TEK KAYNAK",
    Label.LEAK_CLAIM: "SIZINTI İDDİASI",
    Label.COMMUNITY_CLAIM: "TOPLULUK İDDİASI",
}

LABEL_NOTE: dict[Label, str] = {
    Label.OFFICIAL: "Rockstar Games / Take-Two resmî kanalında doğrudan duyuruldu.",
    Label.MULTI_SOURCE: "Birbirinden bağımsız en az iki yayın organıyla destekleniyor.",
    Label.SINGLE_SOURCE: "Tek bir yayın organının haberi; resmî doğrulama yok.",
    Label.LEAK_CLAIM: "Doğrulanmamış sızıntı iddiası; resmî açıklama değildir.",
    Label.COMMUNITY_CLAIM: "Topluluk kaynaklı, doğrulanmamış iddia.",
}

STRENGTH_KEY: dict[Label, str] = {
    Label.OFFICIAL: "OFFICIAL",
    Label.MULTI_SOURCE: "MULTI_SOURCE",
    Label.SINGLE_SOURCE: "SINGLE_SOURCE",
    Label.LEAK_CLAIM: "COMMUNITY",
    Label.COMMUNITY_CLAIM: "COMMUNITY",
}

Decision = Literal["CANDIDATE", "HOLD", "REJECT"]


@dataclass
class Assessment:
    """Bir olay kümesi için deterministik karar."""
    decision: Decision
    label: Label | None
    source_strength: int
    editorial_priority: int
    reason: str
    primary: Item | None
    independent_origins: list[str] = field(default_factory=list)
    items: list[Item] = field(default_factory=list)  # karara giren (ayıklanmış) öğeler

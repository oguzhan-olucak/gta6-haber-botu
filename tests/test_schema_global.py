"""Ücretsiz model şema sapmalarına tolerans ve İngilizce (global) sürüm denetimi."""
from __future__ import annotations

import json

from bot.gemini import GeneratedContent, ValidationOutcome, english_ok, parse_output
from bot.labels import Label

BASE = {"title_tr": "GTA VI için yeni bir iddia gündemde", "summary_tr": "Örnek özet metni " * 5,
        "category": "OTHER", "title_style": "FACTUAL", "claim_type": "RUMOR",
        "source_urls": ["https://insider-gaming.com/a"], "why_this_label": "t", "needs_review": False}


def test_common_free_model_deviations_are_coerced_not_rejected():
    raw = dict(BASE, category="gameplay tech", title_style="weird", claim_type="reported", needs_review="false",
               why_this_label="x" * 900, source_urls=[f"https://a.com/{i}" for i in range(9)], extra_field=1,
               confidence=0.9)
    out = parse_output("Here you go:\n" + json.dumps(raw) + "\nThanks")
    assert isinstance(out, GeneratedContent)
    assert out.category == "GAMEPLAY_TECH" and out.title_style == "FACTUAL" and out.claim_type == "REPORTED"
    assert out.needs_review is False and len(out.why_this_label) == 300 and len(out.source_urls) == 5


def test_missing_core_fields_still_rejected():
    raw = dict(BASE)
    raw.pop("title_tr")
    out = parse_output(json.dumps(raw))
    assert isinstance(out, ValidationOutcome) and out.error_class == "GEMINI_SCHEMA_ERROR"
    assert isinstance(parse_output("tamamen metin"), ValidationOutcome)


def test_unknown_needs_review_defaults_to_safe_true():
    raw = dict(BASE)
    raw.pop("needs_review")
    out = parse_output(json.dumps(raw))
    assert isinstance(out, GeneratedContent) and out.needs_review is True


class _A:
    def __init__(self, label):
        self.label = label


class _I:
    def __init__(self, title, summary=""):
        self.title, self.summary = title, summary


def test_english_version_checks():
    cluster = [_I("GTA 6 preload is 212 GB on Xbox", "Rockstar says preload starts November 10")]
    good = GeneratedContent(**dict(BASE, title_en="GTA 6 preload needs up to 212 GB",
                                   summary_en="Rockstar says the preload starts on November 10 for digital buyers."))
    assert english_ok(good, cluster, _A(Label.OFFICIAL))
    invented = good.model_copy(update={"summary_en": "The preload is 300 GB and starts on November 10, says Rockstar."})
    assert not english_ok(invented, cluster, _A(Label.OFFICIAL))
    certain = good.model_copy(update={"title_en": "It's official: GTA 6 preload needs 212 GB"})
    assert not english_ok(certain, cluster, _A(Label.SINGLE_SOURCE))
    empty = good.model_copy(update={"title_en": ""})
    assert not english_ok(empty, cluster, _A(Label.OFFICIAL))

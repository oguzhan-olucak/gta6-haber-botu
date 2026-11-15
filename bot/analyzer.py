"""Geri besleme: yalnızca Bot API ile gerçekten alınabilen metrikler.

Ölçülebilen:   ``message_reaction_count`` güncellemeleri (anonim toplam reaksiyon sayıları).
               Bot kanalda yönetici olmalı ve getUpdates ``allowed_updates`` içinde açıkça
               "message_reaction_count" istemelidir. Güncellemeler gruplanır, birkaç dakika
               gecikebilir ve yalnızca bundan SONRAKİ değişiklikler gelir (geriye dönük sorgu yok).
Ölçülemeyen:   views / forwards -> her zaman "unavailable". MTProto kullanıcı oturumu kullanılmaz.
Kullanıcı bazlı ``message_reaction`` güncellemeleri istenmez; kullanıcı kimliği saklanmaz.
"""
from __future__ import annotations

import statistics
from collections import defaultdict
from datetime import datetime, timedelta, timezone

from . import iso, parse_iso
from .config import Settings

ALLOWED_UPDATES = ["message_reaction_count"]
UNAVAILABLE = "unavailable"


def _reaction_key(r: dict) -> str:
    t = r.get("type") or {}
    kind = t.get("type")
    if kind == "emoji":
        return f"emoji:{t.get('emoji', '?')}"
    if kind == "custom_emoji":
        return "custom_emoji"
    if kind == "paid":
        return "paid"
    return "other"


def ensure_metrics(post: dict) -> dict:
    """Gönderide metrik alanlarını (views/forwards = unavailable) garanti eder."""
    m = post.setdefault("metrics", {})
    m.setdefault("views", UNAVAILABLE)
    m.setdefault("forwards", UNAVAILABLE)
    m.setdefault("reaction_snapshots", [])
    post.setdefault("measurement_status", "PENDING")
    return m


def apply_updates(updates: list[dict], history: dict, state: dict) -> dict:
    """getUpdates sonuçlarını işler. İdempotent: aynı update iki kez gelse de sonuç değişmez
    (reaksiyon sayıları mutlak değerdir; aynı tarihli snapshot tekrar eklenmez)."""
    by_key = {(str(p.get("chat_id")), p.get("message_id")): p for p in history.get("posts", [])
              if p.get("message_id") is not None}
    stats = {"updates": len(updates), "matched": 0, "unmatched": 0}
    max_id = None
    for u in updates:
        uid = u.get("update_id")
        if isinstance(uid, int):
            max_id = uid if max_id is None else max(max_id, uid)
        rc = u.get("message_reaction_count")
        if not isinstance(rc, dict):
            continue
        chat_id = str((rc.get("chat") or {}).get("id"))
        post = by_key.get((chat_id, rc.get("message_id")))
        if post is None:
            stats["unmatched"] += 1
            continue
        m = ensure_metrics(post)
        when = rc.get("date")
        at = iso(datetime.fromtimestamp(when, tz=timezone.utc)) if isinstance(when, int) else None
        by_type: dict[str, int] = defaultdict(int)
        for r in rc.get("reactions") or []:
            cnt = r.get("total_count")
            if isinstance(cnt, int) and cnt >= 0:
                by_type[_reaction_key(r)] += cnt
        snap = {"at": at, "update_id": uid, "total": sum(by_type.values()), "by_type": dict(by_type)}
        if any(s.get("update_id") == uid or (s.get("at") == at and s.get("total") == snap["total"])
               for s in m["reaction_snapshots"]):
            continue
        m["reaction_snapshots"].append(snap)
        m["reaction_snapshots"].sort(key=lambda s: s.get("at") or "")
        del m["reaction_snapshots"][:-30]
        state["reaction_pipeline_verified"] = True
        if not state.get("reaction_pipeline_since"):
            # Akışın kanıtlandığı en erken an: ilgili gönderinin yayın zamanı
            state["reaction_pipeline_since"] = post.get("published_at") or at
        stats["matched"] += 1
    if max_id is not None:
        state["telegram_update_offset"] = max_id + 1
    return stats


def reactions_at_window(post: dict, window_hours: int) -> int | None:
    """Yayından sonraki ölçüm penceresi sonundaki son toplam reaksiyon sayısı."""
    published = parse_iso(post.get("published_at"))
    snaps = (post.get("metrics") or {}).get("reaction_snapshots") or []
    if not published or not snaps:
        return None
    limit = published + timedelta(hours=window_hours)
    eligible = [s for s in snaps if (t := parse_iso(s.get("at"))) is not None and t <= limit]
    return eligible[-1]["total"] if eligible else None


def update_measurement_status(history: dict, state: dict, settings: Settings, now: datetime) -> dict:
    """Yayınlanan gönderilerin ölçüm durumunu (PENDING/PARTIAL/COMPLETE/UNAVAILABLE) günceller."""
    counts = {"PENDING": 0, "PARTIAL": 0, "COMPLETE": 0, "UNAVAILABLE": 0, "updated": 0}
    for p in history.get("posts", []):
        if p.get("publish_status") != "PUBLISHED":
            continue
        m = ensure_metrics(p)
        published = parse_iso(p.get("published_at"))
        before = p.get("measurement_status")
        if not published or now < published + timedelta(hours=settings.measurement_window_hours):
            status = "PARTIAL" if m["reaction_snapshots"] else "PENDING"
        else:
            val = reactions_at_window(p, settings.measurement_window_hours)
            if val is not None:
                status, m["reactions_24h"], m["reactions_24h_inferred_zero"] = "COMPLETE", val, False
            elif m["reaction_snapshots"]:
                # Pencere içinde snapshot yok ama sonradan var: ilk değer pencereyi temsil etmez.
                status = "PARTIAL"
            elif state.get("reaction_pipeline_verified") and (since := parse_iso(state.get("reaction_pipeline_since"))) \
                    and since <= published:
                # Kanal için reaksiyon akışı kanıtlanmış ve bu gönderi için hiç güncelleme gelmemiş:
                # 0 reaksiyon olarak çıkarsanır, açıkça işaretlenir.
                status, m["reactions_24h"], m["reactions_24h_inferred_zero"] = "COMPLETE", 0, True
            else:
                status = "UNAVAILABLE"
        p["measurement_status"] = status
        counts[status] += 1
        if before != status:
            counts["updated"] += 1
    return counts


def _group_stats(values: list[int]) -> dict:
    return {"n": len(values), "mean": round(statistics.fmean(values), 2) if values else None,
            "median": statistics.median(values) if values else None}


def analyze(history: dict, settings: Settings, now: datetime) -> dict:
    """Kategori ve başlık stiline göre etkileşim analizi; yetersiz örneklemde kazanan ilan etmez."""
    measured = [p for p in history.get("posts", []) if p.get("measurement_status") == "COMPLETE"
                and isinstance((p.get("metrics") or {}).get("reactions_24h"), int)]
    by_cat: dict[str, list[int]] = defaultdict(list)
    by_style: dict[str, list[int]] = defaultdict(list)
    cross: dict[str, dict[str, int]] = defaultdict(lambda: defaultdict(int))
    for p in measured:
        v = p["metrics"]["reactions_24h"]
        by_cat[p.get("category", "OTHER")].append(v)
        by_style[p.get("title_style", "FACTUAL")].append(v)
        cross[p.get("category", "OTHER")][p.get("title_style", "FACTUAL")] += 1
    published_times = [t for t in (parse_iso(p.get("published_at")) for p in measured) if t is not None]

    def rank(groups: dict[str, list[int]]) -> dict:
        """Gruplar arasında medyana göre sıralama (her grupta n ≥ min_sample_per_group şartıyla)."""
        eligible = {k: v for k, v in groups.items() if len(v) >= settings.min_sample_per_group}
        if len(eligible) < 2:
            return {"result": "YETERSİZ VERİ",
                    "note": f"Karşılaştırma için en az 2 grupta n≥{settings.min_sample_per_group} gerekir."}
        ordered = sorted(eligible.items(), key=lambda kv: statistics.median(kv[1]), reverse=True)
        min_n = min(len(v) for v in eligible.values())
        return {"result": "ERKEN SİNYAL" if min_n < settings.early_signal_below_n else "SİNYAL",
                "leader": ordered[0][0], "trailing": ordered[-1][0],
                "note": "Medyan 24 saatlik toplam reaksiyon karşılaştırması; nedensellik iddia edilmez."}

    style_rank = rank(by_style)
    hints: dict = {}
    if style_rank.get("result") in ("ERKEN SİNYAL", "SİNYAL") and style_rank["leader"] != "BREAKING":
        # Yalnızca sunum tarzı önerisi; diğer stiller kapatılmaz.
        hints = {"preferred_title_styles": [style_rank["leader"]]}

    status = "YETERSİZ VERİ"
    if style_rank.get("result") in ("ERKEN SİNYAL", "SİNYAL") or rank(by_cat).get("result") in ("ERKEN SİNYAL", "SİNYAL"):
        status = "ERKEN SİNYAL" if "ERKEN" in (style_rank.get("result", "") + rank(by_cat).get("result", "")) else "SİNYAL"

    return {
        "schema_version": 1,
        "generated_at": iso(now),
        "status": status,
        "measurement_window_hours": settings.measurement_window_hours,
        "period": {"from": iso(min(published_times)) if published_times else None,
                   "to": iso(max(published_times)) if published_times else None},
        "metric_source": "Telegram Bot API message_reaction_count (anonim toplam reaksiyon)",
        "metrics_available": ["reactions_total"],
        "metrics_unavailable": {"views": UNAVAILABLE, "forwards": UNAVAILABLE},
        "sample_size": len(measured),
        "inferred_zero_count": sum(1 for p in measured if p["metrics"].get("reactions_24h_inferred_zero")),
        "by_category": {k: _group_stats(v) for k, v in sorted(by_cat.items())},
        "by_title_style": {k: _group_stats(v) for k, v in sorted(by_style.items())},
        "category_x_style_counts": {k: dict(v) for k, v in cross.items()},
        "category_ranking": rank(by_cat),
        "title_style_ranking": style_rank,
        "uncertainty_note": ("Görüntülenme paydası olmadığı için reaksiyon ORANI hesaplanmaz; yalnızca mutlak "
                             "reaksiyon sayısı 'etkileşim' olarak raporlanır. Küçük örneklemde sonuçlar erken "
                             "sinyaldir. Reaksiyon gelmeyen gönderiler, akış kanıtlanmışsa 0 sayılır."),
        "prompt_hints": hints,
    }

"""Tek çalışma (GitHub Actions her ~20 dakikada bir çağırır).

Sıra: ayar doğrulama -> veri dosyaları (bozuksa güvenli mod) -> secret kontrolü ->
reaksiyon güncellemeleri -> [paused değilse] toplama -> kümeleme/tekrar -> deterministik
değerlendirme -> Gemini (limitli) -> çıktı doğrulama -> idempotent yayın -> analiz ->
sağlık/alarmlar -> yönetici özeti -> saklama sınırları -> atomik kayıt -> JSON çalışma özeti.

Çıkış kodları: 0 normal, 1 yapılandırma/secret eksik, 2 güvenli mod (bozuk veri).
"""
from __future__ import annotations

import json
import logging
import sys
import time
from datetime import datetime, timedelta
from pathlib import Path
from typing import Callable, Mapping

import requests

from . import ErrorClass, iso, parse_iso, utcnow
from .analyzer import ALLOWED_UPDATES, analyze, apply_updates, update_measurement_status
from .collector import Item, collect, verify_source_url
from .config import (CONFIG_DIR, DATA_DIR, ConfigError, load_secrets, load_settings, load_sources, redact,
                     setup_logging)
from .processor import (LABEL_TEXT, RESPONSE_JSON_SCHEMA, SYSTEM_INSTRUCTION, GeminiError, GeminiGenerator,
                        Generator, assess, build_prompt, cluster_items, is_duplicate_of_history,
                        load_style_hints, validate_generated)
from .publisher import (due_digest_key, mark_alert, mark_digest_sent, minutes_since_last_post,
                        posts_in_last_24h, publish_post, render_alert, render_digest, render_post, send_admin,
                        should_alert)
from .storage import (CorruptDataError, FileLock, LockError, default_history, default_insights, default_state,
                      read_json, write_if_changed, write_json_atomic)
from .telegram_client import TelegramClient, TelegramError

log = logging.getLogger("gta6bot")


def _new_summary(now: datetime) -> dict:
    return {
        "started_at": iso(now), "finished_at": None, "paused": False, "safe_mode": False,
        "sources_checked": 0, "sources_ok": 0, "new_items": 0, "duplicates_or_filtered": 0,
        "held": 0, "rejected": 0, "gemini_calls": 0, "gemini_errors": 0, "published": 0,
        "review_held": 0, "uncertain": 0, "measurements_updated": 0, "measurements_pending": 0,
        "reaction_updates": 0, "daily_limit_reached": False, "error_classes": [], "notes": [],
    }


def _prune(state: dict, history: dict, settings, now: datetime) -> None:
    r = settings.retention_limits
    seen_age = max(r.seen_items_max_age_hours, settings.max_item_age_hours + 24)
    cutoff = now - timedelta(hours=seen_age)
    seen = state.get("seen_items", {})
    seen = {k: v for k, v in seen.items() if (parse_iso(v.get("first_seen")) or now) >= cutoff}
    if len(seen) > r.seen_items_max_records:
        seen = dict(sorted(seen.items(), key=lambda kv: kv[1].get("first_seen") or "")[-r.seen_items_max_records:])
    state["seen_items"] = seen
    pool_cutoff = now - timedelta(hours=settings.max_item_age_hours)
    state["candidate_pool"] = {
        k: v for k, v in state.get("candidate_pool", {}).items()
        if (parse_iso(v["item"].get("published_at")) or parse_iso(v.get("first_seen")) or now) >= pool_cutoff
    }
    hist_cutoff = now - timedelta(days=r.history_max_age_days)
    posts = [p for p in history.get("posts", [])
             if (parse_iso(p.get("published_at") or p.get("created_at")) or now) >= hist_cutoff]
    history["posts"] = posts[-r.history_max_records:]
    state["run_log"] = state.get("run_log", [])[-r.run_log_max_records:]


def _alert(state, settings, telegram, admin_chat_id, key: str, error_class: str, detail: str, now, summary) -> None:
    if should_alert(state, key, settings, now):
        sent = send_admin(telegram, admin_chat_id, render_alert(error_class, detail, settings, now))
        mark_alert(state, key, now)
        summary["notes"].append(f"alarm:{key}:{'gönderildi' if sent else 'log'}")


def run(*, now: datetime | None = None, env: Mapping[str, str] | None = None,
        session: requests.Session | None = None, telegram: TelegramClient | None = None,
        generator: Generator | None = None, data_dir: Path | None = None, config_dir: Path | None = None,
        url_verifier: Callable[[str, list[str]], tuple[bool, str]] | None = None) -> tuple[int, dict]:
    setup_logging()
    now = now or utcnow()
    data_dir = Path(data_dir or DATA_DIR)
    config_dir = Path(config_dir or CONFIG_DIR)
    summary = _new_summary(now)

    try:
        settings = load_settings(config_dir / "settings.json")
        sources = load_sources(config_dir / "sources.json")
    except (ConfigError, CorruptDataError) as exc:
        summary["error_classes"].append(ErrorClass.DATA_SCHEMA_ERROR.value)
        summary["notes"].append(str(exc))
        log.error("Yapılandırma hatası: %s", exc)
        return 1, _finish(summary)

    lock = FileLock(data_dir / ".run.lock")
    try:
        lock.acquire()
    except LockError as exc:
        summary["notes"].append(str(exc))
        return 0, _finish(summary)
    try:
        return _run_locked(settings, sources, now, env, session, telegram, generator, data_dir, summary,
                           url_verifier)
    finally:
        lock.release()


def _run_locked(settings, sources, now, env, session, telegram, generator, data_dir, summary, url_verifier):
    state_path, history_path, insights_path = data_dir / "state.json", data_dir / "history.json", \
        data_dir / "insights.json"
    try:
        state = read_json(state_path, default_state)
    except CorruptDataError as exc:
        summary["safe_mode"] = True
        summary["error_classes"].append(ErrorClass.DATA_SCHEMA_ERROR.value)
        summary["notes"].append(f"{exc} — yedek: {exc.backup.name if exc.backup else '-'}; GÜVENLİ MOD")
        log.error("state.json bozuk; güvenli mod. İnsan müdahalesi gerekli.")
        return 2, _finish(summary)
    for k, v in default_state().items():
        state.setdefault(k, v)
    state.setdefault("candidate_pool", {})

    safe_mode = False
    try:
        history = read_json(history_path, default_history)
        if not isinstance(history.get("posts"), list):
            raise CorruptDataError(history_path, None, "posts listesi yok")
    except CorruptDataError as exc:
        safe_mode = True
        history = {"posts": []}
        summary["safe_mode"] = True
        summary["error_classes"].append(ErrorClass.DATA_SCHEMA_ERROR.value)
        summary["notes"].append(f"{exc}; yayın ve Gemini devre dışı (GÜVENLİ MOD)")

    secrets, missing = load_secrets(env)
    if secrets is None:
        summary["error_classes"].append(ErrorClass.AUTH_PERMISSION.value)
        summary["notes"].append("Eksik ortam değişkeni: " + ", ".join(missing))
        log.error("Eksik ortam değişkenleri: %s", ", ".join(missing))
        state["last_run_at"] = iso(now)
        write_if_changed(state_path, state)
        return 1, _finish(summary)

    session = session or requests.Session()
    telegram = telegram or TelegramClient(secrets.telegram_bot_token, session=session,
                                          timeout=settings.http_timeout_seconds,
                                          max_retries=settings.http_max_retries)
    admin = secrets.admin_chat_id
    state["first_run_at"] = state.get("first_run_at") or iso(now)

    if safe_mode:
        _alert(state, settings, telegram, admin, "SAFE_MODE_HISTORY", ErrorClass.DATA_SCHEMA_ERROR.value,
               "history.json bozuk; yedeği alındı, yayın durduruldu. Dosyayı düzeltin veya yedekten geri yükleyin.",
               now, summary)

    # ---- 1) Reaksiyon güncellemeleri (paused iken de ölçüm sürer; içerik yayınlanmaz) ----
    if not safe_mode:
        try:
            updates = telegram.get_updates(state.get("telegram_update_offset"), ALLOWED_UPDATES)
            st = apply_updates(updates, history, state)
            summary["reaction_updates"] = st["matched"]
        except TelegramError as exc:
            summary["error_classes"].append(exc.error_class.value)
            if exc.error_class == ErrorClass.AUTH_PERMISSION:
                _alert(state, settings, telegram, admin, "TELEGRAM_AUTH", exc.error_class.value,
                       "Telegram token veya bot yetkisi reddedildi (401/403).", now, summary)
            elif exc.status == 409:
                _alert(state, settings, telegram, admin, "TELEGRAM_WEBHOOK", exc.error_class.value,
                       "getUpdates 409: botta webhook ayarlı olabilir. deleteWebhook gerekli.", now, summary)
        mc = update_measurement_status(history, state, settings, now)
        summary["measurements_updated"] = mc["updated"]
        summary["measurements_pending"] = mc["PENDING"] + mc["PARTIAL"]

    # ---- 2) İçerik hattı ----
    if settings.paused:
        summary["paused"] = True
        summary["notes"].append("paused=true: toplama, Gemini ve yayın atlandı")
    elif not safe_mode:
        _content_pipeline(settings, sources, state, history, insights_path, history_path, session, telegram,
                          generator, secrets, summary, now, url_verifier)

    # ---- 3) Analiz ----
    if not safe_mode:
        insights = analyze(history, settings, now)
        write_if_changed(insights_path, insights)
    else:
        insights = default_insights()

    # ---- 4) Sağlık ----
    last_ok = parse_iso(state.get("last_successful_fetch_at")) or parse_iso(state.get("first_run_at")) or now
    if not settings.paused and now - last_ok >= timedelta(hours=settings.health_alert_hours):
        _alert(state, settings, telegram, admin, "NO_DATA_24H", ErrorClass.NETWORK_TRANSIENT.value,
               f"{settings.health_alert_hours} saattir hiçbir kaynaktan veri alınamadı.", now, summary)
    for sid, st in state.get("source_status", {}).items():
        if st.get("error_class") == ErrorClass.AUTH_PERMISSION.value:
            _alert(state, settings, telegram, admin, f"SOURCE_AUTH_{sid}", ErrorClass.AUTH_PERMISSION.value,
                   f"Kaynak {sid} 401/403 döndürüyor.", now, summary)

    # ---- 5) Yönetici özeti ----
    key = due_digest_key(settings, state, now)
    if key:
        send_admin(telegram, admin, render_digest(summary, history, insights, settings, now))
        mark_digest_sent(state, key)  # admin yoksa da işaretle: aynı pencerede tekrar denenmez
        summary["notes"].append(f"özet:{key}")

    # ---- 6) Kayıt ----
    state["last_run_at"] = iso(now)
    _prune(state, history, settings, now)
    state["run_log"].append({k: summary[k] for k in ("started_at", "sources_ok", "new_items", "published",
                                                      "gemini_calls", "error_classes")})
    if not safe_mode:
        write_if_changed(history_path, history)
    write_if_changed(state_path, state)
    return (2 if safe_mode else 0), _finish(summary)


def _content_pipeline(settings, sources, state, history, insights_path, history_path, session, telegram,
                      generator, secrets, summary, now, url_verifier):
    result = collect(sources, settings, session, now)
    summary["sources_checked"], summary["sources_ok"] = result.sources_checked, result.sources_ok
    summary["error_classes"].extend(result.errors)
    state.setdefault("source_status", {}).update(result.source_status)
    if result.sources_ok > 0:
        state["last_successful_fetch_at"] = iso(now)

    seen = state.setdefault("seen_items", {})
    pool = state.setdefault("candidate_pool", {})
    new_ids: set[str] = set()
    for it in result.items:
        if it.id in seen:
            summary["duplicates_or_filtered"] += 1
            continue
        seen[it.id] = {"first_seen": iso(now), "status": "NEW", "source": it.source_id}
        pool[it.id] = {"item": it.to_dict(), "first_seen": iso(now), "needs_eval": True}
        new_ids.add(it.id)
    summary["new_items"] = len(new_ids)

    pool_items = [Item(**v["item"]) for v in pool.values()]
    to_eval = []
    for cluster in cluster_items(pool_items, settings.title_similarity_threshold):
        if not any(pool[i.id].get("needs_eval") for i in cluster):
            continue
        for i in cluster:
            pool[i.id]["needs_eval"] = False
        if is_duplicate_of_history(cluster, history, settings, now):
            _retire(cluster, pool, seen, "DUPLICATE")
            summary["duplicates_or_filtered"] += len(cluster)
            continue
        a = assess(cluster, settings, now)
        if a.decision == "REJECT":
            _retire(cluster, pool, seen, "REJECTED")
            summary["rejected"] += 1
        elif a.decision == "HOLD":
            for i in cluster:
                seen[i.id]["status"] = "HELD"
            summary["held"] += 1
        else:
            to_eval.append((cluster, a))
    to_eval.sort(key=lambda ca: ca[1].editorial_priority, reverse=True)

    remaining = settings.max_daily_posts - posts_in_last_24h(history, now)
    blocked_until = parse_iso(state.get("gemini_quota_blocked_until"))
    style_hints = load_style_hints(insights_path)
    generator = generator or GeminiGenerator(secrets.gemini_api_key, secrets.gemini_model)
    verifier = url_verifier or (lambda url, domains: verify_source_url(url, domains, session, settings))
    domains_by_source = {s.id: s.allowed_domains for s in sources}

    def persist() -> None:
        write_json_atomic(history_path, history)

    for cluster, a in to_eval:
        if remaining <= 0:
            summary["daily_limit_reached"] = True
            _requeue(cluster, pool)
            continue
        since = minutes_since_last_post(history, now)
        if since is not None and since < settings.min_minutes_between_posts:
            summary["notes"].append("gönderiler arası minimum süre bekleniyor")
            _requeue(cluster, pool)
            continue
        if blocked_until and now < blocked_until:
            summary["notes"].append("Gemini kotası soğuma süresinde")
            _requeue(cluster, pool)
            continue
        if summary["gemini_calls"] >= settings.max_gemini_calls_per_run:
            _requeue(cluster, pool)
            continue

        summary["gemini_calls"] += 1
        try:
            raw = generator.generate(SYSTEM_INSTRUCTION, build_prompt(cluster, a, style_hints, settings),
                                     RESPONSE_JSON_SCHEMA)
        except GeminiError as exc:
            summary["gemini_errors"] += 1
            summary["error_classes"].append(exc.error_class.value)
            log.warning("Gemini hatası: %s", exc.error_class.value)
            _requeue(cluster, pool)
            if exc.error_class == ErrorClass.RATE_LIMIT_QUOTA:
                blocked_until = now + timedelta(minutes=settings.gemini_quota_cooldown_minutes)
                state["gemini_quota_blocked_until"] = iso(blocked_until)
            elif exc.error_class == ErrorClass.AUTH_PERMISSION:
                blocked_until = now + timedelta(minutes=settings.gemini_quota_cooldown_minutes)
                state["gemini_quota_blocked_until"] = iso(blocked_until)
                _alert(state, settings, telegram, secrets.admin_chat_id, "GEMINI_AUTH", exc.error_class.value,
                       "Gemini anahtarı/model erişimi reddedildi. GEMINI_MODEL ve anahtarı kontrol edin. "
                       "Ücretli modele otomatik geçiş yapılmaz.", now, summary)
            continue

        outcome = validate_generated(raw, cluster, a, settings)
        sources_meta = []
        for i in sorted(cluster, key=lambda x: {"OFFICIAL": 0, "ESTABLISHED_MEDIA": 1}.get(x.trust_class, 2)):
            if i.url not in {s["url"] for s in sources_meta}:
                sources_meta.append({"name": i.source_name, "url": i.url, "source_id": i.source_id})
        post = {
            "content_id": a.primary.id,
            "label": a.label.value,
            "label_text": LABEL_TEXT[a.label],
            "category": outcome.content.category if outcome.content else None,
            "title_style": outcome.content.title_style if outcome.content else None,
            "title_tr": outcome.content.title_tr if outcome.content else None,
            "source_strength": a.source_strength,
            "editorial_priority": a.editorial_priority,
            "publish_reason": a.reason,
            "independent_origins": a.independent_origins,
            "source_urls": [s["url"] for s in sources_meta],
            "source_titles": [i.title for i in cluster],
            "content_hashes": sorted({i.content_hash for i in cluster}),
            "measurement_status": "PENDING",
            "metrics": {"views": "unavailable", "forwards": "unavailable", "reaction_snapshots": []},
        }
        if not outcome.ok:
            if outcome.error_class:
                summary["error_classes"].append(outcome.error_class)
                summary["gemini_errors"] += 1
            post.update({"publish_status": outcome.status, "publish_error": outcome.reason, "created_at": iso(now),
                         "measurement_status": "UNAVAILABLE"})
            history["posts"].append(post)
            _retire(cluster, pool, seen, outcome.status)
            summary["review_held" if outcome.status == "REVIEW_HELD" else "rejected"] += 1
            continue

        if settings.verify_source_urls:
            bad = None
            for s in sources_meta[:3]:
                ok, info = verifier(s["url"], domains_by_source.get(s["source_id"], []))
                if not ok:
                    bad = f"{s['source_id']}: {info}"
                    break
            if bad:
                post.update({"publish_status": "REJECTED", "publish_error": f"URL doğrulanamadı ({bad})",
                             "created_at": iso(now), "measurement_status": "UNAVAILABLE"})
                history["posts"].append(post)
                _retire(cluster, pool, seen, "REJECTED")
                summary["rejected"] += 1
                continue

        text = render_post(outcome.content, a.label, sources_meta, settings, now)
        status = publish_post(post=post, text=text, history=history, chat_id=secrets.telegram_chat_id,
                              telegram=telegram, persist=persist, now=now)
        if status in ("PUBLISHED", "UNCERTAIN", "SKIPPED_DUPLICATE"):
            _retire(cluster, pool, seen, "USED")
            if status == "PUBLISHED":
                summary["published"] += 1
                remaining -= 1
            elif status == "UNCERTAIN":
                summary["uncertain"] += 1
                remaining -= 1
                summary["error_classes"].append(ErrorClass.TELEGRAM_API_ERROR.value)
        else:  # FAILED / REJECTED: Telegram açıkça reddetti -> sonraki çalışmada yeniden değerlendirilebilir
            summary["error_classes"].append(ErrorClass.TELEGRAM_API_ERROR.value)
            if post.get("publish_status") == "FAILED" and "AUTH" in str(post.get("publish_error")):
                _alert(state, settings, telegram, secrets.admin_chat_id, "TELEGRAM_AUTH",
                       ErrorClass.AUTH_PERMISSION.value, "Kanala gönderim yetkisi reddedildi.", now, summary)
            failures = sum(1 for p in history["posts"] if p.get("content_id") == post["content_id"]
                           and p.get("publish_status") == "FAILED")
            if failures >= 2:  # sonsuz yeniden deneme ve kota israfı yok
                _retire(cluster, pool, seen, "FAILED")
            else:
                _requeue(cluster, pool)


def _retire(cluster, pool, seen, status: str) -> None:
    for i in cluster:
        pool.pop(i.id, None)
        if i.id in seen:
            seen[i.id]["status"] = status


def _requeue(cluster, pool) -> None:
    for i in cluster:
        if i.id in pool:
            pool[i.id]["needs_eval"] = True


def _finish(summary: dict) -> dict:
    summary["finished_at"] = iso(utcnow())
    summary["error_classes"] = sorted(set(summary["error_classes"]))
    return summary


def main() -> int:
    t0 = time.monotonic()
    try:
        code, summary = run()
    except Exception as exc:  # beklenmeyen hata: secret içermeyen kısa log
        logging.getLogger("gta6bot").error("UNEXPECTED_ERROR: %s", redact(f"{type(exc).__name__}: {exc}"))
        print(json.dumps({"error_classes": [ErrorClass.UNEXPECTED_ERROR.value]}, ensure_ascii=False))
        return 3
    summary["duration_seconds"] = round(time.monotonic() - t0, 2)
    print(redact(json.dumps(summary, ensure_ascii=False, indent=2)))
    return code


if __name__ == "__main__":
    sys.exit(main())

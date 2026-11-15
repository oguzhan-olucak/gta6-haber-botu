"""Tek çalışma (GitHub Actions her ~20 dakikada bir çağırır).

Sıra: ayar doğrulama → veri dosyaları (bozuksa son sağlam kopyadan otomatik kurtarma, o da
yoksa güvenli mod) → secret kontrolü → reaksiyon güncellemeleri → [paused değilse] toplama →
olay kümeleme/tekrar → deterministik değerlendirme → Gemini (limitli) → çıktı doğrulama →
idempotent yayın → analiz → sağlık/alarmlar → yönetici özeti → saklama sınırları → atomik kayıt
→ JSON çalışma özeti.

Çıkış kodları: 0 normal, 1 yapılandırma/secret eksik, 2 güvenli mod (kurtarılamayan bozuk veri),
3 beklenmeyen hata.
"""
from __future__ import annotations

import json
import logging
import sys
import time
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Mapping, Sequence

import requests

from . import ErrorClass, iso, parse_iso, utcnow
from .analyzer import ALLOWED_UPDATES, analyze, apply_updates, update_measurement_status
from .collector import Item, Verifier, collect, verify_source_url
from .config import (
    CONFIG_DIR,
    DATA_DIR,
    ConfigError,
    Secrets,
    Settings,
    Source,
    load_secrets,
    load_settings,
    load_sources,
    redact,
    setup_logging,
)
from .gemini import (
    RESPONSE_JSON_SCHEMA,
    SYSTEM_INSTRUCTION,
    GeminiError,
    GeminiGenerator,
    Generator,
    ValidationOutcome,
    build_prompt,
    load_style_hints,
    validate_generated,
)
from .labels import LABEL_TEXT, Assessment
from .processor import assess, cluster_items, is_duplicate_of_history
from .publisher import (
    due_digest_key,
    mark_alert,
    mark_digest_sent,
    minutes_since_last_post,
    posts_today,
    publish_post,
    render_alert,
    render_digest,
    render_post,
    send_admin,
    should_alert,
)
from .storage import (
    CorruptDataError,
    FileLock,
    LockError,
    default_history,
    default_insights,
    default_state,
    read_json_recovering,
    validate_history_shape,
    validate_state_shape,
    write_if_changed,
    write_json_atomic,
)
from .telegram_client import MessageSender, TelegramClient, TelegramError

__all__ = ["run", "main", "ErrorClass", "TelegramError", "load_secrets"]

log = logging.getLogger("gta6bot")


@dataclass
class RunContext:
    """Bir çalışmanın paylaşılan durumu (fonksiyonlar arasında açık bağımlılık)."""
    settings: Settings
    sources: list[Source]
    now: datetime
    data_dir: Path
    state: dict[str, Any]
    history: dict[str, Any]
    summary: dict[str, Any]
    telegram: MessageSender | None = None
    secrets: Secrets | None = None
    session: requests.Session | None = None
    generator: Generator | None = None
    verifier: Verifier | None = None
    safe_mode: bool = False
    gemini_blocked_until: datetime | None = None
    remaining_posts: int = 0
    started_mono: float = field(default_factory=time.monotonic)
    style_hints: dict[str, list[str]] = field(default_factory=dict)

    @property
    def state_path(self) -> Path:
        """data/state.json yolu."""
        return self.data_dir / "state.json"

    @property
    def history_path(self) -> Path:
        """data/history.json yolu."""
        return self.data_dir / "history.json"

    @property
    def insights_path(self) -> Path:
        """data/insights.json yolu."""
        return self.data_dir / "insights.json"

    @property
    def admin(self) -> str | None:
        """Yönetici sohbet kimliği (tanımlı değilse None)."""
        return self.secrets.admin_chat_id if self.secrets else None

    def persist_history(self) -> None:
        """history.json'u (ve son sağlam kopyasını) hemen atomik yazar."""
        write_json_atomic(self.history_path, self.history, keep_last_good=True)

    def alert(self, key: str, error_class: str, detail: str) -> None:
        """Tekilleştirilmiş yönetici uyarısı (aynı anahtar ``alert_dedup_hours`` içinde bir kez)."""
        if should_alert(self.state, key, self.settings, self.now):
            sent = send_admin(self.telegram, self.admin, render_alert(error_class, detail, self.settings, self.now))
            mark_alert(self.state, key, self.now)
            self.summary["notes"].append(f"alarm:{key}:{'gönderildi' if sent else 'log'}")


def _new_summary(now: datetime) -> dict[str, Any]:
    return {
        "started_at": iso(now), "finished_at": None, "paused": False, "safe_mode": False, "recovered": [],
        "sources_checked": 0, "sources_ok": 0, "new_items": 0, "duplicates_or_filtered": 0,
        "held": 0, "rejected": 0, "gemini_calls": 0, "gemini_errors": 0, "published": 0,
        "review_held": 0, "uncertain": 0, "measurements_updated": 0, "measurements_pending": 0,
        "reaction_updates": 0, "daily_limit_reached": False, "error_classes": [], "notes": [],
    }


# ---- Giriş noktası ---------------------------------------------------------------------

def run(*, now: datetime | None = None, env: Mapping[str, str] | None = None,
        session: requests.Session | None = None, telegram: MessageSender | None = None,
        generator: Generator | None = None, data_dir: Path | None = None, config_dir: Path | None = None,
        url_verifier: Verifier | None = None) -> tuple[int, dict[str, Any]]:
    """Bir çalışmayı yürütür. Tüm dış bağımlılıklar test için enjekte edilebilir."""
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


def _load_data(summary: dict[str, Any], data_dir: Path) -> tuple[
        dict[str, Any] | None, dict[str, Any], bool]:
    """state/history yükler; bozuksa son sağlam kopyadan kurtarır. (state, history, safe_mode)."""
    try:
        state, err = read_json_recovering(data_dir / "state.json", default_state, validator=validate_state_shape)
        if err:
            summary["recovered"].append("state.json")
            summary["notes"].append(f"state.json bozuktu ({err.reason}); son sağlam kopyadan kurtarıldı")
    except CorruptDataError as exc:
        summary["safe_mode"] = True
        summary["error_classes"].append(ErrorClass.DATA_SCHEMA_ERROR.value)
        summary["notes"].append(f"{exc} — yedek: {exc.backup.name if exc.backup else '-'}; GÜVENLİ MOD")
        log.error("state.json bozuk ve kurtarılamadı; güvenli mod. İnsan müdahalesi gerekli.")
        return None, {"posts": []}, True
    for k, v in default_state().items():
        state.setdefault(k, v)
    state.setdefault("candidate_pool", {})
    try:
        history, err = read_json_recovering(data_dir / "history.json", default_history,
                                            validator=validate_history_shape)
        if err:
            summary["recovered"].append("history.json")
            summary["notes"].append(f"history.json bozuktu ({err.reason}); son sağlam kopyadan kurtarıldı")
        return state, history, False
    except CorruptDataError as exc:
        summary["safe_mode"] = True
        summary["error_classes"].append(ErrorClass.DATA_SCHEMA_ERROR.value)
        summary["notes"].append(f"{exc}; yayın ve Gemini devre dışı (GÜVENLİ MOD)")
        return state, {"posts": []}, True


def _run_locked(settings: Settings, sources: list[Source], now: datetime, env: Mapping[str, str] | None,
                session: requests.Session | None, telegram: MessageSender | None, generator: Generator | None,
                data_dir: Path, summary: dict[str, Any], url_verifier: Verifier | None) -> tuple[int, dict[str, Any]]:
    state, history, safe_mode = _load_data(summary, data_dir)
    if state is None:
        return 2, _finish(summary)
    ctx = RunContext(settings, sources, now, data_dir, state, history, summary, safe_mode=safe_mode)

    secrets, missing = load_secrets(env)
    if secrets is None:
        summary["error_classes"].append(ErrorClass.AUTH_PERMISSION.value)
        summary["notes"].append("Eksik ortam değişkeni: " + ", ".join(missing))
        log.error("Eksik ortam değişkenleri: %s", ", ".join(missing))
        state["last_run_at"] = iso(now)
        write_if_changed(ctx.state_path, state)
        return 1, _finish(summary)

    ctx.secrets = secrets
    ctx.session = session or requests.Session()
    ctx.telegram = telegram or TelegramClient(secrets.telegram_bot_token, session=ctx.session,
                                              timeout=settings.http_timeout_seconds,
                                              max_retries=settings.http_max_retries)
    ctx.generator = generator
    ctx.verifier = url_verifier or _default_verifier(ctx.session, settings)
    state["first_run_at"] = state.get("first_run_at") or iso(now)

    if safe_mode:
        ctx.alert("SAFE_MODE_HISTORY", ErrorClass.DATA_SCHEMA_ERROR.value,
                  "history.json bozuk ve son sağlam kopya yok/bozuk; yayın durduruldu. Yedekten geri yükleyin.")
    if summary["recovered"]:
        ctx.alert("DATA_RECOVERED", ErrorClass.DATA_SCHEMA_ERROR.value,
                  "Bozuk veri dosyası son sağlam kopyadan otomatik kurtarıldı: " + ", ".join(summary["recovered"]))
    if not safe_mode:
        _poll_reactions(ctx)
    if settings.paused:
        summary["paused"] = True
        summary["notes"].append("paused=true: toplama, Gemini ve yayın atlandı")
    elif not safe_mode:
        _content_pipeline(ctx)
    insights = analyze(history, settings, now) if not safe_mode else default_insights()
    if not safe_mode:
        write_if_changed(ctx.insights_path, insights)
    _health_checks(ctx)
    _maybe_digest(ctx, insights)
    _save(ctx)
    return (2 if safe_mode else 0), _finish(summary)


def _default_verifier(session: requests.Session, settings: Settings) -> Verifier:
    def verifier(url: str, allowed: Sequence[str], hop_domains: Sequence[str]) -> tuple[bool, str]:
        """Gerçek ağ üzerinden SSRF korumalı URL doğrulaması."""
        return verify_source_url(url, allowed, session, settings, hop_domains=hop_domains)
    return verifier


# ---- Adımlar -------------------------------------------------------------------------------

def _poll_reactions(ctx: RunContext) -> None:
    """getUpdates ile reaksiyon sayılarını alır (paused iken de çalışır)."""
    assert ctx.telegram is not None
    try:
        updates = ctx.telegram.get_updates(ctx.state.get("telegram_update_offset"), ALLOWED_UPDATES)
        ctx.summary["reaction_updates"] = apply_updates(updates, ctx.history, ctx.state)["matched"]
    except TelegramError as exc:
        ctx.summary["error_classes"].append(exc.error_class.value)
        if exc.error_class == ErrorClass.AUTH_PERMISSION:
            ctx.alert("TELEGRAM_AUTH", exc.error_class.value, "Telegram token veya bot yetkisi reddedildi (401/403).")
        elif exc.status == 409:
            ctx.alert("TELEGRAM_WEBHOOK", exc.error_class.value,
                      "getUpdates 409: botta webhook ayarlı olabilir. deleteWebhook gerekli.")
    mc = update_measurement_status(ctx.history, ctx.state, ctx.settings, ctx.now)
    ctx.summary["measurements_updated"] = mc["updated"]
    ctx.summary["measurements_pending"] = mc["PENDING"] + mc["PARTIAL"]


def _ingest(ctx: RunContext) -> None:
    """Kaynakları toplar, yeni öğeleri aday havuzuna ekler."""
    result = collect(ctx.sources, ctx.settings, ctx.session, ctx.now, verifier=ctx.verifier,
                     deadline_at=ctx.started_mono + ctx.settings.run_deadline_seconds,
                     known_ids=frozenset(ctx.state.get("seen_items", {})))
    ctx.summary["sources_checked"], ctx.summary["sources_ok"] = result.sources_checked, result.sources_ok
    ctx.summary["error_classes"].extend(result.errors)
    ctx.summary["duplicates_or_filtered"] += result.known_skipped
    ctx.state.setdefault("source_status", {}).update(result.source_status)
    if result.sources_ok > 0:
        ctx.state["last_successful_fetch_at"] = iso(ctx.now)
    seen, pool = ctx.state.setdefault("seen_items", {}), ctx.state.setdefault("candidate_pool", {})
    for it in result.items:
        if it.id in seen:
            ctx.summary["duplicates_or_filtered"] += 1
            continue
        seen[it.id] = {"first_seen": iso(ctx.now), "status": "NEW", "source": it.source_id}
        if it.raw_id and it.raw_id != it.id:  # ham bağlantı (ör. Google News) da görüldü say
            seen[it.raw_id] = {"first_seen": iso(ctx.now), "status": "ALIAS", "source": it.source_id}
        pool[it.id] = {"item": it.to_dict(), "first_seen": iso(ctx.now), "needs_eval": True}
        ctx.summary["new_items"] += 1


def _evaluate(ctx: RunContext) -> list[tuple[list[Item], Assessment]]:
    """Havuzu olay kümelerine ayırır, değerlendirir; adayları öncelik sırasıyla döndürür."""
    pool, seen = ctx.state["candidate_pool"], ctx.state["seen_items"]
    items = [Item(**v["item"]) for v in pool.values()]
    candidates: list[tuple[list[Item], Assessment]] = []
    for cluster in cluster_items(items, ctx.settings.cluster_similarity_threshold, ctx.settings.cluster_max_gap_hours):
        if not any(pool[i.id].get("needs_eval") for i in cluster):
            continue
        for i in cluster:
            pool[i.id]["needs_eval"] = False
        if is_duplicate_of_history(cluster, ctx.history, ctx.settings, ctx.now):
            _retire(cluster, pool, seen, "DUPLICATE")
            ctx.summary["duplicates_or_filtered"] += len(cluster)
            continue
        a = assess(cluster, ctx.settings, ctx.now)
        if a.decision == "REJECT":
            _retire(cluster, pool, seen, "REJECTED")
            ctx.summary["rejected"] += 1
            ctx.summary["notes"].append(f"red: {a.reason}"[:160])
        elif a.decision == "HOLD":
            for i in cluster:
                seen[i.id]["status"] = "HELD"
            ctx.summary["held"] += 1
        else:
            candidates.append((cluster, a))
    candidates.sort(key=lambda ca: ca[1].editorial_priority, reverse=True)
    return candidates


def _blocked_reason(ctx: RunContext) -> str | None:
    """Bu çalışmada yeni bir Gemini çağrısı/yayın yapılamıyorsa nedeni."""
    if ctx.remaining_posts <= 0:
        ctx.summary["daily_limit_reached"] = True
        return "günlük limit"
    if time.monotonic() - ctx.started_mono > ctx.settings.run_deadline_seconds:
        return "çalışma süresi sınırı"
    since = minutes_since_last_post(ctx.history, ctx.now)
    if since is not None and since < ctx.settings.min_minutes_between_posts:
        return "gönderiler arası minimum süre bekleniyor"
    if ctx.gemini_blocked_until and ctx.now < ctx.gemini_blocked_until:
        return "Gemini kotası soğuma süresinde"
    if ctx.summary["gemini_calls"] >= ctx.settings.max_gemini_calls_per_run:
        return "çalışma başına Gemini limiti"
    return None


def _content_pipeline(ctx: RunContext) -> None:
    """Toplama → değerlendirme → üretim → yayın."""
    assert ctx.secrets is not None
    _ingest(ctx)
    candidates = _evaluate(ctx)
    ctx.remaining_posts = ctx.settings.max_daily_posts - posts_today(ctx.history, ctx.now, ctx.settings)
    ctx.gemini_blocked_until = parse_iso(ctx.state.get("gemini_quota_blocked_until"))
    ctx.style_hints = load_style_hints(ctx.insights_path)
    if ctx.generator is None:
        ctx.generator = GeminiGenerator(ctx.secrets.gemini_api_key, ctx.secrets.gemini_model)
    pool = ctx.state["candidate_pool"]
    for cluster, a in candidates:
        reason = _blocked_reason(ctx)
        if reason:
            if reason not in ctx.summary["notes"]:
                ctx.summary["notes"].append(reason)
            _requeue(cluster, pool)
            continue
        _generate_and_publish(ctx, cluster, a)


def _call_gemini(ctx: RunContext, cluster: list[Item], a: Assessment) -> str | None:
    """Tek Gemini çağrısı; hata sınıfına göre soğuma/alarm. Başarısızsa None."""
    assert ctx.generator is not None and ctx.secrets is not None
    ctx.summary["gemini_calls"] += 1
    try:
        return ctx.generator.generate(SYSTEM_INSTRUCTION, build_prompt(a.items or cluster, a, ctx.style_hints,
                                                                       ctx.settings), RESPONSE_JSON_SCHEMA)
    except GeminiError as exc:
        ctx.summary["gemini_errors"] += 1
        ctx.summary["error_classes"].append(exc.error_class.value)
        log.warning("Gemini hatası: %s", exc.error_class.value)
        _requeue(cluster, ctx.state["candidate_pool"])
        if exc.error_class in (ErrorClass.RATE_LIMIT_QUOTA, ErrorClass.AUTH_PERMISSION):
            ctx.gemini_blocked_until = ctx.now + timedelta(minutes=ctx.settings.gemini_quota_cooldown_minutes)
            ctx.state["gemini_quota_blocked_until"] = iso(ctx.gemini_blocked_until)
        if exc.error_class == ErrorClass.AUTH_PERMISSION:
            ctx.alert("GEMINI_AUTH", exc.error_class.value,
                      "Gemini anahtarı/model erişimi reddedildi. GEMINI_MODEL ve anahtarı kontrol edin. "
                      "Ücretli modele otomatik geçiş yapılmaz.")
        return None


def _sources_meta(items: list[Item]) -> list[dict[str, str]]:
    """Gösterilecek kaynaklar: önce resmî, sonra medya; URL başına bir kez."""
    out: list[dict[str, str]] = []
    rank = {"OFFICIAL": 0, "ESTABLISHED_MEDIA": 1}
    for i in sorted(items, key=lambda x: rank.get(x.trust_class, 2)):
        if i.url not in {s["url"] for s in out}:
            out.append({"name": i.source_name, "url": i.url, "source_id": i.source_id})
    return out


def _post_record(a: Assessment, cluster: list[Item], outcome: ValidationOutcome,
                 sources_meta: list[dict[str, str]]) -> dict[str, Any]:
    assert a.label is not None and a.primary is not None
    c = outcome.content
    return {
        "content_id": a.primary.id, "label": a.label.value, "label_text": LABEL_TEXT[a.label],
        "category": c.category if c else None, "title_style": c.title_style if c else None,
        "title_tr": c.title_tr if c else None, "source_strength": a.source_strength,
        "editorial_priority": a.editorial_priority, "publish_reason": a.reason,
        "independent_origins": a.independent_origins, "source_urls": [s["url"] for s in sources_meta],
        "source_titles": [i.title for i in cluster], "content_hashes": sorted({i.content_hash for i in cluster}),
        "measurement_status": "PENDING",
        "metrics": {"views": "unavailable", "forwards": "unavailable", "reaction_snapshots": []},
    }


def _record_failure(ctx: RunContext, post: dict[str, Any], cluster: list[Item], status: str, reason: str) -> None:
    post.update({"publish_status": status, "publish_error": reason, "created_at": iso(ctx.now),
                 "measurement_status": "UNAVAILABLE"})
    ctx.history["posts"].append(post)
    _retire(cluster, ctx.state["candidate_pool"], ctx.state["seen_items"], status)
    ctx.summary["review_held" if status == "REVIEW_HELD" else "rejected"] += 1


def _verify_urls(ctx: RunContext, sources_meta: list[dict[str, str]]) -> str | None:
    """Yayın öncesi kaynak URL doğrulaması; sorun varsa açıklama döner."""
    if not ctx.settings.verify_source_urls or ctx.verifier is None:
        return None
    domains = {s.id: s.allowed_domains for s in ctx.sources}
    for s in sources_meta[:3]:
        ok, info = ctx.verifier(s["url"], domains.get(s["source_id"], []), [])
        if not ok:
            return f"{s['source_id']}: {info}"
    return None


def _generate_and_publish(ctx: RunContext, cluster: list[Item], a: Assessment) -> None:
    """Bir aday kümeyi üretir, doğrular ve yayınlar."""
    assert ctx.secrets is not None and ctx.telegram is not None and a.label is not None
    raw = _call_gemini(ctx, cluster, a)
    if raw is None:
        return
    used = a.items or cluster
    outcome = validate_generated(raw, used, a, ctx.settings)
    sources_meta = _sources_meta(used)
    post = _post_record(a, cluster, outcome, sources_meta)
    if not outcome.ok or outcome.content is None:
        if outcome.error_class:
            ctx.summary["error_classes"].append(outcome.error_class)
            ctx.summary["gemini_errors"] += 1
        _record_failure(ctx, post, cluster, outcome.status, outcome.reason)
        return
    bad = _verify_urls(ctx, sources_meta)
    if bad:
        _record_failure(ctx, post, cluster, "REJECTED", f"URL doğrulanamadı ({bad})")
        return
    text = render_post(outcome.content, a.label, sources_meta, ctx.settings, ctx.now,
                       independent_count=len(a.independent_origins))
    status = publish_post(post=post, text=text, history=ctx.history, chat_id=ctx.secrets.telegram_chat_id,
                          telegram=ctx.telegram, persist=ctx.persist_history, now=ctx.now)
    _after_publish(ctx, cluster, post, status)


def _after_publish(ctx: RunContext, cluster: list[Item], post: dict[str, Any], status: str) -> None:
    pool, seen = ctx.state["candidate_pool"], ctx.state["seen_items"]
    if status in ("PUBLISHED", "UNCERTAIN", "SKIPPED_DUPLICATE"):
        _retire(cluster, pool, seen, "USED")
        if status == "PUBLISHED":
            ctx.summary["published"] += 1
            ctx.remaining_posts -= 1
        elif status == "UNCERTAIN":
            ctx.summary["uncertain"] += 1
            ctx.remaining_posts -= 1
            ctx.summary["error_classes"].append(ErrorClass.TELEGRAM_API_ERROR.value)
        return
    ctx.summary["error_classes"].append(ErrorClass.TELEGRAM_API_ERROR.value)
    if post.get("publish_status") == "FAILED" and "AUTH" in str(post.get("publish_error")):
        ctx.alert("TELEGRAM_AUTH", ErrorClass.AUTH_PERMISSION.value, "Kanala gönderim yetkisi reddedildi.")
    failures = sum(1 for p in ctx.history["posts"] if p.get("content_id") == post["content_id"]
                   and p.get("publish_status") == "FAILED")
    if failures >= 2:  # sonsuz yeniden deneme ve kota israfı yok
        _retire(cluster, pool, seen, "FAILED")
    else:
        _requeue(cluster, pool)


def _health_checks(ctx: RunContext) -> None:
    """24 saat veri yok ve kalıcı kaynak yetki hataları için tekilleştirilmiş uyarı."""
    last_ok = (parse_iso(ctx.state.get("last_successful_fetch_at")) or parse_iso(ctx.state.get("first_run_at"))
               or ctx.now)
    if not ctx.settings.paused and ctx.now - last_ok >= timedelta(hours=ctx.settings.health_alert_hours):
        ctx.alert("NO_DATA_24H", ErrorClass.NETWORK_TRANSIENT.value,
                  f"{ctx.settings.health_alert_hours} saattir hiçbir kaynaktan veri alınamadı.")
    for sid, st in ctx.state.get("source_status", {}).items():
        if st.get("error_class") == ErrorClass.AUTH_PERMISSION.value:
            ctx.alert(f"SOURCE_AUTH_{sid}", ErrorClass.AUTH_PERMISSION.value, f"Kaynak {sid} 401/403 döndürüyor.")


def _maybe_digest(ctx: RunContext, insights: dict[str, Any]) -> None:
    key = due_digest_key(ctx.settings, ctx.state, ctx.now)
    if key:
        send_admin(ctx.telegram, ctx.admin, render_digest(ctx.summary, ctx.history, insights, ctx.settings, ctx.now))
        mark_digest_sent(ctx.state, key)  # admin yoksa da işaretle: aynı pencerede tekrar denenmez
        ctx.summary["notes"].append(f"özet:{key}")


def _save(ctx: RunContext) -> None:
    ctx.state["last_run_at"] = iso(ctx.now)
    _prune(ctx.state, ctx.history, ctx.settings, ctx.now)
    ctx.state["run_log"].append({k: ctx.summary[k] for k in ("started_at", "sources_ok", "new_items", "published",
                                                              "gemini_calls", "error_classes")})
    if not ctx.safe_mode:
        write_if_changed(ctx.history_path, ctx.history, keep_last_good=True)
    if state_needs_write(ctx.state_path, ctx.state, ctx.now, ctx.settings.state_heartbeat_minutes):
        ctx.state["persisted_at"] = iso(ctx.now)
        write_if_changed(ctx.state_path, ctx.state, keep_last_good=True)


VOLATILE_STATE_KEYS = frozenset({"last_run_at", "run_log", "source_status", "last_successful_fetch_at",
                                 "persisted_at"})


def state_needs_write(path: Path, state: dict[str, Any], now: datetime, heartbeat_minutes: int) -> bool:
    """Yalnızca oynak alanlar değiştiyse state en fazla ``heartbeat_minutes`` dakikada bir yazılır
    (commit gürültüsünü ~3 kat azaltır). Kalıcı alanlarda (seen_items, havuz, özet/alarm kayıtları,
    offset...) herhangi bir değişiklik varsa hemen yazılır."""
    try:
        old = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return True
    if not isinstance(old, dict):
        return True

    def stable(d: dict[str, Any]) -> dict[str, Any]:
        return {k: v for k, v in d.items() if k not in VOLATILE_STATE_KEYS}

    if stable(old) != stable(state):
        return True
    last = parse_iso(old.get("persisted_at"))
    return last is None or now - last >= timedelta(minutes=heartbeat_minutes)


def _prune(state: dict[str, Any], history: dict[str, Any], settings: Settings, now: datetime) -> None:
    """Saklama sınırları: seen_items, aday havuzu, geçmiş ve çalışma günlüğü."""
    r = settings.retention_limits
    cutoff = now - timedelta(hours=max(r.seen_items_max_age_hours, settings.max_item_age_hours + 24))
    seen = {k: v for k, v in state.get("seen_items", {}).items() if (parse_iso(v.get("first_seen")) or now) >= cutoff}
    if len(seen) > r.seen_items_max_records:
        seen = dict(sorted(seen.items(), key=lambda kv: kv[1].get("first_seen") or "")[-r.seen_items_max_records:])
    state["seen_items"] = seen
    pool_cutoff = now - timedelta(hours=settings.max_item_age_hours)

    def pool_time(v: dict[str, Any]) -> datetime:
        return parse_iso(v["item"].get("published_at")) or parse_iso(v.get("first_seen")) or now

    fresh = {k: v for k, v in state.get("candidate_pool", {}).items() if pool_time(v) >= pool_cutoff}
    if len(fresh) > r.candidate_pool_max_records:  # en yeniler kalır; state.json şişmez
        fresh = dict(sorted(fresh.items(), key=lambda kv: pool_time(kv[1]), reverse=True)[:r.candidate_pool_max_records])
    state["candidate_pool"] = fresh
    hist_cutoff = now - timedelta(days=r.history_max_age_days)
    posts = [p for p in history.get("posts", [])
             if (parse_iso(p.get("published_at") or p.get("created_at")) or now) >= hist_cutoff]
    history["posts"] = posts[-r.history_max_records:]
    state["run_log"] = state.get("run_log", [])[-r.run_log_max_records:]


def _retire(cluster: list[Item], pool: dict[str, Any], seen: dict[str, Any], status: str) -> None:
    for i in cluster:
        pool.pop(i.id, None)
        if i.id in seen:
            seen[i.id]["status"] = status


def _requeue(cluster: list[Item], pool: dict[str, Any]) -> None:
    for i in cluster:
        if i.id in pool:
            pool[i.id]["needs_eval"] = True


def _finish(summary: dict[str, Any]) -> dict[str, Any]:
    summary["finished_at"] = iso(utcnow())
    summary["error_classes"] = sorted(set(summary["error_classes"]))
    return summary


def main() -> int:
    """CLI giriş noktası: ``python -m bot.main``."""
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

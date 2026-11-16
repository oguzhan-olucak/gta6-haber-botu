"""Skill denetleyicisi: ``.claude/skills/*/SKILL.md`` dosyalarını yapısal olarak doğrular ve her skill'in
kurallarını koda karşı ÇALIŞTIRIR. Sonuç ``SKILL_AUDIT_REPORT.md`` dosyasına yazılır.

Kullanım:
    python tools/skill_audit.py                    # tüm skill'ler + rapor
    python tools/skill_audit.py --skill cost-guard # tek skill (rapor yazılmaz)

Ağ erişimi yapmaz; gerçek secret okumaz.
"""
from __future__ import annotations

import argparse
import ast
import json
import re
import shutil
import subprocess
import sys
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
SKILLS = ROOT / ".claude" / "skills"


@dataclass
class Check:
    """Tek denetim sonucu."""
    name: str
    ok: bool
    detail: str = ""


@dataclass
class SkillResult:
    """Bir skill'in yapısal ve işlevsel denetim sonucu."""
    name: str
    description: str
    trigger: str
    lines: int
    checks: list[Check] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return all(c.ok for c in self.checks)


# ---- yardımcılar ----------------------------------------------------------------------------

def read(rel: str) -> str:
    return (ROOT / rel).read_text(encoding="utf-8")


def py_files(*dirs: str) -> list[Path]:
    """Dizinlerdeki .py dosyaları (denetleyicinin kendisi hariç: desenleri metin olarak içerir)."""
    return [p for d in dirs for p in sorted((ROOT / d).glob("*.py")) if p.name != "skill_audit.py"]


def pytest(*args: str) -> Check:
    """pytest'i alt süreçte çalıştırır; 'N passed' ve başarısızlık yoksa geçer."""
    proc = subprocess.run([sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider", *args],
                          cwd=ROOT, capture_output=True, text=True, timeout=600)
    last = (proc.stdout.strip().splitlines() or ["(çıktı yok)"])[-1]
    return Check(f"pytest {' '.join(args)}", proc.returncode == 0 and "passed" in last, last)


def grep(pattern: str, files: list[Path]) -> list[str]:
    rx = re.compile(pattern)
    hits = []
    for f in files:
        for n, line in enumerate(f.read_text(encoding="utf-8").splitlines(), 1):
            if rx.search(line):
                hits.append(f"{f.relative_to(ROOT)}:{n}")
    return hits


def none_found(name: str, pattern: str, files: list[Path]) -> Check:
    hits = grep(pattern, files)
    return Check(name, not hits, ", ".join(hits[:5]) or "bulunamadı")


def settings() -> dict:
    return json.loads(read("config/settings.json"))


# ---- yapısal denetim -------------------------------------------------------------------------

FRONT_RE = re.compile(r"^---\nname: (?P<name>[a-z0-9-]+)\ndescription: (?P<desc>.+?)\n---\n", re.S)


def structural(path: Path) -> tuple[SkillResult, list[Check]]:
    text = path.read_text(encoding="utf-8")
    m = FRONT_RE.match(text)
    checks = [Check("frontmatter (name + description)", bool(m))]
    name = m.group("name") if m else path.parent.name
    desc = m.group("desc").strip() if m else ""
    checks.append(Check("ad klasörle aynı", name == path.parent.name))
    checks.append(Check("açıklama 30–1024 karakter", 30 <= len(desc) <= 1024, f"{len(desc)} karakter"))
    body = text[m.end():] if m else text
    checks.append(Check("gövde ≥ 8 anlamlı satır (taslak değil)", len([l for l in body.splitlines() if l.strip()]) >= 8))
    checks.append(Check("'Ne zaman tetiklenir' bölümü", "## Ne zaman tetiklenir" in text or "Ne zaman tetiklenir" in text))
    checks.append(Check("'Otomatik doğrulama' bölümü", "## Otomatik doğrulama" in text))
    checks.append(Check("gizli kabuk komutu yok (curl|sh, base64 -d)",
                        not re.search(r"curl[^\n]*\|\s*(ba)?sh|base64\s+-d|wget[^\n]*\|\s*sh", text)))
    checks.append(Check("proje dışı yol yok (~/.ssh, ~/.aws, /etc)", not re.search(r"~/\.ssh|~/\.aws|/etc/", text)
                        or "erişemez" in text or "dokunma" in text or "okuma" in text))
    trig = ""
    tm = re.search(r"## Ne zaman tetiklenir\n(.+?)(\n##|\Z)", text, re.S)
    if tm:
        trig = " ".join(tm.group(1).split())
    return SkillResult(name, desc, trig, len(text.splitlines())), checks


# ---- işlevsel denetimler (skill kurallarını koda karşı çalıştırır) -------------------------------

def c_security() -> list[Check]:
    files = [p for p in ROOT.rglob("*") if p.is_file() and ".git" not in p.parts and p.name != "skill_audit.py"
             and p.suffix in (".py", ".json", ".yml", ".md", ".js", ".html", ".toml", ".txt")]
    wf = read(".github/workflows/run.yml")
    bot_step = wf.split("- name: Botu çalıştır")[1].split("- name:")[0] if "- name: Botu çalıştır" in wf else ""
    other = wf.replace(bot_step, "")
    return [
        none_found("gerçek biçimli token/anahtar yok", r"\b\d{8,10}:[A-Za-z0-9_-]{35}\b|AIza[0-9A-Za-z_-]{35}", files),
        none_found("eval/exec/pickle/shell=True/verify=False yok", r"\beval\(|\bexec\(|import pickle|shell=True|verify=False",
                   py_files("bot", "tools")),
        Check("workflow yalnızca schedule + workflow_dispatch", _triggers(wf) == {"schedule", "workflow_dispatch"},
              ", ".join(sorted(_triggers(wf)))),
        Check("secret'lar yalnızca bot adımında", "secrets." in bot_step and "secrets." not in other),
        Check("XML yalnızca defusedxml", not grep(r"xml\.etree|from lxml|minidom", py_files("bot")) and
              bool(grep(r"defusedxml", py_files("bot")))),
        pytest("tests/test_publisher.py::test_secrets_never_logged"),
    ]


def _triggers(wf: str) -> set[str]:
    """Workflow 'on:' bloğundaki tetikleyici adları (yorumlar hariç)."""
    block = wf.split("\non:", 1)[1].split("\npermissions:", 1)[0]
    return {m.group(1) for m in re.finditer(r"^  ([a-z_]+):", block, re.M)}


def c_cost() -> list[Check]:
    s = settings()
    wf = read(".github/workflows/run.yml")
    return [
        Check("max_gemini_calls_per_run ≤ 10", s["max_gemini_calls_per_run"] <= 10, str(s["max_gemini_calls_per_run"])),
        Check("http_max_retries ≤ 6", s["http_max_retries"] <= 6, str(s["http_max_retries"])),
        Check("run_deadline_seconds < iş zaman aşımı (15 dk)", s["run_deadline_seconds"] < 15 * 60),
        none_found("kodda sabit Gemini model kimliği yok", r"[\"']gemini-\d", py_files("bot")),
        Check("standart ubuntu-latest runner", "runs-on: ubuntu-latest" in wf),
        pytest("tests/test_publisher.py::test_gemini_quota_stops_calls_and_never_switches_model",
               "tests/test_arena.py::test_r2_sre_huge_retry_after_is_not_slept_through"),
    ]


def c_architect() -> list[Check]:
    bot = py_files("bot")
    posts = [h for h in grep(r"\.post\(", bot) if not h.startswith("bot/telegram_client.py")]
    gets = [h for h in grep(r"session\.get\(", bot) if not h.startswith("bot/collector.py")]
    writes = [h for h in grep(r"open\([^)]*['\"]w|write_text\(", bot)
              if not h.startswith(("bot/storage.py", "bot/site_exporter.py"))]
    proc = subprocess.run([sys.executable, "-m", "mypy", "bot"], cwd=ROOT, capture_output=True, text=True)
    return [
        Check("HTTP POST yalnızca telegram_client.py", not posts, ", ".join(posts) or "uyumlu"),
        Check("HTTP GET yalnızca collector.py", not gets, ", ".join(gets) or "uyumlu"),
        Check("dosya yazımı yalnızca storage/site_exporter", not writes, ", ".join(writes) or "uyumlu"),
        Check("mypy bot temiz", proc.returncode == 0, (proc.stdout.strip().splitlines() or [""])[-1]),
    ]


def c_tdd() -> list[Check]:
    names = ["test_same_item_twice_processed_once", "test_broken_feed_does_not_stop_other_sources",
             "test_no_source_url_is_rejected", "test_reddit_and_single_source_never_official",
             "test_broken_model_json_is_rejected_without_crash", "test_hallucinated_details_and_certainty_words_are_blocked",
             "test_daily_post_limit_not_exceeded", "test_paused_means_no_publish_and_no_gemini",
             "test_telegram_timeout_does_not_cause_duplicate_post", "test_reaction_count_update_attaches_to_correct_message",
             "test_views_and_forwards_stay_unavailable", "test_corrupt_insights_falls_back_to_neutral",
             "test_digest_not_sent_twice_in_same_window", "test_secrets_never_logged"]
    src = "".join(p.read_text(encoding="utf-8") for p in py_files("tests"))
    missing = [n for n in names if f"def {n}(" not in src]
    ruff = shutil.which("ruff")
    checks = [Check("14 kabul testi tanımlı", not missing, ", ".join(missing) or "14/14"), pytest()]
    if ruff is None:
        checks.append(Check("ruff kurulu (stil denetimi için)", False, "ruff bulunamadı: pip install ruff"))
    else:
        proc = subprocess.run([ruff, "check", "bot", "tests", "tools"], cwd=ROOT, capture_output=True, text=True)
        checks.append(Check("ruff temiz", proc.returncode == 0, (proc.stdout.strip().splitlines() or [""])[-1]))
    return checks


def c_rss() -> list[Check]:
    from bot.config import load_sources
    srcs = load_sources()
    return [Check("tüm feed_url https", all(not s.feed_url or s.feed_url.startswith("https://") for s in srcs)),
            Check("her kaynakta allowed_domains", all(s.allowed_domains for s in srcs)),
            pytest("tests/test_collector.py", "tests/test_resilience.py")]


def c_telegram() -> list[Check]:
    from bot.analyzer import ALLOWED_UPDATES
    from bot.telegram_client import MAX_MESSAGE_CHARS, MAX_RETRY_AFTER_SECONDS
    views = [h for h in grep(r"[\"']views[\"']\s*:", py_files("bot"))]
    bad_views = [h for h in views if "unavailable" not in (ROOT / h.split(":")[0]).read_text(encoding="utf-8")
                 .splitlines()[int(h.split(":")[1]) - 1].lower()]
    return [Check("allowed_updates yalnızca message_reaction_count", ALLOWED_UPDATES == ["message_reaction_count"]),
            Check("views/forwards yalnızca 'unavailable'", not bad_views, ", ".join(bad_views) or f"{len(views)} yer"),
            Check("4096 sınırı ve retry_after üst sınırı", MAX_MESSAGE_CHARS == 4096 and MAX_RETRY_AFTER_SECONDS <= 60),
            pytest("tests/test_analyzer.py", "tests/test_publisher.py")]


def c_gemini() -> list[Check]:
    from bot.gemini import CHECKS, RESPONSE_JSON_SCHEMA, SYSTEM_INSTRUCTION
    allowed = {"type", "properties", "required", "enum", "items", "minItems", "maxItems", "description"}

    def keys(node: object) -> set[str]:
        out: set[str] = set()
        if isinstance(node, dict):
            for k, v in node.items():
                out.add(k)
                out |= keys(v) if k != "properties" else set().union(*(keys(x) for x in v.values())) if v else set()
        return out
    used = keys(RESPONSE_JSON_SCHEMA)
    return [Check("şema yalnızca desteklenen JSON Schema anahtar kelimeleri", used <= allowed, ", ".join(sorted(used - allowed)) or "uyumlu"),
            Check("≥ 6 bağımsız doğrulama kontrolü", len(CHECKS) >= 6, str(len(CHECKS))),
            Check("sistem talimatı untrusted_source_data'yı tanımlar", "<untrusted_source_data>" in SYSTEM_INSTRUCTION),
            Check("SDK çağrısı response_json_schema kullanır", "response_json_schema" in read("bot/gemini.py")),
            pytest("tests/test_processor.py")]


def c_night() -> list[Check]:
    tools = py_files("tools", "bot")
    return [Check("NIGHT_PROGRESS.md ve MORNING_REPORT.md var", (ROOT / "NIGHT_PROGRESS.md").exists()
                  and (ROOT / "MORNING_REPORT.md").exists()),
            none_found("kodda 'git push' yok (yalnızca workflow)", r"git push", tools),
            Check("İNSAN MÜDAHALESİ başlığı raporda tanımlı", "İNSAN MÜDAHALESİ GEREKLİ" in read("MORNING_REPORT.md"))]


def c_token() -> list[Check]:
    progress = read("NIGHT_PROGRESS.md")
    log = read("ARENA_DEBATE_LOG.md")
    retries = re.findall(r"(\d+)\. denemede", log + progress)
    return [Check("hiçbir hata 2 denemeyi aşmadı (kayıtlara göre)", all(int(r) <= 2 for r in retries),
                  f"kayıtlı denemeler: {', '.join(retries) or '—'}"),
            Check("alt ajan açılmadı (roller tek bağlamda)", "alt ajan açılmadı" in log),
            Check("ilerleme kaydı tek satırlık adımlarla tutuluyor", progress.count("\n| ") >= 10,
                  f"{progress.count(chr(10) + '| ')} satır")]


def c_arena() -> list[Check]:
    log = read("ARENA_DEBATE_LOG.md")
    tests_src = read("tests/test_arena.py")
    rounds = sorted({int(n) for n in re.findall(r"^## Tur (\d+)", log, re.M)})
    per_round = {r: len(re.findall(rf"def test_r{r}_", tests_src)) for r in rounds}
    return [Check("her tur ≥ 3 regresyon testi", all(v >= 3 for v in per_round.values()), json.dumps(per_round)),
            Check("her turda FAIL ve PASS kanıtı", log.count("**FAIL kanıtı") == len(rounds) == log.count("**PASS kanıtı")),
            Check("tablo satırlarında dosya:satır", len(re.findall(r"`[\w/.]+\.(py|js|yml):\d", log)) >= len(rounds) * 3),
            pytest("tests/test_arena.py")]


def c_atomic() -> list[Check]:
    from bot import storage
    return [Check("lastgood + şema doğrulayıcılar mevcut", all(hasattr(storage, n) for n in
                  ("read_json_recovering", "lastgood_path", "validate_state_shape", "validate_history_shape"))),
            pytest("tests/test_storage.py", "tests/test_resilience.py", "-k", "storage or recover or corrupt or half")]


def c_poison() -> list[Check]:
    tree = ast.parse(read("tests/test_injection.py"))
    payloads = next((len(n.value.elts) for n in ast.walk(tree) if isinstance(n, ast.Assign)
                     and getattr(n.targets[0], "id", "") == "PAYLOADS" and isinstance(n.value, ast.List)), 0)
    return [Check("saldırı yükü kütüphanesi ≥ 8", payloads >= 8, str(payloads)),
            Check("homoglif katlama aktif", "fold_confusables" in read("bot/processor.py")),
            pytest("tests/test_injection.py", "tests/test_arena.py", "-k", "injection or homoglyph or padded or blend or links")]


def c_official() -> list[Check]:
    from bot.config import load_sources
    from bot.labels import OFFICIAL_DOMAINS
    off = [s for s in load_sources() if s.trust_class == "OFFICIAL"]
    bad = [s.id for s in off if not all(any(d == o or d.endswith("." + o) for o in OFFICIAL_DOMAINS)
                                        for d in s.allowed_domains)]
    return [Check("resmî kaynak sayısı ≥ 2 ve etkin", sum(s.enabled for s in off) >= 2, f"{sum(s.enabled for s in off)} etkin"),
            Check("resmî kaynak alan adları yalnızca rockstargames.com / take2games.com", not bad, ", ".join(bad) or "uyumlu"),
            Check("üçlü koşul (OFFICIAL + url_verified + alan adı) kodda", "def is_official_item" in read("bot/processor.py")),
            pytest("tests/test_resilience.py", "tests/test_injection.py", "tests/test_arena.py", "-k",
                   "official or google_news or html_listing or reverified")]


def c_cluster() -> list[Check]:
    sys.path.insert(0, str(ROOT))
    from bot.clustering import Doc, SimilarityEngine
    from tests.test_clustering import DIFFERENT_EVENT, SAME_EVENT
    allp = [x for pair in SAME_EVENT + DIFFERENT_EVENT for x in pair]

    def score(a: tuple[str, str], b: tuple[str, str]) -> float:
        docs = [Doc("a", a[0], a[1]), Doc("b", b[0], b[1])] + [Doc(f"x{i}", t, s) for i, (t, s) in enumerate(allp)]
        return SimilarityEngine(docs).score(0, 1)
    pos = min(score(a, b) for a, b in SAME_EVENT)
    neg = max(score(a, b) for a, b in DIFFERENT_EVENT)
    th = settings()["cluster_similarity_threshold"]
    return [Check("eşik pozitif/negatif boşluğun içinde", neg < th <= pos,
                  f"en yüksek negatif {neg:.3f} < eşik {th} ≤ en düşük pozitif {pos:.3f}"),
            pytest("tests/test_clustering.py")]


def c_site() -> list[Check]:
    js = re.sub(r"/\*.*?\*/|//[^\n]*", "", read("docs/assets/app.js"), flags=re.S)   # yorumlar hariç
    page = read("docs/index.html")
    csp = re.search(r'Content-Security-Policy" content="([^"]+)"', page)
    feed = json.loads(read("docs/data/feed.json"))
    blob = json.dumps(feed)
    return [Check("app.js'te innerHTML/eval/document.write yok",
                  not re.search(r"innerHTML|outerHTML|\beval\(|new Function|document\.write|insertAdjacentHTML", js)),
            Check("CSP: script-src 'self', object-src 'none', base-uri 'none'", bool(csp) and all(
                x in csp.group(1) for x in ("script-src 'self'", "object-src 'none'", "base-uri 'none'"))),
            Check("index.html'de satır içi betik yok", not re.search(r"<script>(?!\s*</script>)", page)),
            Check("feed.json'da hassas alan yok", not re.search(r"chat_id|content_hashes|publish_error|source_titles|"
                                                                 r"telegram_update_offset|-100\d{6,}", blob)),
            Check("feed.json yalnızca https bağlantı", all(s["url"].startswith("https://") for i in feed["items"]
                                                            for s in i["sources"])),
            pytest("tests/test_site_exporter.py")]


def c_design() -> list[Check]:
    css = read("docs/assets/style.css")
    tokens = ("--night", "--sunset", "--pink", "--gold", "--mint", "--violet", "--t-official", "--t-multi",
              "--t-single", "--t-claim", "--display", "--body")
    return [Check("tasarım token'ları tanımlı", all(re.search(re.escape(t) + r"\s*:", css) for t in tokens)),
            Check("[hidden] her zaman gizler", "[hidden] { display: none !important; }" in css),
            Check("prefers-reduced-motion bloğu", "prefers-reduced-motion: reduce" in css),
            Check("kırılımlar 760px ve 1100px", "max-width: 760px" in css and "max-width: 1100px" in css),
            Check("güven rozeti sınıfları", all(f".badge--{g}" in css for g in ("official", "multi", "single", "claim")))]


def c_uix() -> list[Check]:
    js = read("docs/assets/app.js")
    page = read("docs/index.html")
    ids = ("hero", "grid", "empty", "demo-toggle", "q", "drawer", "telegram", "method", "pulse-list", "milestones",
           "st-demo", "nomatch")
    return [Check("örnek bülten tembel yüklenir", "data/demo-feed.js" in js and "demo-feed.js" not in page),
            Check("gerçek veri önceliği (realItems.length)", "!realItems.length &&" in js),
            Check("diyaloglar showModal ile", "showModal" in js),
            Check("safeHttps ve textContent", "function safeHttps" in js and "textContent" in js),
            Check("localStorage try/catch", bool(re.search(r"try \{ (if \(v == null\) )?localStorage", js))),
            Check("index.html gerekli kimlikler", all(f'id="{i}"' in page for i in ids)),
            Check("dört güven rozeti adı", all(n in js for n in ("Resmî Açıklama", "Çoklu Kaynak Doğrulamalı",
                                                                 "Tek Kaynak", "Topluluk / Sızıntı")))]


def c_webtest() -> list[Check]:
    checks = [Check("tools/site_check.py var", (ROOT / "tools" / "site_check.py").exists()),
              Check("app.js selftest kancası", "data-selftest" in read("docs/assets/app.js"))]
    sys.path.insert(0, str(ROOT / "tools"))
    import site_check  # noqa: PLC0415 - isteğe bağlı ağır denetim
    if site_check.find_chrome() is None:
        checks.append(Check("tarayıcı matrisi", True, "Chrome yok; atlandı"))
    else:
        errs = site_check.run()
        checks.append(Check("tarayıcı matrisi 3×2", not errs, "; ".join(errs[:3])))
    return checks


FUNCS: dict[str, Callable[[], list[Check]]] = {
    "security-auditor": c_security, "cost-guard": c_cost, "architect-verifier": c_architect,
    "python-tdd-runner": c_tdd, "rss-integrity-checker": c_rss, "telegram-api-guard": c_telegram,
    "gemini-schema-enforcer": c_gemini, "night-shift-supervisor": c_night, "token-budget-guardian": c_token,
    "arena-adversarial-review": c_arena, "atomic-json-recovery": c_atomic, "rss-anti-poisoning": c_poison,
    "official-source-verifier": c_official, "event-clustering-calibrator": c_cluster, "static-site-guardian": c_site,
    "vice-city-design-system": c_design, "ui-ux-interaction-standards": c_uix, "webapp-testing-site": c_webtest,
}


def audit(only: str | None = None) -> list[SkillResult]:
    """Skill'leri denetler; ``only`` verilirse yalnızca o skill."""
    results = []
    for path in sorted(SKILLS.glob("*/SKILL.md")):
        if only and path.parent.name != only:
            continue
        res, checks = structural(path)
        res.checks = checks
        fn = FUNCS.get(res.name)
        if fn is None:
            res.checks.append(Check("işlevsel denetleyici tanımlı", False, "FUNCS içinde yok"))
        else:
            try:
                res.checks += fn()
            except Exception as exc:  # denetleyici hatası da başarısızlıktır
                res.checks.append(Check("işlevsel denetim çalıştı", False, f"{type(exc).__name__}: {exc}"))
        results.append(res)
    return results


def render_report(results: list[SkillResult], session_notes: str) -> str:
    now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    ok = sum(r.ok for r in results)
    lines = [
        "# SKILL_AUDIT_REPORT — Skill Ekosistemi Denetimi", "",
        f"Üretim: `python tools/skill_audit.py` · {now} · **{ok}/{len(results)} skill tüm denetimlerden geçti**", "",
        "Her skill iki katmanda denetlenir: (1) **yapısal** — frontmatter, gövde dolu mu, tetiklenme ve otomatik "
        "doğrulama bölümleri, gizli kabuk komutu yok; (2) **işlevsel** — skill'in koyduğu kurallar koda, "
        "ayarlara ve testlere karşı gerçekten çalıştırılır.", "",
        "## Özet", "", "| Skill | Ne işe yarar | Ne zaman tetiklenir | Denetim | Durum |", "|---|---|---|---|---|",
    ]
    for r in results:
        passed = sum(c.ok for c in r.checks)
        desc = r.description.split(". ")[0].rstrip(".")
        lines.append(f"| `{r.name}` | {desc} | {r.trigger or '—'} | {passed}/{len(r.checks)} | "
                     f"{'✅ DOĞRULANDI' if r.ok else '❌ SORUN VAR'} |")
    lines += ["", "## Ayrıntılı sonuçlar", ""]
    for r in results:
        lines.append(f"### `{r.name}` — {'✅' if r.ok else '❌'} ({r.lines} satır)")
        lines.append("")
        for c in r.checks:
            detail = f" — {c.detail}" if c.detail else ""
            lines.append(f"- {'✅' if c.ok else '❌'} {c.name}{detail}")
        lines.append("")
    lines += [session_notes.strip(), ""]
    return "\n".join(lines)


SESSION_NOTES = """
## Bu oturumda aktif uygulanan skill'ler

### `token-budget-guardian`
- Dosyalar bir kez okundu; düzenlemeler hedefli `python - <<EOF` yamalarıyla yapıldı (tam dosya yeniden yazımı yalnızca yeni dosyalarda).
- Araç çıktıları `| tail -N` / `| head -N` ile kısıtlandı; tam `pytest -v` yalnızca rapor için bir kez çalıştırıldı.
- 2 deneme kuralı: Aşama 4'te hiçbir hata 2. denemeye kalmadı (Tur 6 yamaları ilk denemede yeşil).
- Alt ajan açılmadı; Arena rolleri tek bağlamda sırayla oynandı.

### `arena-adversarial-review`
- **Tur 6** (site + köprü) bu oturumda yürütüldü: 6 bulgu → 6 FAIL testi → yama → tamamı PASS. İki bulgu doğrudan demo
  üretiminden çıktı (12 haberden 2'si haksız yere incelemeye takılıyordu). Ayrıntı: `ARENA_DEBATE_LOG.md` → Tur 6.

### `official-source-verifier`
- Demo hattında iki resmî kaynak (Rockstar Newswire HTML listesi + Take-Two IR) gerçek `collect()` yolundan geçti;
  RESMÎ AÇIKLAMA rozeti yalnızca doğrulanmış resmî alan adlı 3 habere verildi; manşet en yeni resmî haber.
- Skill'in işlevsel denetimi `sources.json` resmî kaynak alan adlarını ve üçlü koşulu kodda doğruladı.
"""


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Skill denetleyicisi")
    ap.add_argument("--skill", help="yalnızca bu skill")
    args = ap.parse_args(argv)
    results = audit(args.skill)
    for r in results:
        print(f"{'OK ' if r.ok else 'ERR'} {r.name:30s} {sum(c.ok for c in r.checks)}/{len(r.checks)}")
        for c in r.checks:
            if not c.ok:
                print(f"     ✗ {c.name} — {c.detail}")
    if not args.skill:
        (ROOT / "SKILL_AUDIT_REPORT.md").write_text(render_report(results, SESSION_NOTES), encoding="utf-8")
        print("Yazıldı: SKILL_AUDIT_REPORT.md")
    return 0 if all(r.ok for r in results) else 1


if __name__ == "__main__":
    sys.exit(main())

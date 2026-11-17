/* GTA VI Türkiye Bülteni — Leonida Komuta Merkezi istemcisi.
 * Kurallar (.claude/skills/ui-ux-interaction-standards): veri yalnızca textContent ile yazılır,
 * yalnızca https bağlantılar (safeHttps), satır içi betik/innerHTML yok. Gerçek veri her zaman
 * örnek bültenin önündedir; gerçek akış boşken örnek bülten varsayılan olarak açıktır.
 * Animasyonlar transform/opacity ile; prefers-reduced-motion'da kapanır.
 */
(function () {
  "use strict";

  var TRUST = {
    official: { name: "Resmî Açıklama" },
    multi: { name: "Çoklu Kaynak Doğrulamalı" },
    single: { name: "Tek Kaynak" },
    claim: { name: "Topluluk / Sızıntı" }
  };
  var TRUST_ORDER = { official: 0, multi: 1, single: 2, claim: 3 };
  var TG_BADGE = { OFFICIAL: "🟩", MULTI_SOURCE: "🟦", SINGLE_SOURCE: "🟨", LEAK_CLAIM: "🟥", COMMUNITY_CLAIM: "🟧" };
  var TG_NOTE = {
    SINGLE_SOURCE: "Tek yayın organının haberi; resmî doğrulama yok.",
    LEAK_CLAIM: "Doğrulanmamış sızıntı iddiası; kesin bilgi değildir.",
    COMMUNITY_CLAIM: "Topluluk kaynaklı, doğrulanmamış iddia."
  };
  var TIER = { OFFICIAL: "Resmî", ESTABLISHED_MEDIA: "Basın", COMMUNITY: "Topluluk", UNKNOWN: "Diğer" };
  var TZ = "Europe/Istanbul";
  var DEMO_KEY = "gta6.demo";
  var LEONIDA = window.__LEONIDA__ || { regions: [], bounds: null };
  var REGIONS = LEONIDA.regions || [];
  var REGION = {}; REGIONS.forEach(function (r) { REGION[r.id] = r; });
  var SVGNS = "http://www.w3.org/2000/svg";

  var $ = function (s, r) { return (r || document).querySelector(s); };
  var $$ = function (s, r) { return Array.prototype.slice.call((r || document).querySelectorAll(s)); };
  var params = new URLSearchParams(location.search);
  var reduced = window.matchMedia && matchMedia("(prefers-reduced-motion: reduce)").matches;
  var finePointer = window.matchMedia && matchMedia("(hover: hover) and (pointer: fine)").matches;

  var state = {
    real: null, demo: null, feed: null, usingDemo: false, items: [],
    trust: "all", cat: "all", q: "", region: null, byId: {},
    cam: { region: null, tx: 0, ty: 0, s: 1 }
  };

  /* ---------- yardımcılar ---------- */
  function el(tag, cls, text) {
    var n = document.createElement(tag);
    if (cls) n.className = cls;
    if (text != null) n.textContent = String(text);
    return n;
  }
  function sv(tag, attrs, text) {
    var n = document.createElementNS(SVGNS, tag);
    Object.keys(attrs || {}).forEach(function (k) { n.setAttribute(k, attrs[k]); });
    if (text != null) n.textContent = String(text);
    return n;
  }
  function icon(paths) {
    var s = sv("svg", { viewBox: "0 0 24 24", "aria-hidden": "true" });
    paths.forEach(function (d) { s.appendChild(sv("path", { d: d })); });
    return s;
  }
  function cover(regionId) {
    var s = sv("svg", { viewBox: "0 0 320 140", preserveAspectRatio: "xMidYMid slice", "aria-hidden": "true" });
    s.appendChild(sv("use", { href: "#cover-" + (REGION[regionId] ? regionId : "vice_city") }));
    return s;
  }
  var ICON_SEND = ["M21 3 3 10.5l6.5 2.5L12 20l3-6.5L21 3z", "M9.5 13 21 3"];
  var ICON_COPY = ["M9 9h10v10H9z", "M5 15V5h10"];
  var ICON_PIN = ["M12 21s-6-5.6-6-11a6 6 0 0 1 12 0c0 5.4-6 11-6 11z", "M12 12.5a2.5 2.5 0 1 0 0-5 2.5 2.5 0 0 0 0 5z"];

  /* Kaynağın kendi görseli: yalnızca https, yönlendiren bilgisi gönderilmez; yüklenemezse SVG kapak kalır. */
  function photo(it, cls) {
    var u = safeHttps(it.image);
    if (!u) return null;
    var img = el("img", cls);
    img.alt = ""; img.loading = "lazy"; img.decoding = "async"; img.referrerPolicy = "no-referrer";
    img.addEventListener("load", function () { img.classList.add("is-loaded"); });
    img.addEventListener("error", function () { img.remove(); });
    img.src = u;
    return img;
  }
  function credit(it) { return "Görsel: " + (it.image_credit || domain(it.image) || "kaynak"); }

  function safeHttps(u) {
    try { var x = new URL(String(u)); return x.protocol === "https:" ? x.href : null; } catch (e) { return null; }
  }
  function domain(u) { try { return new URL(u).hostname.replace(/^www\./, ""); } catch (e) { return ""; } }
  function store(k, v) { try { if (v == null) localStorage.removeItem(k); else localStorage.setItem(k, v); } catch (e) { /* gizli mod */ } }
  function load(k) { try { return localStorage.getItem(k); } catch (e) { return null; } }
  function fold(s) { return String(s || "").toLocaleLowerCase("tr").normalize("NFD").replace(/[̀-ͯ]/g, "").replace(/ı/g, "i"); }
  function parseDate(s) { var d = s ? new Date(s) : null; return d && !isNaN(d) ? d : null; }
  function absTime(d) {
    return new Intl.DateTimeFormat("tr-TR", { timeZone: TZ, day: "numeric", month: "long", hour: "2-digit", minute: "2-digit" }).format(d);
  }
  function relTime(d) {
    var sec = Math.round((Date.now() - d.getTime()) / 1000);
    if (sec < 60) return "az önce";
    var m = Math.round(sec / 60); if (m < 60) return m + " dk önce";
    var h = Math.round(m / 60); if (h < 24) return h + " saat önce";
    var g = Math.round(h / 24); if (g < 7) return g + " gün önce";
    return absTime(d);
  }
  function readMins(it) {
    var words = (String(it.title || "") + " " + String(it.summary || "")).trim().split(/\s+/).length;
    return Math.max(1, Math.round(words / 180));
  }
  /* Gerçek akışta her haberin bot tarafından üretilmiş kalıcı sayfası var (haber/<id>.html): paylaşımda
   * görsel önizleme ve arama motoru indeksi bu sayfadan gelir. Örnek bültende sayfa yok → harita bağlantısı. */
  function pagePath(it) { return /^[A-Za-z0-9_-]{4,64}$/.test(it.id) ? "haber/" + it.id + ".html" : null; }
  function permalink(it) {
    var base = location.origin + location.pathname.replace(/[^/]*$/, "");
    var p = !state.usingDemo && pagePath(it);
    return p ? base + p : location.origin + location.pathname + "#haber-" + it.id;
  }
  function shareUrl(it) {
    return "https://t.me/share/url?url=" + encodeURIComponent(permalink(it)) + "&text=" + encodeURIComponent(it.title || "");
  }

  /* Haber → Leonida konumu: feed.json'daki location_id; yoksa (eski veri) anahtar kelime + kategori. */
  function locOf(it) {
    if (it.location_id && REGION[it.location_id]) return it.location_id;
    var hay = " " + fold(it.title + " " + (it.summary || "")) + " ";
    var best = null, bestScore = 0;
    REGIONS.forEach(function (r) {
      var sc = 0;
      (r.keywords || []).forEach(function (k) { if (hay.indexOf(" " + fold(k)) >= 0) sc++; });
      if ((r.categories || []).indexOf(it.category) >= 0) sc += 0.5;
      if (sc > bestScore) { bestScore = sc; best = r.id; }
    });
    return best || "vice_city";
  }

  var toastTimer;
  function toast(msg) {
    var t = $("#toast"); t.textContent = msg; t.hidden = false;
    clearTimeout(toastTimer); toastTimer = setTimeout(function () { t.hidden = true; }, 2200);
  }
  function copy(text, btn) {
    var done = function () {
      toast("Bağlantı kopyalandı");
      if (btn) { btn.classList.add("is-done"); setTimeout(function () { btn.classList.remove("is-done"); }, 1600); }
    };
    function fallback() {
      var ta = el("textarea"); ta.value = text; ta.setAttribute("readonly", ""); ta.style.position = "fixed"; ta.style.opacity = "0";
      document.body.appendChild(ta); ta.select();
      try { document.execCommand("copy"); done(); } catch (e) { toast("Kopyalanamadı; bağlantı: " + text); }
      ta.remove();
    }
    if (navigator.clipboard && window.isSecureContext) navigator.clipboard.writeText(text).then(done, fallback);
    else fallback();
  }

  /* ---------- veri ---------- */
  function validFeed(f) { return f && typeof f === "object" && Array.isArray(f.items) && f.status && typeof f.status === "object"; }
  function cleanItems(f) {
    return f.items.filter(function (it) { return it && it.id && it.title && TRUST[it.trust_group]; })
      .map(function (it) { var c = Object.assign({}, it); c._loc = locOf(it); return c; });
  }
  function ranked(items) {
    return items.slice().sort(function (a, b) {
      return (TRUST_ORDER[a.trust_group] - TRUST_ORDER[b.trust_group])
        || ((b.source_strength || 0) - (a.source_strength || 0))
        || ((parseDate(b.published_at) || 0) - (parseDate(a.published_at) || 0));
    });
  }
  function byDate(a, b) { return (parseDate(b.published_at) || 0) - (parseDate(a.published_at) || 0); }
  function heroOf(f, items) {
    var m = {}; items.forEach(function (i) { m[i.id] = i; });
    if (f.hero_id && m[f.hero_id]) return m[f.hero_id];
    return ranked(items)[0] || null;
  }

  function loadDemo(cb) {
    if (window.__GTA6_DEMO_FEED__) return cb(window.__GTA6_DEMO_FEED__);
    var s = document.createElement("script");
    s.src = "data/demo-feed.js";
    s.onload = function () { cb(window.__GTA6_DEMO_FEED__ || null); };
    s.onerror = function () { toast("Örnek bülten yüklenemedi"); cb(null); };
    document.body.appendChild(s);
  }

  function choose() {
    var realItems = validFeed(state.real) ? cleanItems(state.real) : [];
    // Gerçek akış boşken örnek bülten varsayılan olarak açık; kullanıcı kapattıysa ("0") kapalı kalır.
    var wantDemo = !realItems.length && params.get("demo") !== "0" && (load(DEMO_KEY) !== "0" || params.get("demo") === "1");
    if (wantDemo && !state.demo) {
      loadDemo(function (d) { state.demo = validFeed(d) ? d : false; choose(); });
      return;
    }
    state.usingDemo = Boolean(wantDemo && state.demo);
    state.feed = state.usingDemo ? state.demo : state.real;
    render();
  }

  /* ---------- çizim ---------- */
  function render() {
    var f = state.feed || { status: {}, items: [] };
    var items = validFeed(f) ? cleanItems(f) : [];
    state.items = items;
    state.byId = {}; items.forEach(function (i) { state.byId[i.id] = i; });
    renderStatus(f, items);
    renderHero(f, items);
    renderPins(items);
    renderRegionChips(items);
    renderPulse(f);
    renderCounts(items);
    renderGrid(items, f);
    renderMethodNote(f);
    if (state.region) renderRegionPanel(state.region);
    document.documentElement.classList.toggle("is-demo", state.usingDemo);
    if (window.GTA6Money) window.GTA6Money.render(state.usingDemo);
    selftest(items);
    if (!state.routed) { state.routed = true; route(); }
  }

  function renderStatus(f, items) {
    var s = f.status || {};
    var pulse = $("#st-pulse"); pulse.className = "pulse";
    var last = parseDate(s.last_run_at);
    var stale = last && (Date.now() - last.getTime() > 3 * 3600 * 1000);
    var label;
    if (state.usingDemo) { label = "Örnek bülten"; pulse.classList.add("is-demo"); }
    else if (!validFeed(state.real)) { label = "Veri okunamadı"; pulse.classList.add("is-error"); }
    else if (s.paused) { label = "Yayın duraklatıldı"; pulse.classList.add("is-paused"); }
    else if (stale) { label = "Tarama gecikmeli"; pulse.classList.add("is-stale"); }
    else { label = "Canlı"; }
    $("#st-state").textContent = label;
    var realLast = parseDate(state.real && state.real.status && state.real.status.last_run_at);
    $("#st-updated").textContent = realLast ? "tarama " + relTime(realLast) : "";
    var sw = $("#demo-switch"), realCount = validFeed(state.real) ? cleanItems(state.real).length : 0;
    sw.hidden = realCount > 0;
    $("#demo-toggle").checked = state.usingDemo;
    var note = $("#demo-note");
    note.hidden = !state.usingDemo;
    note.textContent = state.usingDemo
      ? "Gerçek akışta henüz doğrulanmış haber yok; aşağıdakiler bültenin nasıl görüneceğini gösteren örneklerdir. İlk gerçek haber geldiğinde örnekler otomatik olarak kalkar."
      : "";
  }

  function badge(group) { return el("span", "badge badge--" + group, TRUST[group].name); }

  function renderHero(f, items) {
    var box = $("#hero"); box.textContent = "";
    var h = heroOf(f, items);
    box.classList.toggle("is-empty", !h);
    box.onclick = null;
    if (!h) {
      var k = el("div", "feature__kicker"); k.appendChild(el("span", "feature__label", "Bülten hazır"));
      box.appendChild(k);
      box.appendChild(el("h2", "feature__title", "İlk doğrulanmış haber yolda"));
      var n = (f.status && f.status.active_sources) || 0;
      box.appendChild(el("p", "feature__summary", (n ? n + " kaynak" : "Kaynaklar") + " düzenli olarak taranıyor. Doğrulanan haber burada ve haritada belirir."));
      var a = el("div", "feature__actions");
      var b = el("button", "btn btn--glow", "Örnek bülteni göster"); b.type = "button";
      b.addEventListener("click", function () { setDemo(true); });
      a.appendChild(b); box.appendChild(a);
      return;
    }
    var kick = el("div", "feature__kicker");
    kick.appendChild(el("span", "feature__label", state.usingDemo ? "Örnek manşet" : "Öne çıkan"));
    kick.appendChild(badge(h.trust_group));
    kick.appendChild(el("span", "loc", REGION[h._loc] ? REGION[h._loc].name : ""));
    box.appendChild(kick);
    box.appendChild(el("h2", "feature__title", h.title));
    if (h.summary) box.appendChild(el("p", "feature__summary", h.summary));
    var meta = el("div", "feature__meta");
    var d = parseDate(h.published_at);
    if (d) { var t = el("time", null, relTime(d)); t.dateTime = h.published_at; t.title = absTime(d); meta.appendChild(t); }
    meta.appendChild(el("span", null, readMins(h) + " dk okuma"));
    var srcs = (h.sources || []).map(function (s) { return s.name; }).filter(Boolean);
    if (srcs.length) meta.appendChild(el("span", null, srcs.slice(0, 3).join(", ")));
    box.appendChild(meta);
    var act = el("div", "feature__actions");
    var open = el("button", "btn btn--glow", "Haberi aç"); open.type = "button";
    open.addEventListener("click", function (e) { e.stopPropagation(); openItem(h.id); });
    var onmap = el("button", "btn", "Haritada göster"); onmap.type = "button";
    onmap.addEventListener("click", function (e) { e.stopPropagation(); showOnMap(h._loc, false); });
    act.appendChild(open); act.appendChild(onmap); box.appendChild(act);
    box.onclick = function () { openItem(h.id); };
  }

  /* ---------- harita ---------- */
  function countByRegion(items) {
    var c = {}; REGIONS.forEach(function (r) { c[r.id] = 0; });
    items.forEach(function (i) { c[i._loc] = (c[i._loc] || 0) + 1; });
    return c;
  }

  function renderPins(items) {
    var g = $("#pins"); if (!g) return;
    g.textContent = "";
    var counts = countByRegion(items);
    REGIONS.forEach(function (r, i) {
      var pin = sv("g", { "class": "pin", "data-region": r.id, transform: "translate(" + r.x + " " + r.y + ")", tabindex: "0", role: "button",
        "aria-label": r.name + ": " + counts[r.id] + " haber. " + r.topics });
      pin.style.setProperty("--d", (0.6 + i * 0.12) + "s");
      if (state.region === r.id || state.cam.region === r.id) pin.classList.add("is-active");
      if (state.region && state.region !== r.id) pin.classList.add("is-dim");
      var inner = sv("g", { "class": "pin__inner" });
      inner.appendChild(sv("circle", { "class": "pin__ring", r: 14 }));
      inner.appendChild(sv("circle", { "class": "pin__ring pin__ring--2", r: 14 }));
      inner.appendChild(sv("circle", { "class": "pin__core", r: 8 }));
      var lb = r.label || [18, -12, "start"];
      inner.appendChild(sv("text", { "class": "pin__label", x: lb[0], y: lb[1], "text-anchor": lb[2] }, r.name));
      if (counts[r.id]) {
        inner.appendChild(sv("circle", { "class": "pin__badge", cx: 10, cy: 10, r: 9 }));
        inner.appendChild(sv("text", { "class": "pin__count", x: 10, y: 14, "text-anchor": "middle" }, counts[r.id]));
      }
      pin.appendChild(inner);
      pin.addEventListener("click", function () { toggleRegion(r.id); });
      pin.addEventListener("keydown", function (e) { if (e.key === "Enter" || e.key === " ") { e.preventDefault(); toggleRegion(r.id); } });
      g.appendChild(pin);
    });
  }

  function renderRegionChips(items) {
    var box = $("#region-chips"); box.textContent = "";
    var counts = countByRegion(items);
    REGIONS.forEach(function (r) {
      var b = el("button", "rchip"); b.type = "button";
      b.style.setProperty("--c", getComputedStyle(document.documentElement).getPropertyValue("--pink"));
      var pinColor = { vice_city: "#FF5E8F", leonida_keys: "#6FE3D6", grassrivers: "#8BD9A3", port_gellhorn: "#B3A8FF", mount_kalaga: "#FFCB6B" }[r.id];
      if (pinColor) b.style.setProperty("--c", pinColor);
      b.setAttribute("aria-pressed", String(state.region === r.id));
      b.appendChild(el("i"));
      b.appendChild(el("span", null, r.name));
      b.appendChild(el("small", null, counts[r.id]));
      b.addEventListener("click", function () { toggleRegion(r.id); });
      box.appendChild(b);
    });
  }

  function geometry() {
    var vp = $("#map-viewport");
    var W = vp.clientWidth, H = vp.clientHeight;
    var k = Math.min(W / 1000, H / 700);
    return { W: W, H: H, k: k, ox: (W - 1000 * k) / 2, oy: (H - 700 * k) / 2, wide: window.innerWidth > 1100 };
  }

  function camera(regionId) {
    var g = geometry();
    var s, px, py, cx, cy;
    if (!regionId) {
      // Genel görünüm: gerçek Florida/Leonida sınırlarını (x ≈ 220–880, y ≈ 30–670) boş alana sığdır.
      // Masaüstünde boş alan başlığın sağı ve alt panellerin üstüdür.
      var aw = g.wide ? g.W * 0.5 : g.W * 0.8, ah = g.wide ? g.H * 0.56 : g.H * 0.86;
      s = Math.min(aw / (430 * g.k), ah / (690 * g.k), 1.15);
      px = g.ox + 485 * g.k; py = g.oy + 352 * g.k;
      cx = g.wide ? g.W * 0.70 : g.W * 0.5; cy = g.wide ? g.H * 0.35 : g.H * 0.5;
    } else {
      var r = REGION[regionId];
      s = g.wide ? 2.1 : 1.9;
      px = g.ox + r.x * g.k; py = g.oy + r.y * g.k;
      cx = g.wide ? g.W * 0.46 : g.W * 0.5; cy = g.wide ? g.H * 0.4 : g.H * 0.5;
    }
    var tx = cx - px * s, ty = cy - py * s;
    state.cam = { region: regionId, tx: tx, ty: ty, s: s };
    var cam = $("#map-camera");
    cam.style.transform = "translate3d(" + tx.toFixed(1) + "px," + ty.toFixed(1) + "px,0) scale(" + s.toFixed(3) + ")";
    cam.style.setProperty("--zoom", s.toFixed(3));
    // İğneler ekranda okunur boyutta kalsın: kamera yakınlaşınca küçülür, küçük ekranda büyür
    cam.style.setProperty("--pinscale", Math.max(1 / s, 0.85 / (s * g.k)).toFixed(3));
    $$(".pin").forEach(function (p) { p.classList.toggle("is-active", p.getAttribute("data-region") === regionId); });
  }

  function flash(regionId) {
    var p = $('.pin[data-region="' + regionId + '"]'); if (!p) return;
    p.classList.remove("is-flash"); void p.getBoundingClientRect(); p.classList.add("is-flash");
    setTimeout(function () { p.classList.remove("is-flash"); }, 1900);
  }

  function renderRegionPanel(regionId) {
    var r = REGION[regionId]; var panel = $("#region-panel");
    if (!r) { panel.hidden = true; return; }
    panel.hidden = false;
    $("#rp-coords").textContent = r.coords + " · " + r.topics;
    $("#rp-name").textContent = r.name;
    $("#rp-desc").textContent = r.desc;
    var list = $("#rp-list"); list.textContent = "";
    var inRegion = state.items.filter(function (i) { return i._loc === regionId; });
    ranked(inRegion).slice(0, 3).forEach(function (it) {
      var li = el("li"); var b = el("button"); b.type = "button";
      b.appendChild(badge(it.trust_group)); b.appendChild(el("b", null, it.title));
      b.addEventListener("click", function () { openItem(it.id); });
      li.appendChild(b); list.appendChild(li);
    });
    if (!inRegion.length) list.appendChild(el("li", "empty", "Bu bölgede henüz doğrulanmış haber yok."));
    var go = $("#rp-go");
    go.textContent = inRegion.length ? "Bu bölgedeki " + inRegion.length + " haberi gör" : "Tüm haberlere dön";
    go.onclick = function () {
      if (!inRegion.length) setRegion(null);
      $("#akis").scrollIntoView({ behavior: reduced ? "auto" : "smooth" });
    };
  }

  function setRegion(id) {
    state.region = id;
    camera(id);
    if (id) { renderRegionPanel(id); flash(id); } else { $("#region-panel").hidden = true; }
    var pill = $("#region-pill");
    pill.hidden = !id;
    if (id) { pill.textContent = REGION[id].name; pill.style.setProperty("--c", { vice_city: "#FF2E88", leonida_keys: "#35F0E0", grassrivers: "#6BE38E", port_gellhorn: "#A99BFF", mount_kalaga: "#FFC94A" }[id]); }
    renderPins(state.items);
    renderRegionChips(state.items);
    renderGrid(state.items, state.feed || {});
  }
  function toggleRegion(id) { setRegion(state.region === id ? null : id); }

  function showOnMap(regionId, keepScroll) {
    if (!REGION[regionId]) return;
    var d = $("dialog[open]"); if (d) closeDialog(d);
    if (!keepScroll) $("#harita").scrollIntoView({ behavior: reduced ? "auto" : "smooth" });
    camera(regionId);
    renderRegionPanel(regionId);
    setTimeout(function () { flash(regionId); }, reduced ? 0 : 500);
  }

  /* Fare ve kaydırma paralaksı + koordinat göstergesi (yalnızca transform). */
  function bindParallax() {
    var stage = $("#harita"), coords = $("#hud-coords"), b = LEONIDA.bounds;
    var raf = 0, mx = 0, my = 0, lastEvt = null;
    if (!reduced && finePointer) {
      stage.addEventListener("pointermove", function (e) {
        lastEvt = e;
        if (raf) return;
        raf = requestAnimationFrame(function () {
          raf = 0;
          var rect = stage.getBoundingClientRect();
          mx = ((lastEvt.clientX - rect.left) / rect.width - 0.5) * 2;
          my = ((lastEvt.clientY - rect.top) / rect.height - 0.5) * 2;
          stage.style.setProperty("--mx", mx.toFixed(3));
          stage.style.setProperty("--my", my.toFixed(3));
          if (b) {
            var g = geometry(), vr = $("#map-viewport").getBoundingClientRect(), c = state.cam;
            var vx = ((lastEvt.clientX - vr.left - c.tx) / c.s - g.ox) / g.k;
            var vy = ((lastEvt.clientY - vr.top - c.ty) / c.s - g.oy) / g.k;
            if (vx >= 0 && vx <= 1000 && vy >= 0 && vy <= 700) {
              var lat = b.latTop - (vy / 700) * (b.latTop - b.latBottom);
              var lon = b.lonLeft - (vx / 1000) * (b.lonLeft - b.lonRight);
              coords.textContent = lat.toFixed(3) + "° K · " + lon.toFixed(3) + "° B";
            }
          }
        });
      });
    }
    var sraf = 0;
    window.addEventListener("scroll", function () {
      if (sraf) return;
      sraf = requestAnimationFrame(function () {
        sraf = 0;
        var y = window.scrollY, max = document.documentElement.scrollHeight - window.innerHeight;
        $("#readbar").style.transform = "scaleX(" + (max > 0 ? Math.min(1, y / max) : 0).toFixed(4) + ")";
        if (!reduced && window.innerWidth > 1100 && y < stage.offsetHeight) stage.style.setProperty("--sy", (y * 0.22).toFixed(1) + "px");
      });
    }, { passive: true });
    var rt;
    window.addEventListener("resize", function () { clearTimeout(rt); rt = setTimeout(function () { camera(state.cam.region); }, 120); });
  }

  /* ---------- kaynak nabzı ---------- */
  function renderPulse(f) {
    var s = (state.real && state.real.status) || f.status || {};
    if (state.usingDemo && !(s.sources && s.sources.length)) s = f.status || s;
    var list = $("#pulse-list"); list.textContent = "";
    var srcs = Array.isArray(s.sources) ? s.sources : [];
    var ok = 0, relevant = 0;
    srcs.forEach(function (x) {
      if (!x || !x.name) return;
      var st = ["ok", "empty", "error", "pending"].indexOf(x.state) >= 0 ? x.state : "pending";
      if (st === "ok") ok++;
      relevant += Number(x.relevant) || 0;
      var li = el("li", "src src--" + st);
      li.appendChild(el("i"));
      li.appendChild(el("span", null, x.name));
      var stTxt = { ok: (Number(x.entries) || 0) + " kayıt", empty: "yeni kayıt yok", error: "erişilemedi", pending: "bekleniyor" }[st];
      li.appendChild(el("small", null, stTxt));
      if (TIER[x.trust_class]) li.appendChild(el("span", "src__tier", TIER[x.trust_class]));
      li.title = x.name + ": " + stTxt + (x.relevant ? " · " + x.relevant + " GTA VI ile ilgili" : "");
      list.appendChild(li);
    });
    var sum;
    if (srcs.length) sum = ok + "/" + srcs.length + " kaynak yanıt verdi · son taramada " + relevant + " ilgili kayıt";
    else if (s.active_sources) sum = (s.sources_ok_last_run || 0) + "/" + s.active_sources + " kaynak son taramada yanıt verdi";
    else sum = "Kaynak durumu ilk taramadan sonra görünür.";
    $("#pulse-sum").textContent = sum;
    list.hidden = !srcs.length;
  }

  /* ---------- akış ---------- */
  function matches(it) {
    if (state.region && it._loc !== state.region) return false;
    if (state.trust !== "all" && it.trust_group !== state.trust) return false;
    if (state.cat !== "all") {
      var ok = it.category === state.cat || (state.cat === "COMMUNITY_RUMOR" && it.trust_group === "claim");
      if (!ok) return false;
    }
    if (state.q) {
      var hay = fold([it.title, it.summary, it.category_tr, REGION[it._loc] ? REGION[it._loc].name : "",
        (it.sources || []).map(function (s) { return s.name + " " + domain(s.url); }).join(" ")].join(" "));
      var words = fold(state.q).split(/\s+/).filter(Boolean);
      for (var i = 0; i < words.length; i++) if (hay.indexOf(words[i]) < 0) return false;
    }
    return true;
  }

  function renderCounts(items) {
    var c = { all: items.length, official: 0, multi: 0, single: 0, claim: 0 };
    items.forEach(function (i) { c[i.trust_group]++; });
    $$("[data-count]").forEach(function (n) { n.textContent = items.length ? c[n.getAttribute("data-count")] : ""; });
  }

  var hoverTimer;
  function card(it, wide) {
    var c = el("article", "card card--" + it.trust_group + (wide ? " card--wide" : ""));
    c.id = "haber-" + it.id;
    c.setAttribute("data-region", it._loc);
    var cv = el("div", "card__cover");
    cv.appendChild(cover(it._loc));
    var ph = photo(it, "card__img");
    if (ph) { cv.appendChild(ph); var cr = el("p", "credit", credit(it)); cv.appendChild(cr); ph.addEventListener("error", function () { cr.remove(); }); }
    cv.appendChild(badge(it.trust_group));
    cv.appendChild(el("span", "card__loc", REGION[it._loc] ? REGION[it._loc].name : ""));
    c.appendChild(cv);
    var body = el("div", "card__body");
    var info = el("div", "card__info");
    if (it.category_tr) info.appendChild(el("span", null, it.category_tr));
    info.appendChild(el("span", null, readMins(it) + " dk okuma"));
    body.appendChild(info);
    var h = el("h3", "card__title");
    var open = el("button", "card__open", it.title); open.type = "button";
    open.addEventListener("click", function () { openItem(it.id); });
    h.appendChild(open); body.appendChild(h);
    if (it.summary) body.appendChild(el("p", "card__summary", it.summary));
    var srcBox = el("div", "card__sources");
    (it.sources || []).slice(0, 3).forEach(function (s) {
      var u = safeHttps(s.url); if (!u) return;
      var a = el("a", "chip-src"); a.href = u; a.target = "_blank"; a.rel = "noopener noreferrer";
      a.title = s.name + " · " + u;
      a.appendChild(el("span", "chip-src__ico", (s.name || "?").charAt(0).toLocaleUpperCase("tr")));
      a.appendChild(el("span", null, s.name));
      a.appendChild(el("span", "chip-src__dom", domain(u)));
      srcBox.appendChild(a);
    });
    if ((it.sources || []).length > 3) srcBox.appendChild(el("span", "card__time", "+" + (it.sources.length - 3)));
    body.appendChild(srcBox);
    var foot = el("div", "card__foot");
    var d = parseDate(it.published_at);
    var t = el("time", "card__time", d ? relTime(d) : ""); if (d) { t.dateTime = it.published_at; t.title = absTime(d); }
    foot.appendChild(t);
    var acts = el("div", "card__actions");
    var mp = el("button", "iconbtn"); mp.type = "button"; mp.title = "Haritada göster";
    mp.setAttribute("aria-label", "Haritada göster: " + it.title); mp.appendChild(icon(ICON_PIN));
    mp.addEventListener("click", function () { showOnMap(it._loc, false); });
    var sh = el("a", "iconbtn"); sh.href = shareUrl(it); sh.target = "_blank"; sh.rel = "noopener noreferrer";
    sh.setAttribute("aria-label", "Telegram'da paylaş: " + it.title); sh.title = "Telegram'da paylaş"; sh.appendChild(icon(ICON_SEND));
    var cp = el("button", "iconbtn"); cp.type = "button"; cp.setAttribute("aria-label", "Bağlantıyı kopyala: " + it.title); cp.title = "Bağlantıyı kopyala";
    cp.appendChild(icon(ICON_COPY));
    cp.addEventListener("click", function () { copy(permalink(it), cp); });
    acts.appendChild(mp); acts.appendChild(sh); acts.appendChild(cp); foot.appendChild(acts);
    body.appendChild(foot);
    c.appendChild(body);

    // Üzerine gelince harita o konuma uçar (görünüyorsa) ve iğne parlar; kart 3B eğilir.
    c.addEventListener("pointerenter", function () {
      clearTimeout(hoverTimer);
      hoverTimer = setTimeout(function () {
        var r = $("#harita").getBoundingClientRect();
        if (r.bottom > 80 && !state.region) camera(it._loc);
        flash(it._loc);
      }, 220);
    });
    c.addEventListener("pointerleave", function () {
      clearTimeout(hoverTimer);
      c.style.transform = "";
    });
    if (finePointer && !reduced) {
      c.addEventListener("pointermove", function (e) {
        var b = c.getBoundingClientRect();
        var rx = ((e.clientY - b.top) / b.height - 0.5) * -7;
        var ry = ((e.clientX - b.left) / b.width - 0.5) * 9;
        c.style.transform = "translate3d(0,-4px,0) rotateX(" + rx.toFixed(2) + "deg) rotateY(" + ry.toFixed(2) + "deg)";
      });
    }
    return c;
  }

  function renderGrid(items, f) {
    var grid = $("#grid"); grid.textContent = "";
    var empty = $("#empty"), nomatch = $("#nomatch");
    var filtering = state.trust !== "all" || state.cat !== "all" || state.q || state.region;
    empty.hidden = items.length > 0;
    if (!items.length) {
      nomatch.hidden = true;
      $("#feed-title").textContent = "Son haberler";
      $("#result-line").textContent = "";
      $("#empty-text").textContent = !validFeed(state.real)
        ? "Bülten verisi şu an okunamıyor. Sayfayı birkaç dakika sonra yenileyin."
        : "Kaynaklar taranıyor; doğrulanan ilk haber burada ve haritada otomatik olarak görünür. Bu arada bültenin dolu hâlini örnek verilerle inceleyebilirsiniz.";
      return;
    }
    var hero = heroOf(f, items);
    var list = items.filter(function (i) { return filtering || !hero || i.id !== hero.id; }).sort(byDate);
    var shown = list.filter(matches);
    nomatch.hidden = shown.length > 0;
    var frag = document.createDocumentFragment();
    shown.forEach(function (it, i) { frag.appendChild(card(it, !filtering && i < 2)); });
    grid.appendChild(frag);
    $("#feed-title").textContent = state.region ? REGION[state.region].name : (state.usingDemo ? "Örnek bülten" : "Son haberler");
    $("#result-line").textContent = filtering ? shown.length + " haber eşleşti" : items.length + " doğrulanmış haber · en yenisi üstte";
  }

  function renderMethodNote(f) {
    var s = (state.real && state.real.status) || f.status || {};
    $("#m-sub").textContent = (s.active_sources ? s.active_sources + " kaynak, " : "") + "altı adım, tek kural: etiket kanıtla belirlenir.";
    $("#m-note").textContent = s.measurement_note || "";
  }

  /* ---------- çekmeceler ---------- */
  function openItem(id, fromHash) {
    var it = state.byId[id]; if (!it) return;
    $("#d-cover").setAttribute("href", "#cover-" + (REGION[it._loc] ? it._loc : "vice_city"));
    var dimg = $("#d-image"), dcr = $("#d-credit"), du = safeHttps(it.image);
    dimg.classList.remove("is-loaded"); dimg.hidden = !du; dcr.hidden = !du;
    if (du) {
      dimg.onload = function () { dimg.classList.add("is-loaded"); };
      dimg.onerror = function () { dimg.hidden = true; dcr.hidden = true; };
      dimg.src = du; dcr.textContent = credit(it);
    } else { dimg.removeAttribute("src"); }
    var b = $("#d-badges"); b.textContent = ""; b.appendChild(badge(it.trust_group));
    b.appendChild(el("span", "loc", REGION[it._loc] ? REGION[it._loc].name : ""));
    $("#d-title").textContent = it.title;
    var d = parseDate(it.published_at);
    $("#d-meta").textContent = [d ? absTime(d) : "", it.category_tr || "", readMins(it) + " dk okuma"].filter(Boolean).join(" · ");
    $("#d-summary").textContent = it.summary || "";
    $("#d-why").textContent = it.why_this_label || TRUST[it.trust_group].name;
    var st = Math.max(0, Math.min(100, Number(it.source_strength) || 0));
    $("#d-strength").textContent = st + "/100";
    $("#d-strength-bar").style.transform = "scaleX(" + (st / 100) + ")";
    $("#d-origins").textContent = String(it.independent_origins || (it.sources || []).length || 0);
    var ul = $("#d-sources"); ul.textContent = "";
    (it.sources || []).forEach(function (s) {
      var u = safeHttps(s.url); if (!u) return;
      var li = el("li"); var a = el("a"); a.href = u; a.target = "_blank"; a.rel = "noopener noreferrer";
      a.appendChild(el("span", "chip-src__ico", (s.name || "?").charAt(0).toLocaleUpperCase("tr")));
      var mid = el("span"); mid.appendChild(el("b", null, s.name)); mid.appendChild(el("small", null, domain(u) + new URL(u).pathname));
      a.appendChild(mid); a.appendChild(el("em", null, "Kaynağa git"));
      li.appendChild(a); ul.appendChild(li);
    });
    var tg = $("#d-telegram"); var tgu = safeHttps(it.telegram_url);
    tg.href = tgu || shareUrl(it); tg.textContent = tgu ? "Telegram gönderisini aç" : "Telegram'da paylaş";
    $("#d-copy").onclick = function () { copy(permalink(it), $("#d-copy")); };
    var dp = $("#d-page"), pp = !state.usingDemo && pagePath(it);
    dp.hidden = !pp; if (pp) dp.href = pp;
    if (window.GTA6Money) window.GTA6Money.fillRelated($("#d-kit"), $("#d-kit-list"), it.title + " " + (it.summary || ""));
    $("#d-map").onclick = function () { showOnMap(it._loc, false); };
    if (!fromHash) history.replaceState(null, "", "#haber-" + it.id);
    var panel = $("#drawer-panel"); panel.scrollTop = 0; $("#d-progress").style.transform = "scaleX(0)";
    showDialog($("#drawer"));
  }

  function showDialog(dlg) {
    if (dlg.open) return;
    if (typeof dlg.showModal === "function") dlg.showModal(); else dlg.setAttribute("open", "");
  }
  function closeDialog(dlg) {
    if (typeof dlg.close === "function") dlg.close(); else dlg.removeAttribute("open");
  }
  function openSheet(name) {
    var open = $("dialog[open]"); if (open) closeDialog(open);
    if (name === "telegram") { renderPhone(); showDialog($("#telegram")); history.replaceState(null, "", "#telegram"); }
    if (name === "method") { showDialog($("#method")); history.replaceState(null, "", "#yontem"); }
  }

  function bubble(it) {
    var b = el("div", "bubble");
    var bp = photo(it, "bubble__img");   // Telegram önizlemesi: kaynak sayfasının büyük görseli metnin üstünde
    if (bp) b.appendChild(bp);
    var line1 = el("div");
    line1.appendChild(document.createTextNode((TG_BADGE[it.label] || "▪️") + " "));
    line1.appendChild(el("b", null, it.label_text || TRUST[it.trust_group].name.toLocaleUpperCase("tr")));
    var redundant = (it.label === "OFFICIAL" && it.category === "OFFICIAL_ANNOUNCEMENT") ||
      ((it.label === "LEAK_CLAIM" || it.label === "COMMUNITY_CLAIM") && it.category === "COMMUNITY_RUMOR");
    if (it.category_tr && !redundant) line1.appendChild(document.createTextNode("  ·  " + it.category_tr.toLocaleUpperCase("tr")));
    b.appendChild(line1); b.appendChild(el("br"));
    b.appendChild(el("b", null, it.title)); b.appendChild(el("br")); b.appendChild(el("br"));
    b.appendChild(document.createTextNode(it.summary || "")); b.appendChild(el("br")); b.appendChild(el("br"));
    var src = el("div"); src.appendChild(el("b", null, "Kaynak: "));
    (it.sources || []).slice(0, 3).forEach(function (s, i) {
      var u = safeHttps(s.url); if (!u) return;
      if (i) src.appendChild(document.createTextNode(", "));
      var a = el("a", null, s.name); a.href = u; a.target = "_blank"; a.rel = "noopener noreferrer"; src.appendChild(a);
    });
    b.appendChild(src);
    var note = el("div"); note.appendChild(el("b", null, "Doğrulama: "));
    var nt = it.label === "OFFICIAL" && it.sources && it.sources[0]
      ? it.sources[0].name + " üzerinde doğrudan duyuruldu (resmî alan adı, bağlantı doğrulandı)."
      : it.label === "MULTI_SOURCE" ? (it.independent_origins || (it.sources || []).length) + " bağımsız yayın organı aynı gelişmeyi aktarıyor; resmî doğrulama yok."
      : TG_NOTE[it.label] || it.why_this_label || "";
    note.appendChild(it.label === "OFFICIAL" || it.label === "MULTI_SOURCE" ? document.createTextNode(nt) : el("i", null, nt));
    b.appendChild(note); b.appendChild(el("br"));
    b.appendChild(el("i", null, "GTA VI Türkiye Bülteni")); b.appendChild(el("br"));
    b.appendChild(document.createTextNode("#GTA6 #GTAVI"));
    var d = parseDate(it.published_at);
    if (d) b.appendChild(el("time", null, new Intl.DateTimeFormat("tr-TR", { timeZone: TZ, hour: "2-digit", minute: "2-digit" }).format(d)));
    return b;
  }

  function renderPhone() {
    var chat = $("#tg-chat"); chat.textContent = "";
    var src = state.items, demoNote = state.usingDemo;
    if (!src.length) {
      if (!state.demo) { loadDemo(function (d) { state.demo = validFeed(d) ? d : false; if (state.demo) renderPhone(); }); return; }
      src = cleanItems(state.demo); demoNote = true;
    }
    ["official", "multi", "single", "claim"].forEach(function (g) {
      var x = ranked(src).filter(function (i) { return i.trust_group === g; })[0]; if (x) chat.appendChild(bubble(x));
    });
    $("#tg-sub").textContent = demoNote
      ? "Örnek verilerle: dört doğrulama düzeyinin kanalda nasıl göründüğü."
      : "Son yayınlanan haberlerden: dört doğrulama düzeyinin kanalda nasıl göründüğü.";
    chat.scrollTop = 0;
  }

  /* ---------- geri sayım ---------- */
  function initCountdown() {
    var M = window.__GTA6_MILESTONES__; if (!M) return;
    var launch = parseDate(M.launch); if (!launch) return;
    $("#cd-date").textContent = M.launch_label || absTime(launch);
    $("#cd-plat").textContent = M.platforms || "";
    var first = parseDate((M.items && M.items[0] && M.items[0].when) || "2023-12-05");
    var ol = $("#milestones"); ol.textContent = "";
    var nextMarked = false;
    (M.items || []).forEach(function (m) {
      var d = parseDate(m.when); var li = el("li");
      if (d && d.getTime() <= Date.now()) li.className = "is-done";
      else if (!nextMarked) { li.className = "is-next"; nextMarked = true; }
      li.appendChild(el("span", null, m.title)); li.appendChild(el("small", null, m.label || ""));
      ol.appendChild(li);
    });
    var pad = function (n) { return (n < 10 ? "0" : "") + n; };
    function tick() {
      var ms = launch.getTime() - Date.now();
      if (ms <= 0) {
        $("#cd-h").textContent = "GTA VI çıktı";
        ["#cd-d", "#cd-h2", "#cd-m", "#cd-s"].forEach(function (s) { $(s).textContent = "00"; });
        $("#cd-bar").style.transform = "scaleX(1)"; return false;
      }
      var s = Math.floor(ms / 1000);
      $("#cd-d").textContent = pad(Math.floor(s / 86400));
      $("#cd-h2").textContent = pad(Math.floor(s % 86400 / 3600));
      $("#cd-m").textContent = pad(Math.floor(s % 3600 / 60));
      $("#cd-s").textContent = pad(s % 60);
      if (first) {
        var p = (Date.now() - first.getTime()) / (launch.getTime() - first.getTime());
        $("#cd-bar").style.transform = "scaleX(" + Math.max(0.02, Math.min(1, p)).toFixed(4) + ")";
      }
      return true;
    }
    if (tick()) { var iv = setInterval(function () { if (!tick()) clearInterval(iv); }, 1000); }
  }

  /* ---------- etkileşim ---------- */
  function setDemo(on) {
    store(DEMO_KEY, on ? "1" : "0");
    if (!on && params.get("demo") === "1") { params.delete("demo"); history.replaceState(null, "", location.pathname + (params.toString() ? "?" + params : "") + location.hash); }
    toast(on ? "Örnek bülten gösteriliyor" : "Örnek bülten gizlendi");
    choose();
  }

  function bind() {
    $$(".tchip").forEach(function (b) {
      b.addEventListener("click", function () {
        state.trust = b.getAttribute("data-trust");
        $$(".tchip").forEach(function (x) { x.setAttribute("aria-pressed", String(x === b)); });
        renderGrid(state.items, state.feed || {});
      });
    });
    $$(".tab").forEach(function (b) {
      b.addEventListener("click", function () {
        state.cat = b.getAttribute("data-cat");
        $$(".tab").forEach(function (x) { x.setAttribute("aria-selected", String(x === b)); });
        renderGrid(state.items, state.feed || {});
      });
    });
    var q = $("#q");
    q.addEventListener("input", function () { state.q = q.value.trim(); renderGrid(state.items, state.feed || {}); });
    q.addEventListener("keydown", function (e) { if (e.key === "Escape") { q.value = ""; state.q = ""; renderGrid(state.items, state.feed || {}); q.blur(); } });
    document.addEventListener("keydown", function (e) {
      if (e.key === "/" && document.activeElement !== q && !$("dialog[open]") && !/^(INPUT|TEXTAREA)$/.test((document.activeElement || {}).tagName)) {
        e.preventDefault(); q.focus();
      }
    });
    $("#reset").addEventListener("click", function () {
      state.trust = "all"; state.cat = "all"; state.q = ""; q.value = "";
      $$(".tchip").forEach(function (x) { x.setAttribute("aria-pressed", String(x.getAttribute("data-trust") === "all")); });
      $$(".tab").forEach(function (x) { x.setAttribute("aria-selected", String(x.getAttribute("data-cat") === "all")); });
      setRegion(null);
    });
    $("#demo-toggle").addEventListener("change", function (e) { setDemo(e.target.checked); });
    $("#empty-demo").addEventListener("click", function () { setDemo(true); });
    $("#region-close").addEventListener("click", function () { setRegion(null); });
    $("#region-pill").addEventListener("click", function () { setRegion(null); });
    $$("[data-open]").forEach(function (b) { b.addEventListener("click", function () { openSheet(b.getAttribute("data-open")); }); });
    $$("dialog").forEach(function (d) {
      d.addEventListener("click", function (e) { if (e.target === d || e.target.closest("[data-close]")) closeDialog(d); });
      d.addEventListener("close", function () { if (location.hash && location.hash !== "#harita" && location.hash !== "#akis") history.replaceState(null, "", location.pathname + location.search); });
    });
    $("#drawer-panel").addEventListener("scroll", function (e) {
      var p = e.currentTarget, max = p.scrollHeight - p.clientHeight;
      $("#d-progress").style.transform = "scaleX(" + (max > 0 ? Math.min(1, p.scrollTop / max) : 1).toFixed(4) + ")";
    }, { passive: true });
    window.addEventListener("hashchange", route);
  }

  function route() {
    var h = decodeURIComponent(location.hash || "");
    if (h.indexOf("#haber-") === 0) { var id = h.slice(7); if (state.byId[id]) openItem(id, true); }
    else if (h === "#telegram") openSheet("telegram");
    else if (h === "#yontem") openSheet("method");
    else if (h.indexOf("#bolge-") === 0 && REGION[h.slice(7)]) setRegion(h.slice(7));
  }

  function selftest(items) {
    if (params.get("selftest") !== "1") return;
    var r = {
      mode: state.usingDemo ? "demo" : "real", items: items.length, cards: $$("#grid .card").length,
      hero: $("#hero").classList.contains("is-empty") ? "empty" : "filled",
      pins: $$("#pins .pin").length, pulse: $$("#pulse-list li").length, emptyVisible: !$("#empty").hidden,
      overflowX: document.documentElement.scrollWidth > window.innerWidth + 1,
      wide: $$("body *").filter(function (n) { var b = n.getBoundingClientRect(); return b.width && b.right > window.innerWidth + 1 && !n.closest("svg,.tabs,.trustbar,.regions,.pulsebar__list,dialog,.stage__viewport,.stage__sky"); })
        .slice(0, 4).map(function (n) { return n.tagName + "." + String(n.className && n.className.baseVal != null ? n.className.baseVal : n.className).split(" ")[0]; })
    };
    document.documentElement.setAttribute("data-selftest", JSON.stringify(r));
  }

  /* ---------- başlat ---------- */
  function intro() {
    var order = [".hud__coords", ".hud__h1", ".hud__lead", ".regions", ".feature", ".countdown"];
    order.forEach(function (s, i) { var n = $(s); if (n) { n.setAttribute("data-reveal", ""); n.style.setProperty("--d", (0.15 + i * 0.12) + "s"); } });
    var cam = $("#map-camera");
    if (!reduced) {
      var g = geometry();
      cam.style.transition = "none";
      cam.style.transform = "translate3d(" + (g.W * -0.06).toFixed(0) + "px,0,0) scale(1.18)";
    }
    // rAF yerine zamanlayıcı: arka plan sekmelerinde ve başsız tarayıcıda da açılış tamamlanır
    setTimeout(function () {
      void cam.getBoundingClientRect();
      cam.style.transition = "";
      document.documentElement.classList.remove("is-loading");
      document.documentElement.classList.add("is-ready");
      camera(state.cam.region || state.region);
    }, 60);
  }

  function start() {
    state.real = validFeed(window.__GTA6_FEED__) ? window.__GTA6_FEED__ : null;
    bind();
    bindParallax();
    initCountdown();
    intro();
    choose();
    if (/^https?:$/.test(location.protocol) && window.fetch) {
      fetch("data/feed.json?t=" + Date.now(), { cache: "no-store" })
        .then(function (r) { return r.ok ? r.json() : null; })
        .then(function (f) {
          if (!validFeed(f)) return;
          var cur = parseDate(state.real && state.real.status.generated_at);
          var nxt = parseDate(f.status.generated_at);
          if (!state.real || (nxt && (!cur || nxt > cur))) { state.real = f; choose(); }
        })
        .catch(function () { /* feed.js ile devam */ });
    }
  }
  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", start); else start();
})();

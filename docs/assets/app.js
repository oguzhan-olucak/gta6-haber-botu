/* GTA VI Türkiye Bülteni — istemci.
 * Kurallar (.claude/skills/ui-ux-interaction-standards): veri yalnızca textContent ile yazılır,
 * yalnızca https bağlantılar kullanılır, satır içi betik/innerHTML yok, gerçek veri her zaman
 * örnek bültenin önündedir. Boş akış ve eski şema (status.sources yok) desteklenir.
 */
(function () {
  "use strict";

  var TRUST = {
    official: { name: "Resmî Açıklama", short: "Resmî" },
    multi: { name: "Çoklu Kaynak Doğrulamalı", short: "Çoklu Kaynak" },
    single: { name: "Tek Kaynak", short: "Tek Kaynak" },
    claim: { name: "Topluluk / Sızıntı", short: "Topluluk / Sızıntı" }
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

  var $ = function (s, r) { return (r || document).querySelector(s); };
  var $$ = function (s, r) { return Array.prototype.slice.call((r || document).querySelectorAll(s)); };
  var params = new URLSearchParams(location.search);

  var state = {
    real: null, demo: null, feed: null, usingDemo: false,
    trust: "all", cat: "all", q: "", byId: {}
  };

  /* ---------- yardımcılar ---------- */
  function el(tag, cls, text) {
    var n = document.createElement(tag);
    if (cls) n.className = cls;
    if (text != null) n.textContent = String(text);
    return n;
  }
  function svgIcon(paths) {
    var ns = "http://www.w3.org/2000/svg";
    var s = document.createElementNS(ns, "svg");
    s.setAttribute("viewBox", "0 0 24 24");
    s.setAttribute("aria-hidden", "true");
    paths.forEach(function (d) { var p = document.createElementNS(ns, "path"); p.setAttribute("d", d); s.appendChild(p); });
    return s;
  }
  var ICON_SEND = ["M21 3 3 10.5l6.5 2.5L12 20l3-6.5L21 3z", "M9.5 13 21 3"];
  var ICON_COPY = ["M9 9h10v10H9z", "M5 15V5h10"];
  var ICON_OK = ["M5 12.5l4.5 4.5L19 7"];

  function safeHttps(u) {
    try { var x = new URL(String(u)); return x.protocol === "https:" ? x.href : null; } catch (e) { return null; }
  }
  function domain(u) { try { return new URL(u).hostname.replace(/^www\./, ""); } catch (e) { return ""; } }
  function store(k, v) { try { if (v == null) localStorage.removeItem(k); else localStorage.setItem(k, v); } catch (e) { /* gizli mod */ } }
  function load(k) { try { return localStorage.getItem(k); } catch (e) { return null; } }
  function trTitle(s) { return String(s || "").toLocaleLowerCase("tr").replace(/(^|\s)\S/g, function (m) { return m.toLocaleUpperCase("tr"); }); }
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
  function permalink(it) { return location.origin + location.pathname + "#haber-" + it.id; }
  function shareUrl(it) {
    return "https://t.me/share/url?url=" + encodeURIComponent(permalink(it)) + "&text=" + encodeURIComponent(it.title || "");
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
    if (navigator.clipboard && window.isSecureContext) {
      navigator.clipboard.writeText(text).then(done, function () { fallback(); });
    } else { fallback(); }
    function fallback() {
      var ta = el("textarea"); ta.value = text; ta.setAttribute("readonly", ""); ta.style.position = "fixed"; ta.style.opacity = "0";
      document.body.appendChild(ta); ta.select();
      try { document.execCommand("copy"); done(); } catch (e) { toast("Kopyalanamadı; bağlantı: " + text); }
      ta.remove();
    }
  }

  /* ---------- veri ---------- */
  function validFeed(f) { return f && typeof f === "object" && Array.isArray(f.items) && f.status && typeof f.status === "object"; }
  function cleanItems(f) {
    return f.items.filter(function (it) { return it && it.id && it.title && TRUST[it.trust_group]; });
  }
  function ranked(items) {
    return items.slice().sort(function (a, b) {
      return (TRUST_ORDER[a.trust_group] - TRUST_ORDER[b.trust_group])
        || ((b.source_strength || 0) - (a.source_strength || 0))
        || ((parseDate(b.published_at) || 0) - (parseDate(a.published_at) || 0));
    });
  }
  function heroOf(f, items) {
    var byId = {}; items.forEach(function (i) { byId[i.id] = i; });
    if (f.hero_id && byId[f.hero_id]) return byId[f.hero_id];
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
    var wantDemo = !realItems.length && (load(DEMO_KEY) === "1" || params.get("demo") === "1");
    if (wantDemo && !state.demo) {
      loadDemo(function (d) { state.demo = validFeed(d) ? d : null; if (!state.demo) store(DEMO_KEY, null); choose(); });
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
    state.byId = {}; items.forEach(function (i) { state.byId[i.id] = i; });
    renderRibbon(f, items);
    renderHero(f, items);
    renderPulse(f);
    renderCounts(items);
    renderGrid(items, f);
    renderMethodNote(f);
    document.documentElement.classList.toggle("is-demo", state.usingDemo);
    selftest(items);
    route();
  }

  function renderRibbon(f, items) {
    var s = f.status || {};
    var pulse = $("#st-pulse"); pulse.className = "pulse";
    var last = parseDate(s.last_run_at);
    var stale = last && (Date.now() - last.getTime() > 3 * 3600 * 1000);
    var label;
    if (!validFeed(state.real) && !state.usingDemo) { label = "Bülten verisi okunamadı"; pulse.classList.add("is-error"); }
    else if (s.paused) { label = "Yayın duraklatıldı"; pulse.classList.add("is-paused"); }
    else if (stale && !state.usingDemo) { label = "Son tarama gecikmeli"; pulse.classList.add("is-stale"); }
    else { label = state.usingDemo ? "Örnek bülten" : "Canlı"; }
    $("#st-state").textContent = label;
    $("#st-updated").textContent = last ? "Son tarama " + relTime(last) : "";
    $("#st-sources").textContent = s.active_sources ? (s.sources_ok_last_run || 0) + "/" + s.active_sources + " kaynak yanıt verdi" : "";
    $("#st-total").textContent = items.length ? items.length + " doğrulanmış haber" : "";
    $("#st-demo").hidden = !state.usingDemo;
  }

  function badge(group) { return el("span", "badge badge--" + group, TRUST[group].name); }

  function renderHero(f, items) {
    var box = $("#hero"); box.textContent = "";
    var h = heroOf(f, items);
    box.classList.toggle("is-empty", !h);
    if (!h) {
      box.removeAttribute("tabindex"); box.removeAttribute("role"); box.onclick = null; box.onkeydown = null;
      var k = el("div", "feature__kicker"); k.appendChild(el("span", "feature__label", "Bülten hazır"));
      box.appendChild(k);
      box.appendChild(el("h1", "feature__title", "İlk doğrulanmış haber yolda"));
      var srcN = (f.status && f.status.active_sources) || 0;
      box.appendChild(el("p", "feature__summary", (srcN ? srcN + " kaynak" : "Kaynaklar") +
        " düzenli olarak taranıyor. Bir gelişme resmî ya da bağımsız kaynaklarla doğrulandığında burada ve Telegram kanalında yayınlanır."));
      var a = el("div", "feature__actions");
      var b = el("button", "btn btn--glow", "Örnek bülteni göster"); b.type = "button";
      b.addEventListener("click", function () { setDemo(true); });
      var m = el("button", "btn", "Nasıl doğruluyoruz"); m.type = "button";
      m.addEventListener("click", function () { openModal("method"); });
      a.appendChild(b); a.appendChild(m); box.appendChild(a);
      return;
    }
    var kick = el("div", "feature__kicker");
    kick.appendChild(el("span", "feature__label", state.usingDemo ? "Örnek manşet" : "Öne çıkan"));
    kick.appendChild(badge(h.trust_group));
    if (h.category_tr) kick.appendChild(el("span", "cat", h.category_tr));
    box.appendChild(kick);
    box.appendChild(el("h1", "feature__title", h.title));
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
    var share = el("a", "btn", "Telegram'da paylaş"); share.href = shareUrl(h); share.target = "_blank"; share.rel = "noopener noreferrer";
    share.addEventListener("click", function (e) { e.stopPropagation(); });
    act.appendChild(open); act.appendChild(share); box.appendChild(act);
    box.onclick = function () { openItem(h.id); };
  }

  function renderPulse(f) {
    var s = f.status || {};
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
      li.title = x.name + ": " + stTxt + (x.relevant ? " · " + x.relevant + " ilgili" : "");
      list.appendChild(li);
    });
    var sum;
    if (srcs.length) sum = ok + "/" + srcs.length + " kaynak yanıt verdi · son taramada " + relevant + " ilgili kayıt";
    else if (s.active_sources) sum = (s.sources_ok_last_run || 0) + "/" + s.active_sources + " kaynak son taramada yanıt verdi";
    else sum = "Kaynak durumu ilk taramadan sonra görünür.";
    $("#pulse-sum").textContent = sum;
    list.hidden = !srcs.length;
  }

  function matches(it) {
    if (state.trust !== "all" && it.trust_group !== state.trust) return false;
    if (state.cat !== "all") {
      var ok = it.category === state.cat || (state.cat === "COMMUNITY_RUMOR" && it.trust_group === "claim");
      if (!ok) return false;
    }
    if (state.q) {
      var hay = fold([it.title, it.summary, it.category_tr, (it.sources || []).map(function (s) { return s.name + " " + domain(s.url); }).join(" ")].join(" "));
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

  function card(it, wide) {
    var c = el("article", "card card--" + it.trust_group + (wide ? " card--wide" : ""));
    c.id = "haber-" + it.id;
    var top = el("div", "card__top");
    top.appendChild(badge(it.trust_group));
    var info = el("span", "card__info");
    if (it.category_tr) info.appendChild(el("span", null, it.category_tr));
    info.appendChild(el("span", null, readMins(it) + " dk okuma"));
    top.appendChild(info);
    c.appendChild(top);
    var h = el("h3", "card__title");
    var open = el("button", "card__open", it.title); open.type = "button";
    open.addEventListener("click", function () { openItem(it.id); });
    h.appendChild(open); c.appendChild(h);
    if (it.summary) c.appendChild(el("p", "card__summary", it.summary));
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
    c.appendChild(srcBox);
    var foot = el("div", "card__foot");
    var d = parseDate(it.published_at);
    var t = el("time", "card__time", d ? relTime(d) : ""); if (d) { t.dateTime = it.published_at; t.title = absTime(d); }
    foot.appendChild(t);
    var acts = el("div", "card__actions");
    var sh = el("a", "iconbtn"); sh.href = shareUrl(it); sh.target = "_blank"; sh.rel = "noopener noreferrer";
    sh.setAttribute("aria-label", "Telegram'da paylaş: " + it.title); sh.title = "Telegram'da paylaş"; sh.appendChild(svgIcon(ICON_SEND));
    var cp = el("button", "iconbtn"); cp.type = "button"; cp.setAttribute("aria-label", "Bağlantıyı kopyala: " + it.title); cp.title = "Bağlantıyı kopyala";
    cp.appendChild(svgIcon(ICON_COPY));
    cp.addEventListener("click", function () { copy(permalink(it), cp); });
    acts.appendChild(sh); acts.appendChild(cp); foot.appendChild(acts);
    c.appendChild(foot);
    return c;
  }

  function renderGrid(items, f) {
    var grid = $("#grid"); grid.textContent = "";
    var empty = $("#empty"), nomatch = $("#nomatch");
    var filtering = state.trust !== "all" || state.cat !== "all" || state.q;
    empty.hidden = items.length > 0;
    if (!items.length) {
      nomatch.hidden = true;
      $("#feed-title").textContent = "Son haberler";
      $("#result-line").textContent = "";
      $("#empty-text").textContent = !validFeed(state.real)
        ? "Bülten verisi şu an okunamıyor. Sayfayı birkaç dakika sonra yenileyin."
        : "Kaynaklar taranıyor; doğrulanan ilk haber burada otomatik olarak görünür. Bu arada bültenin dolu hâlini örnek verilerle inceleyebilirsiniz.";
      $("#demo-toggle").checked = false;
      return;
    }
    var hero = heroOf(f, items);
    var list = ranked(items).filter(function (i) { return filtering || !hero || i.id !== hero.id; });
    list.sort(function (a, b) { return (parseDate(b.published_at) || 0) - (parseDate(a.published_at) || 0); });
    var shown = list.filter(matches);
    nomatch.hidden = shown.length > 0;
    var frag = document.createDocumentFragment();
    shown.forEach(function (it, i) { frag.appendChild(card(it, !filtering && i < 2)); });
    grid.appendChild(frag);
    $("#feed-title").textContent = state.usingDemo ? "Örnek bülten" : "Son haberler";
    $("#result-line").textContent = filtering ? shown.length + " haber eşleşti" : items.length + " doğrulanmış haber · en yenisi üstte";
  }

  function renderMethodNote(f) {
    var s = f.status || {};
    $("#m-sub").textContent = (s.active_sources ? s.active_sources + " kaynak, " : "") + "altı adım, tek kural: etiket kanıtla belirlenir.";
    $("#m-note").textContent = s.measurement_note || "";
  }

  /* ---------- çekmece ve modallar ---------- */
  function openItem(id, fromHash) {
    var it = state.byId[id]; if (!it) return;
    var b = $("#d-badges"); b.textContent = ""; b.appendChild(badge(it.trust_group));
    if (it.category_tr) b.appendChild(el("span", "cat", it.category_tr));
    $("#d-title").textContent = it.title;
    var d = parseDate(it.published_at);
    $("#d-meta").textContent = (d ? absTime(d) + " · " : "") + readMins(it) + " dk okuma";
    $("#d-summary").textContent = it.summary || "";
    $("#d-why").textContent = it.why_this_label || TRUST[it.trust_group].name;
    var st = Math.max(0, Math.min(100, Number(it.source_strength) || 0));
    $("#d-strength").textContent = st + "/100";
    $("#d-strength-bar").style.width = st + "%";
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
    if (!fromHash) history.replaceState(null, "", "#haber-" + it.id);
    showDialog($("#drawer"));
  }

  function showDialog(dlg) {
    if (dlg.open) return;
    if (typeof dlg.showModal === "function") dlg.showModal(); else dlg.setAttribute("open", "");
  }
  function closeDialog(dlg) {
    if (typeof dlg.close === "function") dlg.close(); else dlg.removeAttribute("open");
  }

  function openModal(name) {
    if (name === "telegram") { renderPhone(); showDialog($("#telegram")); history.replaceState(null, "", "#telegram"); }
    if (name === "method") { showDialog($("#method")); history.replaceState(null, "", "#yontem"); }
  }

  function bubble(it) {
    var b = el("div", "bubble");
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
    var items = Object.keys(state.byId).map(function (k) { return state.byId[k]; });
    var src = items, demoNote = false;
    if (!items.length) {
      if (!state.demo) { loadDemo(function (d) { state.demo = validFeed(d) ? d : null; if (state.demo) renderPhone(); }); return; }
      src = cleanItems(state.demo); demoNote = true;
    } else if (state.usingDemo) { demoNote = true; }
    var pick = [];
    ["official", "multi", "single", "claim"].forEach(function (g) {
      var x = ranked(src).filter(function (i) { return i.trust_group === g; })[0]; if (x) pick.push(x);
    });
    pick.forEach(function (it) { chat.appendChild(bubble(it)); });
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
      var box = el("span"); box.appendChild(el("b", null, m.title)); box.appendChild(el("small", null, m.label || "")); li.appendChild(box);
      ol.appendChild(li);
    });
    var pad = function (n) { return (n < 10 ? "0" : "") + n; };
    function tick() {
      var ms = launch.getTime() - Date.now();
      if (ms <= 0) {
        $("#cd-h").textContent = "GTA VI çıktı";
        ["#cd-d", "#cd-h2", "#cd-m", "#cd-s"].forEach(function (s) { $(s).textContent = "0"; });
        $("#cd-bar").style.width = "100%"; return false;
      }
      var s = Math.floor(ms / 1000);
      $("#cd-d").textContent = String(Math.floor(s / 86400));
      $("#cd-h2").textContent = pad(Math.floor(s % 86400 / 3600));
      $("#cd-m").textContent = pad(Math.floor(s % 3600 / 60));
      $("#cd-s").textContent = pad(s % 60);
      if (first) {
        var p = (Date.now() - first.getTime()) / (launch.getTime() - first.getTime());
        $("#cd-bar").style.width = Math.max(2, Math.min(100, p * 100)).toFixed(1) + "%";
      }
      return true;
    }
    if (tick()) { var iv = setInterval(function () { if (!tick()) clearInterval(iv); }, 1000); }
  }

  /* ---------- etkileşim ---------- */
  function setDemo(on) {
    store(DEMO_KEY, on ? "1" : null);
    if (!on && params.get("demo") === "1") { params.delete("demo"); history.replaceState(null, "", location.pathname + (params.toString() ? "?" + params : "") + location.hash); }
    if (on) toast("Örnek bülten gösteriliyor");
    choose();
  }

  function bind() {
    $$(".tchip").forEach(function (b) {
      b.addEventListener("click", function () {
        state.trust = b.getAttribute("data-trust");
        $$(".tchip").forEach(function (x) { x.setAttribute("aria-pressed", String(x === b)); });
        render();
      });
    });
    $$(".tab").forEach(function (b) {
      b.addEventListener("click", function () {
        state.cat = b.getAttribute("data-cat");
        $$(".tab").forEach(function (x) { x.setAttribute("aria-selected", String(x === b)); });
        render();
      });
    });
    var q = $("#q");
    q.addEventListener("input", function () { state.q = q.value.trim(); render(); });
    q.addEventListener("keydown", function (e) { if (e.key === "Escape") { q.value = ""; state.q = ""; render(); q.blur(); } });
    document.addEventListener("keydown", function (e) {
      if (e.key === "/" && document.activeElement !== q && !$("dialog[open]") && !/^(INPUT|TEXTAREA)$/.test((document.activeElement || {}).tagName)) {
        e.preventDefault(); q.focus();
      }
    });
    $("#reset").addEventListener("click", function () {
      state.trust = "all"; state.cat = "all"; state.q = ""; q.value = "";
      $$(".tchip").forEach(function (x) { x.setAttribute("aria-pressed", String(x.getAttribute("data-trust") === "all")); });
      $$(".tab").forEach(function (x) { x.setAttribute("aria-selected", String(x.getAttribute("data-cat") === "all")); });
      render();
    });
    $("#demo-toggle").addEventListener("change", function (e) { setDemo(e.target.checked); });
    $("#st-demo").addEventListener("click", function () { setDemo(false); });
    $$("[data-open]").forEach(function (b) { b.addEventListener("click", function () { openModal(b.getAttribute("data-open")); }); });
    $$("dialog").forEach(function (d) {
      d.addEventListener("click", function (e) { if (e.target === d || e.target.closest("[data-close]")) closeDialog(d); });
      d.addEventListener("close", function () { if (location.hash) history.replaceState(null, "", location.pathname + location.search); });
    });
    window.addEventListener("hashchange", route);
  }

  function route() {
    var h = decodeURIComponent(location.hash || "");
    if (h.indexOf("#haber-") === 0) { var id = h.slice(7); if (state.byId[id]) openItem(id, true); }
    else if (h === "#telegram") openModal("telegram");
    else if (h === "#yontem") openModal("method");
  }

  function selftest(items) {
    if (params.get("selftest") !== "1") return;
    var r = {
      mode: state.usingDemo ? "demo" : "real", items: items.length, cards: $$("#grid .card").length,
      hero: $("#hero").classList.contains("is-empty") ? "empty" : "filled",
      pulse: $$("#pulse-list li").length, emptyVisible: !$("#empty").hidden,
      overflowX: document.documentElement.scrollWidth > window.innerWidth + 1
    };
    document.documentElement.setAttribute("data-selftest", JSON.stringify(r));
  }

  /* ---------- başlat ---------- */
  function start() {
    state.real = validFeed(window.__GTA6_FEED__) ? window.__GTA6_FEED__ : null;
    bind();
    initCountdown();
    choose();
    // Yayındaki sitede önbellekten bağımsız en güncel veriyi çek (file:// üzerinde atlanır).
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

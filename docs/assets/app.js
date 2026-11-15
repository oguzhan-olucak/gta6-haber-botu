/* GTA VI Türkiye Bülteni — istemci tarafı.
   Güvenlik: veri hiçbir zaman innerHTML ile basılmaz; tüm metinler textContent, tüm bağlantılar
   https:// denetiminden geçer. Sayfa CSP ile yalnızca kendi betiklerini çalıştırır. */
(function () {
  "use strict";

  var TRUST_CLASS = { official: "official", multi: "multi", single: "single", claim: "claim" };
  var REFRESH_MS = 5 * 60 * 1000;
  var state = { feed: null, trust: "all", cat: "all", q: "" };
  var $ = function (sel) { return document.querySelector(sel); };

  // ---- yardımcılar ------------------------------------------------------------------
  function el(tag, cls, text) {
    var n = document.createElement(tag);
    if (cls) n.className = cls;
    if (text !== undefined && text !== null) n.textContent = String(text);
    return n;
  }
  function safeHttps(url) {
    if (typeof url !== "string") return null;
    try {
      var u = new URL(url);
      return u.protocol === "https:" ? u.href : null;
    } catch (e) { return null; }
  }
  function fold(s) {
    return String(s || "").toLocaleLowerCase("tr").normalize("NFD").replace(/[̀-ͯ]/g, "")
      .replace(/ı/g, "i");
  }
  var rtf = (typeof Intl !== "undefined" && Intl.RelativeTimeFormat) ? new Intl.RelativeTimeFormat("tr", { numeric: "auto" }) : null;
  var dtf = new Intl.DateTimeFormat("tr-TR", { day: "numeric", month: "long", hour: "2-digit", minute: "2-digit", timeZone: "Europe/Istanbul" });
  function ago(iso, now) {
    var t = Date.parse(iso);
    if (isNaN(t)) return "";
    var diff = Math.round((t - now) / 60000);
    if (!rtf) return dtf.format(t);
    if (Math.abs(diff) < 60) return rtf.format(diff, "minute");
    if (Math.abs(diff) < 60 * 24) return rtf.format(Math.round(diff / 60), "hour");
    return rtf.format(Math.round(diff / 1440), "day");
  }
  function refNow() {
    // Demo verisinde göreli zamanlar beslemenin üretildiği ana göre hesaplanır.
    var f = state.feed;
    if (f && f.demo && f.status && f.status.generated_at) return Date.parse(f.status.generated_at);
    return Date.now();
  }
  function badge(item) {
    var b = el("span", "badge badge--" + (TRUST_CLASS[item.trust_group] || "single"), item.label_text);
    return b;
  }

  // ---- veri ----------------------------------------------------------------------------
  function validFeed(f) {
    return f && typeof f === "object" && Array.isArray(f.items) && f.status && typeof f.status === "object";
  }
  function load() {
    var inline = window.__GTA6_FEED__;
    if (validFeed(inline)) setFeed(inline);
    if (location.protocol === "http:" || location.protocol === "https:") {
      fetch("data/feed.json", { cache: "no-store" })
        .then(function (r) { return r.ok ? r.json() : null; })
        .then(function (f) { if (validFeed(f)) setFeed(f); })
        .catch(function () { /* çevrimdışı: satır içi veriyle devam */ });
    }
    if (!validFeed(inline) && location.protocol === "file:") {
      $("#st-state").textContent = "Veri bulunamadı (data/feed.js)";
    }
  }
  function setFeed(f) {
    state.feed = f;
    renderStatus();
    renderHero();
    renderCounts();
    render();
    openFromHash();
  }

  // ---- durum bandı ------------------------------------------------------------------------
  function renderStatus() {
    var s = state.feed.status, now = refNow();
    var last = s.last_run_at || s.generated_at;
    var stale = last && (now - Date.parse(last)) > 3 * 3600 * 1000;
    var pulse = document.querySelector(".pulse");
    pulse.classList.toggle("is-paused", !!s.paused);
    pulse.classList.toggle("is-stale", !s.paused && !!stale);
    $("#st-state").textContent = s.paused ? "Bot duraklatıldı" : stale ? "Bot gecikmeli" : "Bot çalışıyor";
    $("#st-updated").textContent = last ? "Son güncelleme " + dtf.format(Date.parse(last)) : "";
    $("#st-sources").textContent = (s.sources_ok_last_run || 0) + "/" + (s.active_sources || 0) + " kaynak yanıt verdi";
    $("#st-total").textContent = (s.verified_total || 0) + " doğrulanmış haber";
    $("#st-demo").hidden = !state.feed.demo;
    if (state.feed.demo) $("#st-demo").title = "Bu içerik örnektir; bot ilk çalıştığında gerçek haberlerle değişir.";
    $("#measure-note").textContent = s.measurement_note || "";
  }

  // ---- manşet -------------------------------------------------------------------------------
  function renderHero() {
    var f = state.feed, hero = $("#hero");
    var item = f.items.filter(function (i) { return i.id === f.hero_id; })[0] || f.items[0];
    hero.replaceChildren();
    if (!item) { hero.hidden = true; return; }
    var body = el("div", "hero__body");
    var kicker = el("div", "hero__kicker");
    kicker.append(badge(item), el("span", "cat", item.category_tr));
    var title = el("h1", "hero__title", item.title);
    body.append(kicker, title, el("p", "hero__summary", item.summary),
      el("p", "hero__meta", ago(item.published_at, refNow()) + " · " + item.sources.map(function (s) { return s.name; }).join(", ")));
    hero.append(body, el("div", "hero__art"));
    hero.hidden = false;
    hero.tabIndex = 0;
    hero.setAttribute("role", "button");
    hero.setAttribute("aria-label", "Manşet: " + item.title + " — ayrıntıları aç");
    hero.onclick = function () { openDrawer(item); };
    hero.onkeydown = function (e) { if (e.key === "Enter" || e.key === " ") { e.preventDefault(); openDrawer(item); } };
  }

  // ---- akış ---------------------------------------------------------------------------------
  function matches(item) {
    if (state.trust !== "all" && item.trust_group !== state.trust) return false;
    if (state.cat !== "all" && item.category !== state.cat) return false;
    if (state.q) {
      var hay = fold(item.title + " " + item.summary + " " + item.category_tr + " " +
        item.sources.map(function (s) { return s.name; }).join(" "));
      var terms = fold(state.q).split(/\s+/).filter(Boolean);
      for (var i = 0; i < terms.length; i++) if (hay.indexOf(terms[i]) === -1) return false;
    }
    return true;
  }
  function renderCounts() {
    var items = state.feed.items, counts = { all: items.length, official: 0, multi: 0, single: 0, claim: 0 };
    items.forEach(function (i) { if (counts[i.trust_group] !== undefined) counts[i.trust_group]++; });
    document.querySelectorAll("[data-count]").forEach(function (n) { n.textContent = counts[n.getAttribute("data-count")]; });
  }
  function card(item, feature) {
    var c = el("button", "card card--" + (TRUST_CLASS[item.trust_group] || "single") + (feature ? " card--feature" : ""));
    c.type = "button";
    var top = el("div", "card__top");
    top.append(badge(item), el("span", "cat", item.category_tr));
    var meta = el("div", "card__meta");
    meta.append(el("span", null, ago(item.published_at, refNow())),
      el("span", null, item.sources.map(function (s) { return s.name; }).join(", ")));
    c.append(top, el("h3", "card__title", item.title), el("p", "card__summary", item.summary), meta);
    c.setAttribute("aria-label", item.label_text + ": " + item.title);
    c.addEventListener("click", function () { openDrawer(item); });
    return c;
  }
  function render() {
    var f = state.feed, grid = $("#grid");
    var filtering = state.trust !== "all" || state.cat !== "all" || state.q;
    var list = f.items.filter(matches);
    var featured = Array.isArray(f.featured_ids) ? f.featured_ids : [];
    if (!filtering) {
      // Vitrin: bot tarafından seçilen (önce doğrulanmış) iki haber başa, manşet akıştan çıkar.
      var feat = featured.map(function (id) { return list.filter(function (i) { return i.id === id; })[0]; })
        .filter(Boolean);
      list = feat.concat(list.filter(function (i) { return i.id !== f.hero_id && featured.indexOf(i.id) === -1; }));
    }
    grid.replaceChildren();
    list.forEach(function (item, idx) { grid.append(card(item, !filtering && idx < featured.length && featured.indexOf(item.id) !== -1)); });
    $("#empty").hidden = list.length > 0;
    $("#result-line").textContent = filtering ? list.length + " haber gösteriliyor" : "Son haberler";
  }

  // ---- detay çekmecesi --------------------------------------------------------------------
  var current = null;
  function openDrawer(item) {
    current = item;
    var d = $("#drawer");
    $("#d-badges").replaceChildren(badge(item), el("span", "cat", item.category_tr));
    $("#d-title").textContent = item.title;
    $("#d-meta").textContent = dtf.format(Date.parse(item.published_at)) + " · " + ago(item.published_at, refNow());
    $("#d-summary").textContent = item.summary;
    $("#d-why").textContent = item.why_this_label || "—";
    $("#d-strength").textContent = item.source_strength + "/100";
    $("#d-strength-bar").style.width = Math.max(0, Math.min(100, item.source_strength)) + "%";
    $("#d-origins").textContent = String(item.independent_origins);
    var ul = $("#d-sources");
    ul.replaceChildren();
    item.sources.forEach(function (s) {
      var href = safeHttps(s.url);
      if (!href) return;
      var a = el("a");
      a.href = href;
      a.target = "_blank";
      a.rel = "noopener noreferrer";
      a.append(el("span", null, s.name), el("small", null, new URL(href).hostname.replace(/^www\./, "")));
      var li = el("li");
      li.append(a);
      ul.append(li);
    });
    var tg = $("#d-telegram"), tgUrl = safeHttps(item.telegram_url);
    if (tgUrl) {
      tg.href = tgUrl;
      tg.textContent = "Telegram'da aç";
    } else {
      var first = item.sources[0] ? safeHttps(item.sources[0].url) : null;
      tg.href = "https://t.me/share/url?url=" + encodeURIComponent(first || location.href) + "&text=" + encodeURIComponent(item.title);
      tg.textContent = "Telegram'da paylaş";
    }
    if (location.hash !== "#haber-" + item.id) history.replaceState(null, "", "#haber-" + item.id);
    if (typeof d.showModal === "function") { if (!d.open) d.showModal(); } else { d.setAttribute("open", ""); }
  }
  function closeDrawer() {
    var d = $("#drawer");
    if (d.open) d.close();
    history.replaceState(null, "", location.pathname + location.search);
  }
  function openFromHash() {
    var m = /^#haber-([A-Za-z0-9_-]{4,64})$/.exec(location.hash);
    if (!m || !state.feed) return;
    var item = state.feed.items.filter(function (i) { return i.id === m[1]; })[0];
    if (item) openDrawer(item);
  }

  // ---- olaylar -----------------------------------------------------------------------------
  function bind() {
    document.querySelectorAll(".tchip").forEach(function (b) {
      b.addEventListener("click", function () {
        state.trust = b.getAttribute("data-trust");
        document.querySelectorAll(".tchip").forEach(function (x) { x.setAttribute("aria-pressed", String(x === b)); });
        render();
      });
    });
    document.querySelectorAll(".tab").forEach(function (t) {
      t.addEventListener("click", function () {
        state.cat = t.getAttribute("data-cat");
        document.querySelectorAll(".tab").forEach(function (x) { x.setAttribute("aria-selected", String(x === t)); });
        render();
      });
    });
    var timer = null;
    $("#q").addEventListener("input", function (e) {
      clearTimeout(timer);
      timer = setTimeout(function () { state.q = e.target.value.slice(0, 80); render(); }, 80);
    });
    $("#reset").addEventListener("click", function () {
      state.trust = "all"; state.cat = "all"; state.q = ""; $("#q").value = "";
      document.querySelectorAll(".tchip").forEach(function (x) { x.setAttribute("aria-pressed", String(x.getAttribute("data-trust") === "all")); });
      document.querySelectorAll(".tab").forEach(function (x) { x.setAttribute("aria-selected", String(x.getAttribute("data-cat") === "all")); });
      render();
    });
    $("#d-close").addEventListener("click", closeDrawer);
    $("#drawer").addEventListener("click", function (e) { if (e.target === e.currentTarget) closeDrawer(); });
    $("#drawer").addEventListener("close", function () { history.replaceState(null, "", location.pathname + location.search); });
    $("#d-copy").addEventListener("click", function () {
      if (!current) return;
      var url = location.href.split("#")[0] + "#haber-" + current.id, btn = $("#d-copy");
      var done = function () { btn.textContent = "Kopyalandı"; setTimeout(function () { btn.textContent = "Bağlantıyı kopyala"; }, 1600); };
      if (navigator.clipboard) navigator.clipboard.writeText(url).then(done, function () {}); else done();
    });
    window.addEventListener("hashchange", openFromHash);
  }

  bind();
  load();
  if (location.protocol === "http:" || location.protocol === "https:") setInterval(load, REFRESH_MS);
})();

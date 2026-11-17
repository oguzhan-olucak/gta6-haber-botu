/* Gelir bileşenleri: Telegram katılım çağrısı, sponsor şeridi, Lansman Kiti, destek bağlantısı.
 * Veri: data/monetization.js (bot, config/monetization.json'dan yalnızca ETKİN alanları yazar).
 * Güvenlik: metinler yalnızca textContent ile basılır; bağlantılar yalnızca https:// (ya da site içi göreli).
 * Örnek bülten modunda ve gerçek yapılandırma boşken tasarımı görmek için "Örnek" etiketli yer tutucular. */
(function () {
  "use strict";
  var REAL = window.__GTA6_MONETIZATION__ || {};
  var SAMPLE = {
    sample: true,
    telegram: { url: "reklam.html", handle: "@kanaliniz", cta: "Lansman haftası: her doğrulanmış haber ilk önce Telegram'da." },
    sponsor: { name: "Sponsor alanı", tagline: "Lansman haftası boyunca markanız burada · örnek görünüm", url: "reklam.html" },
    kit: {
      title: "Lansman Kiti", lead: "19 Kasım'a hazır mısın? Deneyimi gerçekten iyileştiren birkaç şey.",
      disclosure: "Örnek görünüm: ortaklık bağlantıları config/monetization.json dosyasından eklenir.",
      items: [
        { id: "ssd", title: "PS5 için M.2 NVMe SSD", why: "Oyunun ~210 GB olacağı iddia ediliyor; dahili alan hızla doluyor.", partner: "Mağaza", price_hint: "", url: "reklam.html", topics: ["boyut", "gb", "on yukleme", "ön yükleme"] },
        { id: "psn", title: "PSN cüzdan kodu (TL)", why: "Kartsız ön sipariş ve satın alma.", partner: "E-pin", price_hint: "", url: "reklam.html", topics: ["fiyat", "on siparis", "ön sipariş"] },
        { id: "dualsense", title: "DualSense kol", why: "Uzun oturumlar için yedek kol.", partner: "Mağaza", price_hint: "", url: "reklam.html", topics: ["kol", "oynanis"] },
        { id: "headset", title: "Oyuncu kulaklığı", why: "Vice City radyoları ve 3D ses.", partner: "Mağaza", price_hint: "", url: "reklam.html", topics: ["muzik", "radyo", "ses"] }
      ]
    }
  };

  function $(s) { return document.querySelector(s); }
  function el(tag, cls, text) { var e = document.createElement(tag); if (cls) e.className = cls; if (text != null) e.textContent = text; return e; }
  function safe(u) {
    if (u === "reklam.html") return u;
    try { var x = new URL(String(u)); return x.protocol === "https:" ? x.href : null; } catch (e) { return null; }
  }
  function fold(s) {
    return String(s || "").toLocaleLowerCase("tr").normalize("NFD").replace(/[̀-ͯ]/g, "")
      .replace(/ı/g, "i").replace(/[^a-z0-9 ]+/g, " ");
  }
  function link(a, u, sponsored) {
    var s = safe(u); if (!s) return false;
    a.href = s;
    if (s !== "reklam.html") { a.target = "_blank"; a.rel = sponsored ? "sponsored noopener" : "noopener"; }
    return true;
  }

  var current = REAL;

  function kitCard(i, mini) {
    var a = el("a", mini ? "kit-mini__item" : "kitcard glass");
    if (!link(a, i.url, true)) return null;
    if (!mini) a.appendChild(el("span", "kitcard__ico kitcard__ico--" + (i.id || "x"), ""));
    var body = el("span", mini ? null : "kitcard__body");
    body.appendChild(el("b", null, i.title));
    if (i.why) body.appendChild(el("span", null, i.why));
    var meta = [i.partner, i.price_hint].filter(Boolean).join(" · ");
    if (meta) body.appendChild(el("small", null, meta));
    a.appendChild(body);
    if (!mini) a.appendChild(el("span", "kitcard__go", "İncele"));
    return a;
  }

  function render(usingDemo) {
    var hasReal = REAL.telegram || REAL.sponsor || REAL.kit;
    current = (usingDemo && !hasReal) ? SAMPLE : REAL;
    var m = current;

    var pill = $("#tg-pill"), band = $("#tg-band");
    if (m.telegram && link(pill, m.telegram.url)) {
      pill.hidden = false;
      link($("#tg-band-link"), m.telegram.url);
      $("#tg-band-cta").textContent = m.telegram.cta || "";
      $("#tg-band-handle").textContent = m.telegram.handle || "Katıl";
      band.hidden = false;
    } else { pill.hidden = true; band.hidden = true; }

    var slot = $("#sponsor-slot"); slot.textContent = "";
    if (m.sponsor) {
      var a = el("a", "sponsorbar glass");
      if (link(a, m.sponsor.url, true)) {
        a.appendChild(el("span", "ad-tag", m.sample ? "Örnek · Sponsor" : "Sponsor"));
        a.appendChild(el("b", null, m.sponsor.name));
        if (m.sponsor.tagline) a.appendChild(el("span", "sponsorbar__tag", m.sponsor.tagline));
        a.appendChild(el("span", "sponsorbar__go", "→"));
        slot.appendChild(a); slot.hidden = false;
      }
    } else if (m.media_kit) {
      var h = el("a", "sponsor-house", "Bu alan lansman haftası sponsorlarına açık · Reklam ve işbirliği →");
      h.href = "reklam.html"; slot.appendChild(h); slot.hidden = false;
    } else { slot.hidden = true; }

    var kit = $("#kit"), grid = $("#kit-grid"); grid.textContent = "";
    if (m.kit && m.kit.items && m.kit.items.length && m.kit.disclosure) {
      $("#kit-h").textContent = m.kit.title || "Lansman Kiti";
      $("#kit-lead").textContent = m.kit.lead || "";
      $("#kit-disc").textContent = m.kit.disclosure;
      m.kit.items.forEach(function (i) { var c = kitCard(i, false); if (c) grid.appendChild(c); });
      kit.hidden = !grid.children.length;
    } else { kit.hidden = true; }

    var sw = $("#support-wrap");
    if (m.support && link($("#support-link"), m.support.url)) { $("#support-link").textContent = m.support.text; sw.hidden = false; }
    else if (sw) { sw.hidden = true; }
  }

  /* Haber metninde konusu geçen kit ürünleri (çekmecede bağlam içi öneri). */
  function related(text, limit) {
    var m = current; if (!m.kit || !m.kit.items || !m.kit.disclosure) return [];
    var hay = " " + fold(text) + " ";
    return m.kit.items.filter(function (i) {
      return (i.topics || []).some(function (t) { var f = fold(t).trim(); return f && hay.indexOf(" " + f) >= 0; });
    }).slice(0, limit || 2);
  }
  function fillRelated(box, list, text) {
    list.textContent = "";
    related(text).forEach(function (i) { var c = kitCard(i, true); if (c) list.appendChild(c); });
    box.hidden = !list.children.length;
  }

  window.GTA6Money = { render: render, related: related, fillRelated: fillRelated, data: function () { return current; } };
})();

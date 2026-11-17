/* Medya kiti: istatistikler bot beslemesinden (feed.js) canlı hesaplanır; uydurma sayı yok. */
(function () {
  "use strict";
  var f = window.__GTA6_FEED__ || { items: [], status: {} };
  var m = window.__GTA6_MONETIZATION__ || {};
  function $(s) { return document.getElementById(s); }
  var items = Array.isArray(f.items) ? f.items : [];
  var st = f.status || {};
  var week = Date.now() - 7 * 864e5;
  var recent = items.filter(function (i) { var t = Date.parse(i.published_at); return t && t >= week; }).length;
  var strong = items.filter(function (i) { return i.trust_group === "official" || i.trust_group === "multi"; }).length;
  $("s-total").textContent = String(st.verified_total != null ? st.verified_total : items.length);
  $("s-week").textContent = String(recent);
  $("s-sources").textContent = String(st.active_sources || "–");
  $("s-official").textContent = items.length ? Math.round(strong * 100 / items.length) + "%" : "–";
  var mk = m.media_kit || {};
  if (mk.price_note) $("price-note").textContent = mk.price_note;
  var c = mk.contact || {}, any = false;
  function https(u) { try { return new URL(u).protocol === "https:"; } catch (e) { return false; } }
  if (c.telegram && https(c.telegram)) { $("c-tg").href = c.telegram; $("c-tg").hidden = false; any = true; }
  if (c.email && /^[^@\s<>"]+@[^@\s<>"]+\.[a-z]{2,24}$/i.test(c.email)) {
    $("c-mail").href = "mailto:" + c.email + "?subject=" + encodeURIComponent("GTA VI Türkiye Bülteni sponsorluk");
    $("c-mail").textContent = c.email; $("c-mail").hidden = false; any = true;
  }
  $("c-none").hidden = any;
})();

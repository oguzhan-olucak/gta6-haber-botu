/* Reklam yükleyici: yalnızca data/monetization.js içinde AdSense kimliği varsa çalışır.
 * - auto=true: Google'ın otomatik reklamları (AdSense panelinde de açık olmalı).
 * - slots: { "guide-top": "1234567890" } verilen yuvalara elle reklam birimi koyar; diğer yuvalar gizli kalır.
 * Kimlik yoksa hiçbir dış betik yüklenmez, hiçbir çerez yazılmaz. */
(function () {
  "use strict";
  var m = window.__GTA6_MONETIZATION__ || {};
  var ads = m.ads;
  if (!ads || !/^ca-pub-\d{10,20}$/.test(ads.client || "")) return;
  var s = document.createElement("script");
  s.async = true;
  s.crossOrigin = "anonymous";
  s.src = "https://pagead2.googlesyndication.com/pagead/js/adsbygoogle.js?client=" + encodeURIComponent(ads.client);
  document.head.appendChild(s);
  var slots = ads.slots || {};
  var nodes = document.querySelectorAll(".ad-slot[data-slot]");
  for (var i = 0; i < nodes.length; i++) {
    var el = nodes[i], id = slots[el.getAttribute("data-slot")];
    if (!id || !/^\d{6,20}$/.test(id)) continue;
    var ins = document.createElement("ins");
    ins.className = "adsbygoogle";
    ins.style.display = "block";
    ins.setAttribute("data-ad-client", ads.client);
    ins.setAttribute("data-ad-slot", id);
    ins.setAttribute("data-ad-format", "auto");
    ins.setAttribute("data-full-width-responsive", "true");
    el.appendChild(ins);
    el.hidden = false;
    try { (window.adsbygoogle = window.adsbygoogle || []).push({}); } catch (e) { /* engelleyici */ }
  }
})();

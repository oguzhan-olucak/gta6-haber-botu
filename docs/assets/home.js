/* Ana sayfa: YouTube fragman kartı → tıklanınca gizlilik dostu oynatıcı (youtube-nocookie).
 * Tıklanmadan YouTube'a hiçbir istek gitmez (yalnızca kapak görseli). */
(function () {
  "use strict";
  var cards = document.querySelectorAll(".yt[data-yt]");
  for (var i = 0; i < cards.length; i++) {
    cards[i].addEventListener("click", function () {
      var id = this.getAttribute("data-yt");
      if (!/^[A-Za-z0-9_-]{11}$/.test(id)) return;
      var f = document.createElement("iframe");
      f.src = "https://www.youtube-nocookie.com/embed/" + id + "?autoplay=1&rel=0";
      f.title = this.getAttribute("aria-label") || "YouTube";
      f.allow = "autoplay; encrypted-media; picture-in-picture; fullscreen";
      f.setAttribute("allowfullscreen", "");
      f.className = "vcard__frame";
      this.replaceWith(f);
    });
  }
})();

/* Lansman bandı: çıkıştan sonra metni kendiliğinden değiştir (Türkiye 19 Kasım 00.00 = 18 Kasım 21.00 UTC). */
(function () {
  var a = document.getElementById("lb-a"), b = document.getElementById("lb-b");
  if (!a || !b) return;
  if (Date.now() >= Date.UTC(2026, 10, 18, 21, 0, 0)) { a.textContent = "Çıktı"; b.textContent = "Şimdi oynanabilir"; }
})();

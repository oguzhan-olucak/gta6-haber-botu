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

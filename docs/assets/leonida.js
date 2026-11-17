/* Leonida haritası bölge tanımları. x/y: harita viewBox (1000×700) koordinatı.
 * Koordinat etiketleri stilize gösterimdir; oyundaki konumları birebir yansıtmaz.
 * keywords: feed.json'da location_id olmayan (eski) haberler için istemci tarafı yedek eşleme. */
window.__LEONIDA__ = {
  regions: [
    { id: "vice_city", name: "Vice City", sub: "Ocean Drive ve neon sahil", x: 610, y: 406, label: [18, 6, "start"],
      coords: "25.774° K · 80.193° B", topics: "Fragman, şehir ve atmosfer",
      desc: "Leonida'nın neon başkenti. Fragmanlar, ekran görüntüleri, müzik ve şehir atmosferiyle ilgili haberler burada.",
      categories: ["TRAILER_MEDIA", "OTHER"],
      keywords: ["vice city", "ocean drive", "fragman", "trailer", "ekran görüntü", "screenshot", "radyo", "müzik", "plaj"] },
    { id: "leonida_keys", name: "Leonida Keys", sub: "Takımadalar ve deniz", x: 470, y: 630, label: [-18, 6, "end"],
      coords: "24.555° K · 81.780° B", topics: "Oynanış, araçlar ve fizik",
      desc: "Köprülerle bağlanan adalar zinciri. Oynanış, araçlar, sürüş, fizik ve fotoğraf modu haberleri burada.",
      categories: ["GAMEPLAY_TECH"],
      keywords: ["leonida keys", "oynanış", "gameplay", "araç", "araba", "tekne", "fizik", "sürüş", "fotoğraf modu", "erişilebilirlik"] },
    { id: "grassrivers", name: "Grassrivers", sub: "Bataklık ve vahşi yaşam", x: 482, y: 469, label: [-18, 6, "end"],
      coords: "25.286° K · 80.899° B", topics: "Harita, ekosistem ve keşif",
      desc: "Sazlıklar, timsahlar ve sis. Harita boyutu, ekosistem, keşif ve doğrulanmamış harita iddiaları burada.",
      categories: ["COMMUNITY_RUMOR"],
      keywords: ["grassrivers", "bataklık", "harita", "map", "timsah", "vahşi", "ada", "keşif"] },
    { id: "port_gellhorn", name: "Port Gellhorn & Ambrosia", sub: "Liman ve iç bölgeler", x: 354, y: 350, label: [0, -24, "middle"],
      coords: "30.421° K · 87.217° B", topics: "Hikâye, karakterler ve görevler",
      desc: "Panhandle'ın liman kenti ve iç bölgeler. Jason ve Lucia'nın hikâyesi, karakterler ve görevlerle ilgili haberler burada.",
      categories: [],
      keywords: ["port gellhorn", "ambrosia", "jason", "lucia", "hikâye", "hikaye", "karakter", "görev", "seslendir"] },
    { id: "mount_kalaga", name: "Mount Kalaga", sub: "Genel merkez", x: 441, y: 147, label: [0, -24, "middle"],
      coords: "30.438° K · 84.281° B", topics: "Resmî açıklamalar, çıkış ve platform",
      desc: "Komuta merkezi. Rockstar ve Take-Two açıklamaları, çıkış tarihi, ön yükleme, fiyat ve platform haberleri burada.",
      categories: ["OFFICIAL_ANNOUNCEMENT", "RELEASE_PLATFORMS", "INDUSTRY_BUSINESS"],
      keywords: ["mount kalaga", "çıkış tarihi", "ön yükleme", "ön sipariş", "fiyat", "ps5", "playstation", "xbox", "gb", "take-two", "inceleme", "erteleme"] }
  ],
  bounds: { latTop: 31.35, latBottom: 24.15, lonLeft: 90.167, lonRight: 78.55 }
};

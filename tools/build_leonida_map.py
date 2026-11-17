"""Leonida haritasının coğrafi katmanını üretir (tek seferlik araç; çıktı docs/assets/leonida-map.svg).

Leonida, Rockstar'ın Florida'yı parodileyen kurgusal eyaletidir ve resmî haritası yayımlanmamıştır.
Bu yüzden harita, **gerçek Florida kıyı çizgisine** (enlem/boylam noktaları; kamu malı coğrafi bilgi)
dayanır ve bölgeler bilinen karşılıklarına yerleştirilir: Vice City ≈ Miami, Leonida Keys ≈ Florida Keys,
Grassrivers ≈ Everglades, Port Gellhorn ≈ Panhandle. Oyundaki haritayı birebir gösterdiği iddia edilmez.

Projeksiyon: eşdikdörtgen, enlem 27.7° kosinüsüyle düzeltilmiş (Florida ölçeğinde şekil bozulması
ihmal edilebilir). Çıktı viewBox 1000×700; app.js iğneleri leonida.js'teki x/y ile yerleştirir.

Kullanım:  python tools/build_leonida_map.py   (docs/assets/leonida-map.svg ve leonida.js x/y günceller)
"""
from __future__ import annotations

import math
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
W, H = 1000, 700
LAT_TOP, LAT_BOTTOM = 31.35, 24.15
PX_PER_LAT = H / (LAT_TOP - LAT_BOTTOM)
PX_PER_LON = PX_PER_LAT * math.cos(math.radians(27.7))
LON_RIGHT = 78.55                       # batı boylamı (pozitif)
LON_LEFT = LON_RIGHT + W / PX_PER_LON


def xy(lat: float, lon_w: float) -> tuple[float, float]:
    return (round((LON_LEFT - lon_w) * PX_PER_LON, 1), round((LAT_TOP - lat) * PX_PER_LAT, 1))


# Florida anakarası (saat yönünde; Perdido Key'den başlar). (enlem, batı boylamı)
MAINLAND = [
    (30.28, 87.52), (30.30, 87.30), (30.33, 87.15), (30.38, 86.80), (30.39, 86.50), (30.37, 86.30), (30.28, 86.00),
    (30.17, 85.80), (30.10, 85.62), (29.95, 85.42), (29.80, 85.31), (29.67, 85.36), (29.68, 85.22), (29.72, 85.00),
    (29.63, 84.85), (29.85, 84.65), (29.92, 84.38), (30.05, 84.20), (30.00, 83.95), (29.85, 83.65), (29.67, 83.39),
    (29.44, 83.29), (29.27, 83.10), (29.14, 83.03), (29.00, 82.80), (28.85, 82.70), (28.60, 82.66), (28.30, 82.72),
    (28.15, 82.80), (28.00, 82.83), (27.80, 82.80), (27.62, 82.74), (27.75, 82.62), (27.95, 82.55), (27.75, 82.45),
    (27.55, 82.62), (27.33, 82.58), (27.10, 82.45), (26.95, 82.35), (26.75, 82.27), (26.95, 82.05), (26.60, 82.02),
    (26.45, 81.95), (26.30, 81.84), (26.14, 81.80), (25.94, 81.72), (25.86, 81.39), (25.60, 81.25), (25.35, 81.15),
    (25.12, 81.10), (25.14, 80.92), (25.20, 80.65), (25.28, 80.45), (25.45, 80.33), (25.62, 80.30), (25.77, 80.19),
    (25.77, 80.13), (25.95, 80.12), (26.12, 80.10), (26.35, 80.07), (26.70, 80.03), (26.95, 80.07), (27.20, 80.17),
    (27.47, 80.30), (27.64, 80.36), (28.08, 80.58), (28.40, 80.60), (28.47, 80.53), (28.70, 80.68), (28.95, 80.85),
    (29.20, 81.00), (29.50, 81.13), (29.90, 81.29), (30.33, 81.39), (30.70, 81.45),
    # Kuzey sınırı (Georgia / Alabama)
    (30.72, 81.60), (30.50, 82.02), (30.57, 82.20), (30.60, 82.46), (30.68, 83.30), (30.70, 84.00), (30.71, 84.86),
    (31.00, 85.00), (31.00, 86.00), (31.00, 87.60), (30.95, 87.60), (30.65, 87.40), (30.42, 87.43),
]
# Bölge dışı komşu kara (Georgia/Alabama): haritanın "ada" gibi durmaması için soluk gölge
NEIGHBOR = [(36.0, 95.0), (36.0, 75.4), (35.2, 75.5), (34.0, 77.9), (33.0, 79.3), (32.0, 80.9), (31.0, 81.4), (30.70, 81.45), (30.72, 81.60), (30.50, 82.02), (30.57, 82.20),
            (30.60, 82.46), (30.68, 83.30), (30.70, 84.00), (30.71, 84.86), (31.00, 85.00), (31.00, 86.00),
            (31.00, 87.60), (30.95, 87.60), (30.65, 87.40), (30.42, 87.43), (30.28, 87.52), (30.25, 88.0),
            (30.35, 88.6), (30.30, 89.3), (29.9, 90.2), (29.2, 91.5), (29.6, 94.0), (29.4, 95.0)]
KEYS = [(25.10, 80.45), (24.95, 80.60), (24.84, 80.78), (24.74, 80.98), (24.70, 81.15), (24.66, 81.35),
        (24.60, 81.55), (24.55, 81.78)]
LAKE = (26.95, 80.83, 0.24, 0.20)           # Okeechobee: merkez, boylam/enlem yarıçapı
WETLAND = [(26.25, 81.05), (26.10, 80.55), (25.80, 80.45), (25.45, 80.48), (25.25, 80.80), (25.30, 81.10),
           (25.70, 81.30), (26.05, 81.35)]   # Everglades ≈ Grassrivers
ROADS = {
    "I-10": [(30.48, 87.30), (30.62, 86.60), (30.73, 85.80), (30.48, 84.90), (30.45, 84.28), (30.45, 83.40),
             (30.30, 82.70), (30.33, 81.66)],
    "I-75": [(30.60, 83.20), (30.19, 82.64), (29.65, 82.35), (29.19, 82.14), (28.55, 82.25), (28.05, 82.40),
             (27.40, 82.45), (26.65, 81.85), (26.15, 81.75), (26.15, 81.10), (26.12, 80.30)],
    "I-95": [(30.70, 81.62), (30.33, 81.66), (29.90, 81.40), (29.20, 81.10), (28.55, 80.85), (28.10, 80.72),
             (27.45, 80.40), (26.70, 80.10), (26.12, 80.17), (25.79, 80.21)],
    "US-1": [(25.45, 80.48), (25.10, 80.45), (24.95, 80.60), (24.84, 80.78), (24.74, 80.98), (24.70, 81.15),
             (24.66, 81.35), (24.60, 81.55), (24.55, 81.78)],
}
CITIES = [  # gece ışıkları (boyut ~ nüfus)
    (25.78, 80.21, 13), (26.12, 80.15, 9), (26.70, 80.07, 7), (27.96, 82.46, 11), (27.77, 82.64, 8),
    (28.54, 81.38, 11), (30.33, 81.66, 9), (30.44, 84.28, 6), (30.42, 87.22, 6), (30.16, 85.66, 4),
    (29.65, 82.32, 5), (26.64, 81.87, 6), (24.56, 81.78, 3), (29.21, 81.02, 5), (28.08, 80.61, 5),
]
GRATICULE_LAT = range(22, 36)
GRATICULE_LON = range(74, 96)
LABELS = [("MEKSİKA KÖRFEZİ", 27.2, 85.9, "sea"), ("ATLANTİK OKYANUSU", 28.4, 78.9, "sea"),
          ("LEONIDA", 28.2, 81.75, "land")]
# Leonida bölgeleri → gerçek karşılık koordinatı (leonida.js 'coords' ile aynı)
REGION_LATLON = {
    "vice_city": (25.774, 80.193), "leonida_keys": (24.555, 81.780), "grassrivers": (25.286, 80.899),
    "port_gellhorn": (30.421, 87.217), "mount_kalaga": (30.438, 84.281),
}


def path(points: list[tuple[float, float]], closed: bool = True) -> str:
    pts = [xy(*p) for p in points]
    d = "M" + " L".join(f"{x} {y}" for x, y in pts)
    return d + ("Z" if closed else "")


def smooth(points: list[tuple[float, float]], closed: bool = True) -> str:
    """Catmull-Rom → kübik Bézier: noktalı kıyı yerine doğal kıvrımlar."""
    pts = [xy(*p) for p in points]
    n = len(pts)
    if n < 3:
        return path(points, closed)
    out = [f"M{pts[0][0]} {pts[0][1]}"]
    rng = range(n) if closed else range(n - 1)
    for i in rng:
        p0 = pts[(i - 1) % n] if closed or i > 0 else pts[i]
        p1, p2 = pts[i], pts[(i + 1) % n]
        p3 = pts[(i + 2) % n] if closed or i + 2 < n else p2
        c1 = (round(p1[0] + (p2[0] - p0[0]) / 6, 1), round(p1[1] + (p2[1] - p0[1]) / 6, 1))
        c2 = (round(p2[0] - (p3[0] - p1[0]) / 6, 1), round(p2[1] - (p3[1] - p1[1]) / 6, 1))
        out.append(f"C{c1[0]} {c1[1]} {c2[0]} {c2[1]} {p2[0]} {p2[1]}")
    return " ".join(out) + ("Z" if closed else "")


def build_svg() -> str:
    land = smooth(MAINLAND)
    lx, ly = xy(LAKE[0], LAKE[1])
    lrx, lry = LAKE[2] * PX_PER_LON, LAKE[3] * PX_PER_LAT
    keys = "".join(
        f'<ellipse cx="{x}" cy="{y}" rx="{7 if i < len(KEYS) - 1 else 6}" ry="2.6" '
        f'transform="rotate({-28 + i * 3} {x} {y})"/>'
        for i, (x, y) in enumerate(xy(*k) for k in KEYS))
    roads = "".join(f'<path d="{smooth(pts, closed=False)}"/>' for name, pts in ROADS.items())
    lights = "".join(f'<circle cx="{xy(a, b)[0]}" cy="{xy(a, b)[1]}" r="{r}"/>' for a, b, r in CITIES)
    lights_core = "".join(f'<circle cx="{xy(a, b)[0]}" cy="{xy(a, b)[1]}" r="{max(1.2, r / 5):.1f}"/>'
                          for a, b, r in CITIES)
    grat = []
    for lat in GRATICULE_LAT:
        y = xy(lat, 80)[1]
        grat.append(f'<path d="M-1600 {y}H2600"/><text x="{xy(lat, 79.0)[0]}" y="{y - 4}">{lat}°K</text>')
    for lon in GRATICULE_LON:
        x = xy(28, lon)[0]
        grat.append(f'<path d="M{x} -1200V1900"/><text x="{x + 4}" y="{xy(24.4, 80)[1]}">{lon}°B</text>')
    labels = "".join(
        f'<text class="map__lbl map__lbl--{kind}" x="{xy(a, b)[0]}" y="{xy(a, b)[1]}" text-anchor="middle">{t}</text>'
        for t, a, b, kind in LABELS)
    return f"""<g class="geo" aria-hidden="true">
  <g class="geo__grat">{''.join(grat)}</g>
  <path class="geo__neighbor" d="{smooth(NEIGHBOR)}"/>
  <path class="geo__shelf" d="{land}"/>
  <path class="geo__land" d="{land}"/>
  <g clip-path="url(#clip-land)">
    <rect class="geo__relief" width="{W}" height="{H}" filter="url(#f-relief)"/>
    <path class="geo__wet" d="{smooth(WETLAND)}" fill="url(#p-wet)"/>
    <path class="geo__wetglow" d="{smooth(WETLAND)}"/>
  </g>
  <path class="geo__coast" d="{land}"/>
  <ellipse class="geo__lake" cx="{lx}" cy="{ly}" rx="{lrx:.1f}" ry="{lry:.1f}"/>
  <g class="geo__keys">{keys}</g>
  <g class="geo__roads">{roads}</g>
  <g class="geo__lights">{lights}</g>
  <g class="geo__lights-core">{lights_core}</g>
  <g class="map__labels">{labels}</g>
</g>"""


def defs() -> str:
    return f"""<defs>
  <linearGradient id="g-ocean" x1="0" y1="0" x2="1" y2="1">
    <stop offset="0" stop-color="#0a1420"/><stop offset=".55" stop-color="#07101a"/><stop offset="1" stop-color="#050b13"/>
  </linearGradient>
  <clipPath id="clip-land"><path d="{smooth(MAINLAND)}"/></clipPath>
  <filter id="f-relief" x="0" y="0" width="100%" height="100%" color-interpolation-filters="sRGB">
    <feTurbulence type="fractalNoise" baseFrequency=".011 .014" numOctaves="5" seed="19" result="n"/>
    <feDiffuseLighting in="n" surfaceScale="2.6" diffuseConstant="1.05" lighting-color="#cfe3d2" result="l">
      <feDistantLight azimuth="235" elevation="38"/>
    </feDiffuseLighting>
    <feColorMatrix in="l" type="matrix" values="0.22 0 0 0 0.03  0 0.30 0 0 0.05  0 0 0.24 0 0.04  0 0 0 1 0"/>
  </filter>
  <pattern id="p-wet" width="7" height="7" patternUnits="userSpaceOnUse" patternTransform="rotate(-20)">
    <path d="M0 3.5h4" stroke="#5fae86" stroke-opacity=".38" stroke-width="1"/>
  </pattern>
  <radialGradient id="g-light"><stop offset="0" stop-color="#ffd9a0" stop-opacity=".9"/><stop offset="1" stop-color="#ff9b4a" stop-opacity="0"/></radialGradient>
</defs>"""


def main() -> None:
    svg = defs() + "\n" + build_svg()
    # Çıktı: index.html'deki <svg id="map"> içine, </desc> ile <g id="pins"> arasına yerleştirilir
    out = ROOT / "docs" / "assets" / "leonida-map.svg.part"
    out.write_text(svg + "\n", encoding="utf-8")
    regions = {k: xy(*v) for k, v in REGION_LATLON.items()}
    js = ROOT / "docs" / "assets" / "leonida.js"
    text = js.read_text(encoding="utf-8")
    for rid, (x, y) in regions.items():
        text = re.sub(rf'(id: "{rid}",[^\n]*?x: )[\d.]+(, y: )[\d.]+', rf"\g<1>{round(x)}\g<2>{round(y)}", text)
    text = re.sub(r"bounds: \{[^}]*\}",
                  f"bounds: {{ latTop: {LAT_TOP}, latBottom: {LAT_BOTTOM}, lonLeft: {LON_LEFT:.3f}, lonRight: {LON_RIGHT} }}",
                  text)
    js.write_text(text, encoding="utf-8")
    print("bölgeler:", regions)


if __name__ == "__main__":
    main()

"""Faz 2: olay kümeleme motoru ve çapraz doğrulama (ÇOKLU KAYNAK yükseltmesi)."""
import pytest

from bot.clustering import Doc, SimilarityEngine, cluster_docs, entities, fold, tokens
from bot.processor import Label, assess, cluster_items
from tests.conftest import NOW
from tests.test_processor import make_item

SAME_EVENT = [
    (("GTA 6 trailer 3 release date revealed by Rockstar",
      "Rockstar has confirmed the third Grand Theft Auto 6 trailer will arrive on Tuesday, showing Lucia and Jason."),
     ("Rockstar confirms when the third Grand Theft Auto VI trailer drops",
      "The third trailer for GTA 6 lands Tuesday, Rockstar Games said, with Lucia and Jason front and center.")),
    (("GTA 6 preload size is 150GB on PS5",
      "Grand Theft Auto 6 will require 150GB of storage on PlayStation 5, according to the PlayStation Store listing."),
     ("GTA VI needs 150GB of free space on PlayStation 5, store listing shows",
      "The PlayStation Store page for GTA 6 lists a 150GB download ahead of the November 19 launch.")),
    (("Take-Two CEO says GTA 6 is on track for November",
      "Strauss Zelnick told investors that Grand Theft Auto VI remains on track for its November 19 release."),
     ("Zelnick: Grand Theft Auto 6 still launching November 19",
      "Take-Two boss Strauss Zelnick reiterated the November 19 date during the earnings call.")),
    (("GTA 6 map leak shows Leonida in full", "A leaked map image purportedly shows the whole state of Leonida."),
     ("Alleged GTA VI map leak reveals full Leonida",
      "An image claiming to be the full Leonida map has leaked online, though Rockstar has not commented.")),
]

DIFFERENT_EVENT = [
    (("GTA 6 trailer 3 release date revealed by Rockstar", "Rockstar has confirmed the third trailer arrives Tuesday."),
     ("GTA 6 trailer 2 breakdown: every detail you missed", "We went frame by frame through the second trailer.")),
    (("GTA 6 preload now live on Xbox Series X", "Xbox players can now preload Grand Theft Auto 6 ahead of launch."),
     ("GTA 6 preload size is 150GB on PS5", "Grand Theft Auto 6 will require 150GB of storage on PlayStation 5.")),
    (("Take-Two earnings: GTA 6 still on track for November", "Take-Two reported quarterly results and said GTA 6 is on track."),
     ("Take-Two earnings: Borderlands 4 sales beat expectations", "Take-Two reported quarterly results with strong Borderlands 4 sales.")),
    (("GTA 6 Lucia actress speaks about the role", "The actress who plays Lucia talked about GTA 6."),
     ("GTA 6 Jason actor speaks about the role", "The actor who plays Jason talked about GTA 6.")),
    (("GTA 6 review embargo date revealed", "Reviews for GTA 6 will go live on November 18."),
     ("GTA 6 review: Vice City has never looked better", "Our review of Grand Theft Auto VI.")),
]


def _pair_score(a, b, corpus_extra=()):
    docs = [Doc(key="a", title=a[0], summary=a[1]), Doc(key="b", title=b[0], summary=b[1])]
    docs += [Doc(key=f"x{i}", title=t, summary=s) for i, (t, s) in enumerate(corpus_extra)]
    return SimilarityEngine(docs).score(0, 1)


ALL = [x for pair in SAME_EVENT + DIFFERENT_EVENT for x in pair]


@pytest.mark.parametrize("a,b", SAME_EVENT)
def test_same_event_with_different_headlines_scores_above_threshold(a, b, settings):
    assert _pair_score(a, b, ALL) >= settings.cluster_similarity_threshold


@pytest.mark.parametrize("a,b", DIFFERENT_EVENT)
def test_different_events_stay_below_threshold(a, b, settings):
    assert _pair_score(a, b, ALL) < settings.cluster_similarity_threshold


def test_two_independent_outlets_upgrade_to_multi_source(settings):
    """IGN + VGC aynı olayı farklı başlıkla yazınca tek kümede birleşir → ÇOKLU KAYNAK."""
    (t1, s1), (t2, s2) = SAME_EVENT[1]
    ign = make_item("ign", "ESTABLISHED_MEDIA", "ign", t1, "https://www.ign.com/gta-6-preload", s1)
    vgc = make_item("vgc", "ESTABLISHED_MEDIA", "vgc", t2, "https://www.videogameschronicle.com/gta-6-150gb", s2)
    (t3, s3) = DIFFERENT_EVENT[2][1]
    other = make_item("eurogamer", "ESTABLISHED_MEDIA", "eurogamer", t3, "https://www.eurogamer.net/borderlands", s3)
    clusters = cluster_items([ign, vgc, other], settings.cluster_similarity_threshold)
    sizes = sorted(len(c) for c in clusters)
    assert sizes == [1, 2]
    pair = next(c for c in clusters if len(c) == 2)
    assert assess(pair, settings, NOW).label == Label.MULTI_SOURCE


def test_average_linkage_prevents_chaining(settings):
    """A~B ve B~C benzer olsa da A ile C alakasızsa üçü tek kümede toplanmaz."""
    docs = [Doc(key="a", title="GTA 6 preload size 150GB PlayStation store listing"),
            Doc(key="b", title="GTA 6 PlayStation store listing shows price and preload"),
            Doc(key="c", title="GTA 6 price on store listing is 70 dollars")]
    groups = cluster_docs(docs, 0.5)
    assert all(len(g) < 3 for g in groups)


def test_same_url_always_clusters_even_if_titles_differ(settings):
    a = make_item("ign", "ESTABLISHED_MEDIA", "ign", "Completely different headline one", "https://www.ign.com/x")
    b = make_item("ign", "ESTABLISHED_MEDIA", "ign", "Unrelated words entirely two", "https://ign.com/x/")
    assert len(cluster_items([a, b], settings.cluster_similarity_threshold)) == 1


def test_items_far_apart_in_time_do_not_cluster(settings):
    (t1, s1), (t2, s2) = SAME_EVENT[3]
    a = make_item("ign", "ESTABLISHED_MEDIA", "ign", t1, "https://www.ign.com/a", s1, published="2026-11-01T10:00:00Z")
    b = make_item("vgc", "ESTABLISHED_MEDIA", "vgc", t2, "https://www.videogameschronicle.com/b", s2)
    assert len(cluster_items([a, b], settings.cluster_similarity_threshold, max_gap_hours=72)) == 2


def test_turkish_folding_and_ordinals():
    assert fold("İSTANBUL ışık ŞÖĞÜÇ") == "istanbul isik sogüc".replace("ü", "u")
    assert "3" in tokens("The third trailer") and "3" in tokens("Üçüncü fragman ucuncu")


def test_entities_ignore_title_case_noise():
    ents = entities("GTA 6 Preload Size Revealed For PlayStation Owners", "")
    assert "playstation" in ents
    ents2 = entities("Some title", "A short summary that mentions Lucia and the PlayStation Store in Vice City today.")
    assert {"lucia", "playstation", "store", "vice", "city"} <= ents2

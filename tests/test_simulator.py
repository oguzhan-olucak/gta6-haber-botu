"""Faz 2: yerel simülatör tüm senaryolarda ağsız çalışır ve beklenen mesajları üretir."""
import sys

from tests.conftest import ROOT

sys.path.insert(0, str(ROOT / "tools"))
import dry_run_simulator as sim  # noqa: E402


def test_all_scenarios_produce_expected_messages(tmp_path):
    out = tmp_path / "preview.html"
    assert sim.main(["--out", str(out), "--site-data", str(tmp_path / "data")]) == 0
    assert (tmp_path / "data" / "demo-feed.js").exists() and not (tmp_path / "data" / "feed.json").exists()
    page = out.read_text(encoding="utf-8")
    for needle in ("RESMÎ AÇIKLAMA", "ÇOKLU KAYNAK", "SIZINTI İDDİASI", "Yönetici Özeti", "ACİL UYARI"):
        assert needle in page
    assert "SIMULATOR_FAKE_TOKEN" not in page


def test_single_scenario_flag(tmp_path):
    out = tmp_path / "p.html"
    assert sim.main(["--scenario", "multi", "--out", str(out), "--no-site"]) == 0
    assert out.read_text(encoding="utf-8").count('class="device"') == 1

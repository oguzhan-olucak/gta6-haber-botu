"""Ortak test fixture'ları. Testler gerçek ağ/API çağrısı yapmaz.

Testlerde yalnızca açıkça sahte sabitler kullanılır; gerçek secret okunmaz.
"""
from __future__ import annotations

import json
import socket
import sys
from datetime import datetime, timezone
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from bot.config import Settings, Source  # noqa: E402

DUMMY_TELEGRAM_TOKEN = "DUMMY_TEST_TOKEN_DO_NOT_USE"
DUMMY_GEMINI_KEY = "DUMMY_GEMINI_KEY_DO_NOT_USE"
NOW = datetime(2026, 11, 16, 12, 0, tzinfo=timezone.utc)


@pytest.fixture(autouse=True)
def _no_real_network(monkeypatch):
    """Herhangi bir test yanlışlıkla gerçek ağa çıkmaya çalışırsa başarısız olsun."""

    def guard(*args, **kwargs):
        raise RuntimeError("Testlerde gerçek ağ erişimi yasak")

    monkeypatch.setattr(socket.socket, "connect", guard)
    monkeypatch.setattr(socket, "create_connection", guard)
    for name in ("GEMINI_API_KEY", "TELEGRAM_BOT_TOKEN", "TELEGRAM_CHAT_ID", "ADMIN_CHAT_ID", "GEMINI_MODEL"):
        monkeypatch.delenv(name, raising=False)


@pytest.fixture
def settings() -> Settings:
    data = json.loads((ROOT / "config" / "settings.json").read_text(encoding="utf-8"))
    data["verify_source_urls"] = False  # URL doğrulaması ayrı testlerde mock'lanır
    return Settings.model_validate(data)


@pytest.fixture
def sources() -> list[Source]:
    return [
        Source(id="rockstar", name="Rockstar Newswire", trust_class="OFFICIAL",
               feed_url="https://www.rockstargames.com/feed.xml", allowed_domains=["rockstargames.com"],
               origin_group="rockstar"),
        Source(id="ign", name="IGN", trust_class="ESTABLISHED_MEDIA",
               feed_url="https://feeds.example-ign.test/ign.xml", allowed_domains=["ign.com"], origin_group="ign"),
        Source(id="eurogamer", name="Eurogamer", trust_class="ESTABLISHED_MEDIA",
               feed_url="https://www.eurogamer.net/feed", allowed_domains=["eurogamer.net"], origin_group="eurogamer"),
        Source(id="gamesradar", name="GamesRadar+", trust_class="ESTABLISHED_MEDIA",
               feed_url="https://www.gamesradar.com/rss/", allowed_domains=["gamesradar.com"], origin_group="future_plc"),
        Source(id="pcgamer", name="PC Gamer", trust_class="ESTABLISHED_MEDIA",
               feed_url="https://www.pcgamer.com/rss/", allowed_domains=["pcgamer.com"], origin_group="future_plc"),
        Source(id="reddit_gta6", name="r/GTA6", trust_class="COMMUNITY",
               feed_url="https://www.reddit.com/r/GTA6/new/.rss", allowed_domains=["reddit.com"], origin_group="reddit"),
    ]


def rss(items: list[dict]) -> bytes:
    parts = []
    for it in items:
        parts.append(
            "<item>"
            f"<title>{it['title']}</title>"
            f"<link>{it['link']}</link>"
            f"<description>{it.get('description', '')}</description>"
            f"<pubDate>{it.get('pubDate', 'Mon, 16 Nov 2026 10:00:00 GMT')}</pubDate>"
            "</item>"
        )
    return (
        '<?xml version="1.0" encoding="UTF-8"?><rss version="2.0"><channel><title>t</title>'
        + "".join(parts)
        + "</channel></rss>"
    ).encode("utf-8")


class FakeResponse:
    def __init__(self, status_code=200, content=b"", headers=None, json_data=None):
        self.status_code = status_code
        self._content = content
        self.headers = headers or {}
        self._json = json_data

    def iter_content(self, chunk_size=65536):
        for i in range(0, len(self._content), chunk_size):
            yield self._content[i:i + chunk_size]

    @property
    def content(self):
        return self._content

    def json(self):
        if self._json is None:
            return json.loads(self._content.decode("utf-8"))
        return self._json

    def close(self):
        pass

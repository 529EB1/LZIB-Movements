import json
from dataclasses import replace
from datetime import timedelta

import httpx
import pytest

from lzib_movements.alerts.discord import DiscordWebhook, redact_webhook
from lzib_movements.config import Settings
from lzib_movements.models import Aircraft, Observation
from lzib_movements.monitor import Monitor
from lzib_movements.registration_lists import (
    RegistrationLists,
    normalize_callsign,
    normalize_registration,
)
from lzib_movements.units import (
    feet_to_metres,
    kilometres_to_nautical_miles,
    knots_to_metres_per_second,
)


def webhook_url(identifier: str, token: str) -> str:
    return "https://discord.com/api/" + f"webhooks/{identifier}/{token}"


def test_registration_normalization_and_validation(tmp_path):
    assert normalize_registration(" om – abc ") == "OM-ABC"
    assert normalize_callsign(" tst- 12 ") == "TST12"
    assert normalize_callsign("TST0001") == "TST1"
    assert normalize_registration(None, strict=False) is None
    with pytest.raises(ValueError):
        normalize_registration("   ")
    special = tmp_path / "s.json"
    ignored = tmp_path / "i.json"
    special.write_text(
        json.dumps(
            [
                {"registration": "om-abc", "livery": "One"},
                {"registration": "OM-ABC", "livery": "Two"},
            ]
        )
    )
    ignored.write_text('["IG-NORE", "ig-nore"]')
    lists = RegistrationLists.load(special, ignored)
    assert len(lists.special) == len(lists.ignored) == 1 and lists.special["OM-ABC"].livery == "Two"


def test_units():
    assert feet_to_metres(1000) == pytest.approx(304.8)
    assert kilometres_to_nautical_miles(1.852) == pytest.approx(1)
    assert knots_to_metres_per_second(1) == pytest.approx(0.514444)


def test_configuration_validation(settings):
    assert Settings(search_radius_nm=251).validate()
    assert Settings(request_reserve=500).validate()
    assert Settings(local_timezone="Not/AZone").validate()
    assert not replace(
        settings,
        special_webhook_url=webhook_url("a", "b"),
        unusual_webhook_url=webhook_url("c", "d"),
    ).validate()
    configured = replace(
        settings,
        special_webhook_url=webhook_url("identifier", "token-value"),
        unusual_webhook_url=webhook_url("other", "token-value"),
    )
    assert "token-value" not in repr(configured)


def test_webhook_redaction():
    webhook = "https://discord.com/api/webhooks/123/" + "test-value"
    assert "test-value" not in redact_webhook(webhook) and "123" not in redact_webhook(webhook)


@pytest.mark.asyncio
async def test_discord_retry_and_missing_photo():
    calls = 0

    def handler(request):
        nonlocal calls
        calls += 1
        return httpx.Response(429 if calls == 1 else 204, headers={"Retry-After": "0"})

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    await DiscordWebhook(webhook_url("identifier", "token"), client=client).send({"title": "x"})
    assert calls == 2
    from lzib_movements.providers.photos import NoPhotoProvider

    assert await NoPhotoProvider().lookup("OM-ABC") is None
    await client.aclose()


class StubProvider:
    async def nearby(self, latitude, longitude, radius):
        return [
            Aircraft(
                "abc",
                "OM-NEW",
                "TST1",
                latitude=48.2,
                longitude=17.2,
                barometric_altitude_ft=4000,
                vertical_rate_fpm=-500,
                on_ground=False,
                position_age_seconds=1,
            )
        ]


@pytest.mark.asyncio
async def test_dry_run_does_not_send(database, settings, now):
    calls = 0

    async def sender(decision, embed):
        nonlocal calls
        calls += 1

    monitor = Monitor(replace(settings, dry_run=True), database, StubProvider(), sender)
    decisions = await monitor.scan(now=now)
    assert decisions and calls == 0
    assert not database.was_alerted(
        decisions[0].alert_key, timedelta(hours=settings.alert_cooldown_hours), now
    )


def test_cleanup(database, now):
    old = Observation("old", now - timedelta(days=3), 1000, 1, 48, 17)
    database.add_observation(old)
    database.cleanup(now)
    assert database.previous_observation("old", now) is None

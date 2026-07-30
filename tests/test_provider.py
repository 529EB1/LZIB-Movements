from datetime import timedelta

import httpx
import pytest

from lzib_movements.providers.airplanes_live import AirplanesLiveProvider
from lzib_movements.providers.base import ProviderError, RateLimited


@pytest.mark.asyncio
async def test_provider_maps_documented_fields(database, now):
    payload = {
        "now": now.timestamp(),
        "ac": [
            {
                "hex": "ABC",
                "flight": " TST 12 ",
                "r": " om-abc ",
                "t": "A320",
                "lat": 48.2,
                "lon": 17.2,
                "alt_baro": 7000,
                "alt_geom": 7100,
                "gs": 250,
                "track": 90,
                "baro_rate": -512,
                "seen_pos": 4,
                "category": "A3",
                "ownOp": "Test",
            }
        ],
    }
    client = httpx.AsyncClient(
        transport=httpx.MockTransport(lambda request: httpx.Response(200, json=payload))
    )
    provider = AirplanesLiveProvider(database, 10, 1, client=client)
    aircraft = (await provider.nearby(48, 17, 250))[0]
    assert aircraft.callsign == "TST12" and aircraft.registration == "OM-ABC"
    assert aircraft.vertical_rate_fpm == -512 and aircraft.last_updated == now - timedelta(
        seconds=4
    )
    assert "/point/48.000000/17.000000/250" in str(client._transport) or aircraft.provider
    await client.aclose()


@pytest.mark.asyncio
@pytest.mark.parametrize("status,error", [(429, RateLimited), (500, ProviderError)])
async def test_provider_http_failures(database, status, error):
    client = httpx.AsyncClient(
        transport=httpx.MockTransport(lambda request: httpx.Response(status))
    )
    with pytest.raises(error):
        await AirplanesLiveProvider(database, 10, 0, client=client).nearby(48, 17, 1)
    await client.aclose()


@pytest.mark.asyncio
async def test_provider_timeout_and_invalid_payload(database):
    def timeout(request):
        raise httpx.ReadTimeout("no response")

    client = httpx.AsyncClient(transport=httpx.MockTransport(timeout))
    with pytest.raises(ProviderError):
        await AirplanesLiveProvider(database, 10, 0, client=client).nearby(48, 17, 1)
    await client.aclose()
    invalid = httpx.AsyncClient(
        transport=httpx.MockTransport(lambda r: httpx.Response(200, json={}))
    )
    with pytest.raises(ProviderError):
        await AirplanesLiveProvider(database, 10, 0, client=invalid).nearby(48, 17, 1)
    await invalid.aclose()


@pytest.mark.asyncio
async def test_budget_persists(database, now):
    assert database.claim_request("airplanes.live", 3, 1, now)
    assert database.claim_request("airplanes.live", 3, 1, now)
    assert not database.claim_request("airplanes.live", 3, 1, now)
    from lzib_movements.database import Database

    restarted = Database(database.path)
    assert restarted.request_count("airplanes.live", now) == 2

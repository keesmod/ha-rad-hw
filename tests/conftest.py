"""Shared fixtures for the RAD Hoeksche Waard Afval tests.

All tests run in the Europe/Amsterdam time zone with time frozen at
2026-11-19 10:00 local time. The Ximmio API is mocked; no test reaches the
network. The address used throughout (1234AB 1) is fictitious.
"""

from __future__ import annotations

import json
from collections.abc import Generator
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, patch

import pytest
from freezegun.api import FrozenDateTimeFactory
from homeassistant.core import HomeAssistant
from pytest_homeassistant_custom_component.common import MockConfigEntry
from pytest_homeassistant_custom_component.test_util.aiohttp import (
    AiohttpClientMocker,
)

from custom_components.rad_hw_afval.const import (
    API_URL,
    CONF_DATE_FORMAT,
    CONF_POSTAL_CODE,
    CONF_RESOURCES,
    CONF_STREET_NUMBER,
    DOMAIN,
)

FIXTURES = Path(__file__).parent / "fixtures"

FETCH_ADDRESS_URL = f"{API_URL}FetchAdress"
GET_CALENDAR_URL = f"{API_URL}GetCalendar"

TIME_ZONE = "Europe/Amsterdam"
FROZEN_TIME = "2026-11-19 10:00:00+01:00"

ALL_WASTE_TYPES = ["rest", "gft", "papier", "pmd"]
UNIQUE_ID = "1234AB_1"
TITLE = "1234AB 1"
ENTRY_DATA = {
    CONF_POSTAL_CODE: "1234AB",
    CONF_STREET_NUMBER: "1",
    CONF_DATE_FORMAT: "%d-%m-%Y",
}


def load_json(name: str) -> Any:
    """Load a JSON fixture from tests/fixtures."""
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


def create_entry(
    *,
    data: dict[str, Any] | None = None,
    options: dict[str, Any] | None = None,
    unique_id: str = UNIQUE_ID,
    title: str = TITLE,
) -> MockConfigEntry:
    """Create (but do not add) a config entry for the fictitious address."""
    return MockConfigEntry(
        domain=DOMAIN,
        unique_id=unique_id,
        title=title,
        data=dict(ENTRY_DATA if data is None else data),
        options={CONF_RESOURCES: list(ALL_WASTE_TYPES)} if options is None else options,
    )


def mock_api(
    aioclient_mock: AiohttpClientMocker,
    *,
    address: dict[str, Any] | None = None,
    calendar: dict[str, Any] | None = None,
    address_kwargs: dict[str, Any] | None = None,
    calendar_kwargs: dict[str, Any] | None = None,
) -> None:
    """Register FetchAdress and GetCalendar responses.

    By default both endpoints answer with the fixture files. Pass
    ``address_kwargs``/``calendar_kwargs`` (e.g. ``{"status": 500}``) to
    replace a response entirely.
    """
    if address is None:
        address = load_json("address.json")
    if calendar is None:
        calendar = load_json("calendar.json")
    aioclient_mock.post(FETCH_ADDRESS_URL, **(address_kwargs or {"json": address}))
    aioclient_mock.post(GET_CALENDAR_URL, **(calendar_kwargs or {"json": calendar}))


def address_with_letter(letter: str) -> dict[str, Any]:
    """Return the address fixture as the API answers a lookup with a house letter."""
    address = load_json("address.json")
    for item in address["dataList"]:
        item["HouseLetter"] = letter
    return address


def api_payloads(aioclient_mock: AiohttpClientMocker, url: str) -> list[Any]:
    """Return the JSON payloads that were POSTed to ``url``."""
    return [
        data
        for method, called_url, data, _headers in aioclient_mock.mock_calls
        if method.lower() == "post" and str(called_url) == url
    ]


@pytest.fixture(autouse=True)
def auto_enable_custom_integrations(
    enable_custom_integrations: None,
) -> Generator[None]:
    """Allow Home Assistant to load the custom integration."""
    yield


@pytest.fixture(autouse=True)
async def set_time_zone(hass: HomeAssistant) -> None:
    """Run every test in the Dutch time zone."""
    await hass.config.async_set_time_zone(TIME_ZONE)


@pytest.fixture(autouse=True)
def frozen_time(freezer: FrozenDateTimeFactory) -> FrozenDateTimeFactory:
    """Freeze time at 2026-11-19 10:00 Europe/Amsterdam."""
    freezer.move_to(FROZEN_TIME)
    return freezer


@pytest.fixture
def mock_config_entry() -> MockConfigEntry:
    """Return a config entry for 1234AB 1 with all waste types selected."""
    return create_entry()


@pytest.fixture
def mock_api_ok(aioclient_mock: AiohttpClientMocker) -> AiohttpClientMocker:
    """Mock both API endpoints with the fixture responses."""
    mock_api(aioclient_mock)
    return aioclient_mock


@pytest.fixture
def mock_setup_entry() -> Generator[AsyncMock]:
    """Prevent the config flow from setting up the created entry."""
    with patch(
        "custom_components.rad_hw_afval.async_setup_entry", return_value=True
    ) as mock_setup:
        yield mock_setup


@pytest.fixture
async def init_integration(
    hass: HomeAssistant,
    mock_config_entry: MockConfigEntry,
    mock_api_ok: AiohttpClientMocker,
) -> MockConfigEntry:
    """Set up the integration with the fixture responses."""
    mock_config_entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(mock_config_entry.entry_id)
    await hass.async_block_till_done()
    return mock_config_entry

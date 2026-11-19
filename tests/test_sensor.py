"""Tests for the RAD Hoeksche Waard Afval sensors."""

from __future__ import annotations

from datetime import timedelta
from http import HTTPStatus
from typing import Any

import pytest
from freezegun.api import FrozenDateTimeFactory
from homeassistant.components.sensor import SensorDeviceClass
from homeassistant.config_entries import ConfigEntryState
from homeassistant.const import (
    ATTR_DEVICE_CLASS,
    ATTR_FRIENDLY_NAME,
    ATTR_ICON,
    STATE_UNAVAILABLE,
)
from homeassistant.core import HomeAssistant
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers import entity_registry as er
from pytest_homeassistant_custom_component.common import (
    MockConfigEntry,
    async_fire_time_changed,
)
from pytest_homeassistant_custom_component.test_util.aiohttp import (
    AiohttpClientMocker,
)

from custom_components.rad_hw_afval.const import (
    CONF_DATE_FORMAT,
    CONF_POSTAL_CODE,
    CONF_STREET_NUMBER,
    DOMAIN,
    RETRY_INTERVAL,
    SCAN_INTERVAL,
)

from .conftest import (
    ALL_WASTE_TYPES,
    ENTITY_IDS,
    FETCH_ADDRESS_URL,
    GET_CALENDAR_URL,
    V122_ENTITY_IDS,
    api_payloads,
    create_entry,
    load_json,
    mock_api,
)

NAMES = {
    "rest": "Restafval",
    "gft": "GFT",
    "papier": "Oud Papier",
    "pmd": "PMD",
}
ICONS = {
    "rest": "mdi:trash-can",
    "gft": "mdi:leaf",
    "papier": "mdi:newspaper",
    "pmd": "mdi:recycle",
}


async def _setup(hass: HomeAssistant, entry: MockConfigEntry) -> None:
    """Add and set up a config entry."""
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()


async def _advance(
    hass: HomeAssistant, freezer: FrozenDateTimeFactory, delta: timedelta
) -> None:
    """Move time forward and run everything that became due."""
    freezer.tick(delta)
    async_fire_time_changed(hass)
    await hass.async_block_till_done(wait_background_tasks=True)


def _assert_pickup(
    hass: HomeAssistant,
    entity_id: str,
    state: str,
    days: int,
    formatted: str,
    *,
    past: bool = False,
) -> None:
    """Check the state and the pickup attributes of one sensor."""
    current = hass.states.get(entity_id)
    assert current is not None, entity_id
    assert current.state == state, entity_id
    assert current.attributes["next_pickup_in_days"] == days, entity_id
    assert current.attributes["is_past_date"] is past, entity_id
    assert current.attributes["formatted_date"] == formatted, entity_id


async def test_sensor_states(
    hass: HomeAssistant, init_integration: MockConfigEntry
) -> None:
    """All four sensors show the next pickup at 2026-11-19 10:00."""
    expected = {
        "rest": ("2026-12-04", 15, "04-12-2026"),
        "gft": ("2026-11-27", 8, "27-11-2026"),
        "papier": ("2026-11-20", 1, "20-11-2026"),
        "pmd": ("2026-11-19", 0, "19-11-2026"),  # today counts
    }
    for waste_type, (state, days, formatted) in expected.items():
        current = hass.states.get(ENTITY_IDS[waste_type])
        assert current is not None
        assert current.state == state
        assert current.attributes == {
            "next_pickup_in_days": days,
            "waste_type": waste_type,
            "is_past_date": False,
            "formatted_date": formatted,
            ATTR_DEVICE_CLASS: SensorDeviceClass.DATE,
            ATTR_ICON: ICONS[waste_type],
            ATTR_FRIENDLY_NAME: f"RAD HW Afval 1234AB 1 {NAMES[waste_type]}",
        }


async def test_entity_registry(
    hass: HomeAssistant, init_integration: MockConfigEntry
) -> None:
    """All four entities use the v1.2.2 unique IDs and start enabled."""
    entity_registry = er.async_get(hass)
    entries = er.async_entries_for_config_entry(
        entity_registry, init_integration.entry_id
    )
    assert {entry.entity_id: entry.unique_id for entry in entries} == {
        ENTITY_IDS[waste_type]: f"1234AB_1_{waste_type}"
        for waste_type in ALL_WASTE_TYPES
    }
    for entry in entries:
        assert entry.disabled_by is None
        assert entry.has_entity_name
        assert entry.original_name == NAMES[entry.unique_id.rsplit("_", 1)[1]]


async def test_device(hass: HomeAssistant, init_integration: MockConfigEntry) -> None:
    """One service device carries the manifest version."""
    devices = dr.async_entries_for_config_entry(
        dr.async_get(hass), init_integration.entry_id
    )
    assert len(devices) == 1
    device = devices[0]
    assert device.identifiers == {(DOMAIN, "1234AB_1")}
    assert device.name == "RAD HW Afval 1234AB 1"
    assert device.entry_type is dr.DeviceEntryType.SERVICE
    assert device.sw_version == "1.3.0"
    assert device.manufacturer == "RAD Hoeksche Waard"
    assert device.model == "Afvalkalender"

    entity_registry = er.async_get(hass)
    for entity_id in ENTITY_IDS.values():
        assert entity_registry.async_get(entity_id).device_id == device.id


async def test_date_format_option_overrides_data(
    hass: HomeAssistant, mock_api_ok: AiohttpClientMocker
) -> None:
    """The date format from the options wins over the one from setup."""
    entry = create_entry(options={CONF_DATE_FORMAT: "%A %d %B %Y"})
    await _setup(hass, entry)
    assert (
        hass.states.get(ENTITY_IDS["rest"]).attributes["formatted_date"]
        == "Friday 04 December 2026"
    )


@pytest.mark.parametrize(
    ("data_format", "options_format"),
    [
        pytest.param("", None, id="empty_in_data"),
        pytest.param("%d-%m-%Y", "", id="empty_in_options"),
        pytest.param(None, None, id="missing"),
    ],
)
async def test_empty_date_format_falls_back_to_default(
    hass: HomeAssistant,
    mock_api_ok: AiohttpClientMocker,
    data_format: str | None,
    options_format: str | None,
) -> None:
    """An empty or missing stored date format uses the default, as in 1.2.x."""
    data = {CONF_POSTAL_CODE: "1234AB", CONF_STREET_NUMBER: "1"}
    if data_format is not None:
        data[CONF_DATE_FORMAT] = data_format
    options: dict[str, Any] = {}
    if options_format is not None:
        options[CONF_DATE_FORMAT] = options_format
    await _setup(hass, create_entry(data=data, options=options))
    assert (
        hass.states.get(ENTITY_IDS["rest"]).attributes["formatted_date"] == "04-12-2026"
    )


async def test_midnight_rollover_without_api_call(
    hass: HomeAssistant,
    mock_config_entry: MockConfigEntry,
    mock_api_ok: AiohttpClientMocker,
    frozen_time: FrozenDateTimeFactory,
) -> None:
    """At local midnight the state moves on without fetching the calendar."""
    # 23:00 on a PMD pickup day; the next scheduled refresh is at 11:00.
    frozen_time.move_to("2026-11-19 23:00:00+01:00")
    await _setup(hass, mock_config_entry)
    _assert_pickup(hass, ENTITY_IDS["pmd"], "2026-11-19", 0, "19-11-2026")
    _assert_pickup(hass, ENTITY_IDS["papier"], "2026-11-20", 1, "20-11-2026")
    calls = mock_api_ok.call_count

    # Just before midnight nothing changes.
    await _advance(hass, frozen_time, timedelta(minutes=59, seconds=58))
    _assert_pickup(hass, ENTITY_IDS["pmd"], "2026-11-19", 0, "19-11-2026")

    # Just after local midnight (23:00 UTC) the sensors roll over.
    await _advance(hass, frozen_time, timedelta(seconds=5))
    _assert_pickup(hass, ENTITY_IDS["pmd"], "2026-11-26", 6, "26-11-2026")
    _assert_pickup(hass, ENTITY_IDS["papier"], "2026-11-20", 0, "20-11-2026")
    _assert_pickup(hass, ENTITY_IDS["gft"], "2026-11-27", 7, "27-11-2026")
    _assert_pickup(hass, ENTITY_IDS["rest"], "2026-12-04", 14, "04-12-2026")
    assert mock_api_ok.call_count == calls

    # The next night it rolls over again, still without an API call.
    await _advance(hass, frozen_time, timedelta(days=1))
    assert mock_api_ok.call_count == calls + 1  # only the 11:00 refresh
    _assert_pickup(hass, ENTITY_IDS["papier"], "2026-12-18", 27, "18-12-2026")


async def test_past_date_fallback(
    hass: HomeAssistant,
    mock_config_entry: MockConfigEntry,
    mock_api_ok: AiohttpClientMocker,
    frozen_time: FrozenDateTimeFactory,
) -> None:
    """Without future dates the latest past pickup is shown and flagged."""
    frozen_time.move_to("2027-01-05 10:00:00+01:00")
    await _setup(hass, mock_config_entry)

    _assert_pickup(hass, ENTITY_IDS["rest"], "2027-01-02", -3, "02-01-2027", past=True)
    _assert_pickup(hass, ENTITY_IDS["pmd"], "2026-12-31", -5, "31-12-2026", past=True)
    _assert_pickup(hass, ENTITY_IDS["gft"], "2026-12-19", -17, "19-12-2026", past=True)
    _assert_pickup(
        hass, ENTITY_IDS["papier"], "2026-12-18", -18, "18-12-2026", past=True
    )


async def test_type_without_dates_unavailable(
    hass: HomeAssistant,
    mock_config_entry: MockConfigEntry,
    aioclient_mock: AiohttpClientMocker,
) -> None:
    """A waste type that is missing from the calendar is unavailable."""
    calendar = load_json("calendar.json")
    calendar["dataList"] = [
        entry for entry in calendar["dataList"] if entry["_pickupTypeText"] != "PAPER"
    ]
    mock_api(aioclient_mock, calendar=calendar)
    await _setup(hass, mock_config_entry)

    papier = hass.states.get(ENTITY_IDS["papier"])
    assert papier.state == STATE_UNAVAILABLE
    assert "next_pickup_in_days" not in papier.attributes
    for waste_type in ("rest", "gft", "pmd"):
        assert hass.states.get(ENTITY_IDS[waste_type]).state != STATE_UNAVAILABLE


async def test_failed_refresh_and_recovery(
    hass: HomeAssistant,
    init_integration: MockConfigEntry,
    aioclient_mock: AiohttpClientMocker,
    frozen_time: FrozenDateTimeFactory,
) -> None:
    """A failed refresh makes sensors unavailable and retries after 30 min."""
    coordinator = init_integration.runtime_data
    assert coordinator.update_interval == SCAN_INTERVAL

    aioclient_mock.clear_requests()
    mock_api(aioclient_mock, calendar_kwargs={"status": HTTPStatus.SERVICE_UNAVAILABLE})

    # Nothing happens before the 12 h interval has passed.
    await _advance(hass, frozen_time, SCAN_INTERVAL - timedelta(minutes=1))
    assert aioclient_mock.call_count == 0

    await _advance(hass, frozen_time, timedelta(minutes=1))
    assert len(api_payloads(aioclient_mock, GET_CALENDAR_URL)) == 1
    assert not coordinator.last_update_success
    assert coordinator.update_interval == RETRY_INTERVAL == timedelta(minutes=30)
    for entity_id in ENTITY_IDS.values():
        assert hass.states.get(entity_id).state == STATE_UNAVAILABLE

    aioclient_mock.clear_requests()
    mock_api(aioclient_mock)

    # The retry runs after 30 minutes, not earlier.
    await _advance(hass, frozen_time, RETRY_INTERVAL - timedelta(minutes=1))
    assert aioclient_mock.call_count == 0

    await _advance(hass, frozen_time, timedelta(minutes=1))
    assert len(api_payloads(aioclient_mock, FETCH_ADDRESS_URL)) == 1
    assert len(api_payloads(aioclient_mock, GET_CALENDAR_URL)) == 1
    assert coordinator.last_update_success
    assert coordinator.update_interval == SCAN_INTERVAL
    # 2026-11-19 22:30 local.
    _assert_pickup(hass, ENTITY_IDS["rest"], "2026-12-04", 15, "04-12-2026")
    _assert_pickup(hass, ENTITY_IDS["pmd"], "2026-11-19", 0, "19-11-2026")

    # Back on the 12 h schedule.
    aioclient_mock.clear_requests()
    mock_api(aioclient_mock)
    await _advance(hass, frozen_time, RETRY_INTERVAL)
    assert aioclient_mock.call_count == 0
    await _advance(hass, frozen_time, SCAN_INTERVAL - RETRY_INTERVAL)
    assert len(api_payloads(aioclient_mock, GET_CALENDAR_URL)) == 1


async def test_v122_entity_ids_are_kept(
    hass: HomeAssistant,
    mock_config_entry: MockConfigEntry,
    mock_api_ok: AiohttpClientMocker,
) -> None:
    """Existing v1.2.2 entities keep their entity_id after the upgrade."""
    mock_config_entry.add_to_hass(hass)
    entity_registry = er.async_get(hass)
    for waste_type, entity_id in V122_ENTITY_IDS.items():
        registered = entity_registry.async_get_or_create(
            "sensor",
            DOMAIN,
            f"1234AB_1_{waste_type}",
            config_entry=mock_config_entry,
            suggested_object_id=entity_id.split(".", 1)[1],
            original_name=f"RAD HW Afval {NAMES[waste_type]}",
        )
        assert registered.entity_id == entity_id

    assert await hass.config_entries.async_setup(mock_config_entry.entry_id)
    await hass.async_block_till_done()
    assert mock_config_entry.state is ConfigEntryState.LOADED

    entries = er.async_entries_for_config_entry(
        entity_registry, mock_config_entry.entry_id
    )
    assert sorted(entry.entity_id for entry in entries) == sorted(
        V122_ENTITY_IDS.values()
    )
    for waste_type, entity_id in V122_ENTITY_IDS.items():
        assert (
            entity_registry.async_get_entity_id(
                "sensor", DOMAIN, f"1234AB_1_{waste_type}"
            )
            == entity_id
        )
        assert hass.states.get(entity_id).state != STATE_UNAVAILABLE
        assert hass.states.get(ENTITY_IDS[waste_type]) is None
    assert hass.states.get(V122_ENTITY_IDS["rest"]).state == "2026-12-04"

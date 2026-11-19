"""Tests for setting up and unloading the integration."""

from __future__ import annotations

import logging
from datetime import timedelta
from http import HTTPStatus
from typing import Any

import pytest
from freezegun.api import FrozenDateTimeFactory
from homeassistant.config_entries import ConfigEntryState
from homeassistant.const import (
    ATTR_RESTORED,
    EVENT_STATE_CHANGED,
    STATE_UNAVAILABLE,
)
from homeassistant.core import Event, EventStateChangedData, HomeAssistant, callback
from pytest_homeassistant_custom_component.common import (
    MockConfigEntry,
    async_fire_time_changed,
)
from pytest_homeassistant_custom_component.test_util.aiohttp import (
    AiohttpClientMocker,
)

from custom_components.rad_hw_afval.api import parse_calendar
from custom_components.rad_hw_afval.const import (
    CONF_DATE_FORMAT,
    RETRY_INTERVAL,
    SCAN_INTERVAL,
)
from custom_components.rad_hw_afval.coordinator import RadAfvalDataUpdateCoordinator

from .conftest import (
    ENTITY_IDS,
    FETCH_ADDRESS_URL,
    GET_CALENDAR_URL,
    api_payloads,
    load_json,
    mock_api,
)

INTEGRATION_LOGGER = "custom_components.rad_hw_afval"
ENTITY_ID = ENTITY_IDS["rest"]


def _traceback_records(caplog: pytest.LogCaptureFixture) -> list[logging.LogRecord]:
    """Return WARNING or worse records that carry a traceback.

    Home Assistant itself logs the full exception at DEBUG level; that is
    expected and not counted here.
    """
    return [
        record
        for record in caplog.records
        if record.levelno >= logging.WARNING and (record.exc_info or record.exc_text)
    ]


async def test_setup_and_unload(
    hass: HomeAssistant, init_integration: MockConfigEntry
) -> None:
    """The entry loads, stores its coordinator and unloads cleanly."""
    entry = init_integration
    assert entry.state is ConfigEntryState.LOADED

    coordinator = entry.runtime_data
    assert isinstance(coordinator, RadAfvalDataUpdateCoordinator)
    assert coordinator.config_entry is entry
    assert coordinator.data == parse_calendar(load_json("calendar.json")["dataList"])
    assert coordinator.update_interval == SCAN_INTERVAL == timedelta(hours=12)
    assert hass.states.get(ENTITY_ID) is not None

    assert await hass.config_entries.async_unload(entry.entry_id)
    await hass.async_block_till_done()

    assert entry.state is ConfigEntryState.NOT_LOADED
    # Registered entities stay behind as "unavailable, restored".
    state = hass.states.get(ENTITY_ID)
    assert state.state == STATE_UNAVAILABLE
    assert state.attributes.get(ATTR_RESTORED) is True


@pytest.mark.parametrize(
    ("api", "reason"),
    [
        pytest.param(
            {"address_kwargs": {"status": HTTPStatus.INTERNAL_SERVER_ERROR}},
            "Error calling FetchAdress",
            id="address_http_error",
        ),
        pytest.param(
            {"calendar_kwargs": {"status": HTTPStatus.INTERNAL_SERVER_ERROR}},
            "Error calling GetCalendar",
            id="calendar_http_error",
        ),
        pytest.param(
            {"calendar": {"status": False, "dataList": None, "messageCode": 2}},
            "GetCalendar returned an error",
            id="calendar_status_false",
        ),
        pytest.param(
            {"address": {"status": True, "dataList": []}},
            "Address 1234AB 1 not found",
            id="address_not_found",
        ),
    ],
)
async def test_setup_retry_on_first_refresh_failure(
    hass: HomeAssistant,
    mock_config_entry: MockConfigEntry,
    aioclient_mock: AiohttpClientMocker,
    caplog: pytest.LogCaptureFixture,
    api: dict[str, Any],
    reason: str,
) -> None:
    """A failing first refresh puts the entry in SETUP_RETRY without tracebacks."""
    mock_api(aioclient_mock, **api)
    mock_config_entry.add_to_hass(hass)

    assert not await hass.config_entries.async_setup(mock_config_entry.entry_id)
    await hass.async_block_till_done()

    assert mock_config_entry.state is ConfigEntryState.SETUP_RETRY
    assert reason in (mock_config_entry.reason or "")
    assert not hasattr(mock_config_entry, "runtime_data")
    assert hass.states.get(ENTITY_ID) is None
    assert not _traceback_records(caplog)
    assert not [
        record
        for record in caplog.records
        if record.name.startswith(INTEGRATION_LOGGER)
        and record.levelno >= logging.ERROR
    ]


async def test_setup_retry_recovers(
    hass: HomeAssistant,
    mock_config_entry: MockConfigEntry,
    aioclient_mock: AiohttpClientMocker,
    frozen_time: FrozenDateTimeFactory,
) -> None:
    """After SETUP_RETRY the entry loads once the API answers again."""
    mock_api(aioclient_mock, address_kwargs={"status": HTTPStatus.BAD_GATEWAY})
    mock_config_entry.add_to_hass(hass)
    await hass.config_entries.async_setup(mock_config_entry.entry_id)
    await hass.async_block_till_done()
    assert mock_config_entry.state is ConfigEntryState.SETUP_RETRY

    aioclient_mock.clear_requests()
    mock_api(aioclient_mock)
    frozen_time.tick(timedelta(minutes=1))
    async_fire_time_changed(hass)
    await hass.async_block_till_done(wait_background_tasks=True)

    assert mock_config_entry.state is ConfigEntryState.LOADED
    assert hass.states.get(ENTITY_ID).state == "2026-12-04"


async def test_failed_scheduled_refresh_logs_no_traceback(
    hass: HomeAssistant,
    init_integration: MockConfigEntry,
    aioclient_mock: AiohttpClientMocker,
    frozen_time: FrozenDateTimeFactory,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """A failing scheduled refresh is logged once, without a traceback."""
    coordinator = init_integration.runtime_data
    aioclient_mock.clear_requests()
    mock_api(aioclient_mock, calendar_kwargs={"status": HTTPStatus.BAD_GATEWAY})
    caplog.clear()

    frozen_time.tick(SCAN_INTERVAL)
    async_fire_time_changed(hass)
    await hass.async_block_till_done(wait_background_tasks=True)

    assert not coordinator.last_update_success
    assert coordinator.update_interval == RETRY_INTERVAL
    assert "Error calling GetCalendar" in caplog.text
    assert not _traceback_records(caplog)

    # A second failure in a row is not logged at ERROR again.
    caplog.clear()
    frozen_time.tick(RETRY_INTERVAL)
    async_fire_time_changed(hass)
    await hass.async_block_till_done(wait_background_tasks=True)
    # First failure used the cached address ID; the retry looked it up again.
    assert len(api_payloads(aioclient_mock, FETCH_ADDRESS_URL)) == 1
    assert len(api_payloads(aioclient_mock, GET_CALENDAR_URL)) == 2
    assert coordinator.update_interval == RETRY_INTERVAL
    assert not [r for r in caplog.records if r.levelno >= logging.ERROR]


async def test_empty_calendar_warns(
    hass: HomeAssistant,
    mock_config_entry: MockConfigEntry,
    aioclient_mock: AiohttpClientMocker,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """An address without any known pickups loads but warns and has no state."""
    mock_api(aioclient_mock, calendar={"status": True, "dataList": []})
    mock_config_entry.add_to_hass(hass)

    assert await hass.config_entries.async_setup(mock_config_entry.entry_id)
    await hass.async_block_till_done()

    assert mock_config_entry.state is ConfigEntryState.LOADED
    assert "No pickup dates found for 1234AB 1; check the address" in caplog.text
    assert hass.states.get(ENTITY_ID).state == STATE_UNAVAILABLE


async def test_options_update_reloads_entry(
    hass: HomeAssistant,
    init_integration: MockConfigEntry,
    aioclient_mock: AiohttpClientMocker,
) -> None:
    """Changing the options reloads the entry with a new coordinator."""
    entry = init_integration
    old_coordinator = entry.runtime_data
    calls = aioclient_mock.call_count

    hass.config_entries.async_update_entry(
        entry, options={CONF_DATE_FORMAT: "%Y/%m/%d"}
    )
    await hass.async_block_till_done()

    assert entry.state is ConfigEntryState.LOADED
    assert entry.runtime_data is not old_coordinator
    assert aioclient_mock.call_count == calls + 2
    assert hass.states.get(ENTITY_ID).attributes["formatted_date"] == "2026/12/04"
    # All waste types are still provided by the integration.
    for entity_id in ENTITY_IDS.values():
        state = hass.states.get(entity_id)
        assert state.state != STATE_UNAVAILABLE, entity_id
        assert ATTR_RESTORED not in state.attributes


@pytest.mark.parametrize("changed", [False, True], ids=["unchanged", "changed"])
async def test_unchanged_calendar_does_not_write_state(
    hass: HomeAssistant,
    init_integration: MockConfigEntry,
    aioclient_mock: AiohttpClientMocker,
    frozen_time: FrozenDateTimeFactory,
    changed: bool,
) -> None:
    """A refresh that returns the same calendar does not touch the sensors.

    An identical state write never fires state_changed, so the check that
    always_update=False skips the write is that ``last_reported`` stays put.
    """
    coordinator = init_integration.runtime_data
    assert coordinator.always_update is False

    calendar = load_json("calendar.json")
    if changed:
        # An extra restafval pickup tomorrow makes it the next one.
        calendar["dataList"].append(
            {"pickupDates": ["2026-11-20T00:00:00"], "_pickupTypeText": "GREY"}
        )
    aioclient_mock.clear_requests()
    mock_api(aioclient_mock, calendar=calendar)

    # HA updates last_reported in place, so keep the values, not the states.
    reported = {
        entity_id: hass.states.get(entity_id).last_reported
        for entity_id in ENTITY_IDS.values()
    }
    changes: list[str] = []

    @callback
    def _changed(event: Event[EventStateChangedData]) -> None:
        if event.data["entity_id"] in reported:
            changes.append(event.data["entity_id"])

    hass.bus.async_listen(EVENT_STATE_CHANGED, _changed)

    frozen_time.tick(SCAN_INTERVAL)
    async_fire_time_changed(hass)
    await hass.async_block_till_done(wait_background_tasks=True)

    assert len(api_payloads(aioclient_mock, GET_CALENDAR_URL)) == 1
    assert coordinator.last_update_success
    if not changed:
        assert changes == []
        for entity_id, last_reported in reported.items():
            assert hass.states.get(entity_id).last_reported == last_reported
    else:
        assert changes == [ENTITY_ID]
        assert hass.states.get(ENTITY_ID).state == "2026-11-20"
        # The listeners ran, so the unchanged sensors were written as well.
        for entity_id, last_reported in reported.items():
            assert hass.states.get(entity_id).last_reported > last_reported

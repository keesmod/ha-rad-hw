"""Tests for the Ximmio API client and the calendar helpers."""

from __future__ import annotations

import asyncio
import logging
from datetime import date
from http import HTTPStatus
from typing import Any
from unittest.mock import patch

import aiohttp
import pytest
from homeassistant.core import HomeAssistant
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from pytest_homeassistant_custom_component.test_util.aiohttp import (
    AiohttpClientMocker,
)

from custom_components.rad_hw_afval.api import (
    RadAfvalAddressNotFoundError,
    RadAfvalApiClient,
    RadAfvalError,
    next_pickup,
    parse_calendar,
)
from custom_components.rad_hw_afval.const import COMMUNITY, COMPANY_CODE

from .conftest import (
    FETCH_ADDRESS_URL,
    GET_CALENDAR_URL,
    address_with_letter,
    api_payloads,
    load_json,
    mock_api,
)

TODAY = date(2026, 11, 19)
ADDRESS_ID = "0000000000000001"


def _entry(code: Any, *dates: Any) -> dict[str, Any]:
    """Build one GetCalendar entry."""
    return {"_pickupTypeText": code, "pickupDates": list(dates)}


# --- parse_calendar ---------------------------------------------------------


def test_parse_calendar_fixture() -> None:
    """The saved live response maps to sorted dates for all four types."""
    result = parse_calendar(load_json("calendar.json")["dataList"])

    assert set(result) == {"rest", "gft", "papier", "pmd"}
    assert result["rest"] == [
        date(2026, 8, 14),
        date(2026, 9, 11),
        date(2026, 10, 9),
        date(2026, 11, 6),
        date(2026, 12, 4),
        date(2027, 1, 2),
    ]
    assert result["papier"] == [
        date(2026, 8, 28),
        date(2026, 9, 25),
        date(2026, 10, 23),
        date(2026, 11, 20),
        date(2026, 12, 18),
    ]
    assert len(result["gft"]) == 11
    assert (result["gft"][0], result["gft"][-1]) == (
        date(2026, 8, 7),
        date(2026, 12, 19),
    )
    assert len(result["pmd"]) == 22
    assert (result["pmd"][0], result["pmd"][-1]) == (
        date(2026, 8, 6),
        date(2026, 12, 31),
    )


@pytest.mark.parametrize(
    ("code", "waste_type"),
    [
        ("GREY", "rest"),
        ("GREEN", "gft"),
        ("PAPER", "papier"),
        ("PACKAGES", "pmd"),
        ("grey", "rest"),
    ],
)
def test_parse_calendar_mapping(code: str, waste_type: str) -> None:
    """Each Ximmio pickup type code maps to one sensor key."""
    assert parse_calendar([_entry(code, "2026-11-19T00:00:00")]) == {
        waste_type: [date(2026, 11, 19)]
    }


def test_parse_calendar_iso_formats() -> None:
    """Dates with and without the time suffix are accepted."""
    assert parse_calendar([_entry("GREY", "2026-11-19T00:00:00", "2026-11-26")]) == {
        "rest": [date(2026, 11, 19), date(2026, 11, 26)]
    }


def test_parse_calendar_sorts_and_deduplicates() -> None:
    """Dates are sorted and duplicates, also across entries, are merged."""
    entries = [
        _entry("GREY", "2026-12-04T00:00:00", "2026-11-06T00:00:00"),
        _entry("GREY", "2026-11-06T00:00:00", "2026-10-09T00:00:00"),
        _entry("GREY", "2026-12-04T00:00:00"),
    ]
    assert parse_calendar(entries) == {
        "rest": [date(2026, 10, 9), date(2026, 11, 6), date(2026, 12, 4)]
    }


def test_parse_calendar_ignores_unknown_types() -> None:
    """Pickup types without a sensor are dropped."""
    entries = [
        _entry("BULKLITTER", "2026-11-19T00:00:00"),
        _entry("TEXTILE", "2026-11-20T00:00:00"),
        _entry("", "2026-11-21T00:00:00"),
        _entry(None, "2026-11-22T00:00:00"),
        {"pickupDates": ["2026-11-23T00:00:00"]},
        _entry("GREEN", "2026-11-27T00:00:00"),
    ]
    assert parse_calendar(entries) == {"gft": [date(2026, 11, 27)]}


def test_parse_calendar_skips_invalid_dates(caplog: pytest.LogCaptureFixture) -> None:
    """Unparseable dates are skipped with a warning; valid ones are kept."""
    entries = [
        _entry(
            "PAPER",
            "not a date",
            "2026-13-01T00:00:00",
            None,
            "",
            "2026-11-20T00:00:00",
        )
    ]
    with caplog.at_level(logging.WARNING):
        assert parse_calendar(entries) == {"papier": [date(2026, 11, 20)]}
    assert "Ignoring invalid pickup date 'not a date'" in caplog.text
    assert "Ignoring invalid pickup date '2026-13-01T00:00:00'" in caplog.text


def test_parse_calendar_skips_non_dict_entries() -> None:
    """Entries that are not objects are ignored."""
    entries = [None, "GREY", 42, ["GREY"], _entry("PACKAGES", "2026-11-19T00:00:00")]
    assert parse_calendar(entries) == {"pmd": [date(2026, 11, 19)]}


def test_parse_calendar_without_dates() -> None:
    """Known types without dates do not produce a key."""
    entries = [
        {"_pickupTypeText": "GREY", "pickupDates": None},
        {"_pickupTypeText": "GREEN"},
        _entry("PAPER"),
    ]
    assert parse_calendar(entries) == {}
    assert parse_calendar([]) == {}


# --- next_pickup ------------------------------------------------------------

DATES = [date(2026, 11, 6), date(2026, 12, 4), date(2027, 1, 2)]


@pytest.mark.parametrize(
    ("today", "expected"),
    [
        pytest.param(date(2026, 1, 1), date(2026, 11, 6), id="before_all"),
        pytest.param(date(2026, 11, 19), date(2026, 12, 4), id="future"),
        pytest.param(date(2026, 12, 4), date(2026, 12, 4), id="today_counts"),
        pytest.param(date(2026, 12, 5), date(2027, 1, 2), id="next_year"),
        pytest.param(date(2027, 1, 3), date(2027, 1, 2), id="past_fallback"),
        pytest.param(date(2027, 6, 1), date(2027, 1, 2), id="long_past_fallback"),
    ],
)
def test_next_pickup(today: date, expected: date) -> None:
    """Return the first date on or after today, else the latest one."""
    assert next_pickup(DATES, today) == expected


def test_next_pickup_empty() -> None:
    """No dates means no next pickup."""
    assert next_pickup([], TODAY) is None


# --- RadAfvalApiClient ------------------------------------------------------


@pytest.fixture
def client(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker
) -> RadAfvalApiClient:
    """Return a client for the fictitious address 1234AB 1."""
    return RadAfvalApiClient(async_get_clientsession(hass), "1234AB", "1")


async def test_get_pickup_dates(
    aioclient_mock: AiohttpClientMocker, client: RadAfvalApiClient
) -> None:
    """The client looks up the address and fetches the calendar."""
    mock_api(aioclient_mock)

    result = await client.async_get_pickup_dates(TODAY)

    assert result == parse_calendar(load_json("calendar.json")["dataList"])
    assert api_payloads(aioclient_mock, FETCH_ADDRESS_URL) == [
        {
            "companyCode": COMPANY_CODE,
            "postCode": "1234AB",
            "houseNumber": 1,
            "houseLetter": "",
            "houseNumberAddition": "",
        }
    ]
    assert api_payloads(aioclient_mock, GET_CALENDAR_URL) == [
        {
            "companyCode": COMPANY_CODE,
            "uniqueAddressID": ADDRESS_ID,
            "startDate": "2026-08-21",
            "endDate": "2028-12-31",
            "community": COMMUNITY,
        }
    ]


async def test_client_normalizes_address(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker
) -> None:
    """Postal code, number and letter are normalized before the lookup."""
    mock_api(aioclient_mock, address=address_with_letter("A"))
    client = RadAfvalApiClient(async_get_clientsession(hass), "1234 ab", " 12 ", " a ")

    assert await client.async_get_address_id() == ADDRESS_ID
    assert api_payloads(aioclient_mock, FETCH_ADDRESS_URL)[0] == {
        "companyCode": COMPANY_CODE,
        "postCode": "1234AB",
        "houseNumber": 12,
        "houseLetter": "A",
        "houseNumberAddition": "",
    }


async def test_calendar_without_data_list(
    aioclient_mock: AiohttpClientMocker, client: RadAfvalApiClient
) -> None:
    """A successful calendar response without a dataList means no dates."""
    mock_api(aioclient_mock, calendar={"status": True, "dataList": None})
    assert await client.async_get_pickup_dates(TODAY) == {}


ERROR_RESPONSES = [
    pytest.param({"status": HTTPStatus.INTERNAL_SERVER_ERROR}, id="http_500"),
    pytest.param(
        {"json": {"status": False, "dataList": None, "messageCode": 2}},
        id="status_false",
    ),
    pytest.param({"json": {"dataList": []}}, id="status_missing"),
    pytest.param({"text": "<html>Service Unavailable</html>"}, id="not_json"),
    pytest.param({"json": [{"status": True}]}, id="json_not_object"),
    pytest.param({"exc": aiohttp.ClientConnectionError("boom")}, id="client_error"),
]


@pytest.mark.parametrize("response", ERROR_RESPONSES)
@pytest.mark.parametrize("endpoint", ["FetchAdress", "GetCalendar"])
async def test_api_errors(
    aioclient_mock: AiohttpClientMocker,
    client: RadAfvalApiClient,
    endpoint: str,
    response: dict[str, Any],
) -> None:
    """Every kind of failure becomes a RadAfvalError (not 'address not found')."""
    if endpoint == "FetchAdress":
        mock_api(aioclient_mock, address_kwargs=response)
    else:
        mock_api(aioclient_mock, calendar_kwargs=response)

    with pytest.raises(RadAfvalError, match=endpoint) as exc_info:
        await client.async_get_pickup_dates(TODAY)
    assert not isinstance(exc_info.value, RadAfvalAddressNotFoundError)


async def test_status_false_reports_message_code(
    aioclient_mock: AiohttpClientMocker, client: RadAfvalApiClient
) -> None:
    """The Ximmio messageCode ends up in the error message."""
    mock_api(
        aioclient_mock,
        address={"status": False, "dataList": None, "messageCode": 2},
    )
    with pytest.raises(RadAfvalError, match=r"messageCode 2"):
        await client.async_get_address_id()


@pytest.mark.parametrize("endpoint", ["FetchAdress", "GetCalendar"])
async def test_timeout(
    aioclient_mock: AiohttpClientMocker, client: RadAfvalApiClient, endpoint: str
) -> None:
    """A request that does not finish within REQUEST_TIMEOUT fails cleanly."""

    async def hang(*_args: Any) -> None:
        await asyncio.Event().wait()

    if endpoint == "FetchAdress":
        mock_api(aioclient_mock, address_kwargs={"side_effect": hang})
    else:
        mock_api(aioclient_mock, calendar_kwargs={"side_effect": hang})

    with (
        patch("custom_components.rad_hw_afval.api.REQUEST_TIMEOUT", 0),
        pytest.raises(RadAfvalError, match=f"Timeout calling {endpoint}"),
    ):
        await client.async_get_pickup_dates(TODAY)


@pytest.mark.parametrize(
    "body",
    [
        pytest.param({"status": True, "dataList": []}, id="empty_list"),
        pytest.param({"status": True, "dataList": None}, id="null_list"),
        pytest.param({"status": True, "dataList": [None, "x"]}, id="no_objects"),
    ],
)
async def test_address_not_found(
    aioclient_mock: AiohttpClientMocker,
    client: RadAfvalApiClient,
    body: dict[str, Any],
) -> None:
    """An empty FetchAdress result means the address is unknown."""
    mock_api(aioclient_mock, address=body)
    with pytest.raises(RadAfvalAddressNotFoundError):
        await client.async_get_address_id()
    assert not api_payloads(aioclient_mock, GET_CALENDAR_URL)


async def test_address_without_unique_id(
    aioclient_mock: AiohttpClientMocker, client: RadAfvalApiClient
) -> None:
    """A match without UniqueId is an API error, not an unknown address."""
    mock_api(aioclient_mock, address={"status": True, "dataList": [{"Street": "X"}]})
    with pytest.raises(RadAfvalError, match="no UniqueId") as exc_info:
        await client.async_get_address_id()
    assert not isinstance(exc_info.value, RadAfvalAddressNotFoundError)


CANDIDATES = [
    {"UniqueId": "100", "HouseLetter": "A"},
    {"UniqueId": "101", "HouseLetter": None},
    {"UniqueId": "102", "HouseLetter": "b"},
]


@pytest.mark.parametrize(
    ("letter", "candidates", "expected"),
    [
        pytest.param("", CANDIDATES, "101", id="no_letter_exact"),
        pytest.param("a", CANDIDATES, "100", id="letter_exact"),
        pytest.param("B", CANDIDATES, "102", id="letter_case_insensitive"),
        pytest.param("", CANDIDATES[:1], "100", id="no_letter_fallback_first"),
        pytest.param("", [None, {"UniqueId": 103}], "103", id="skips_non_objects"),
    ],
)
async def test_address_letter_selection(
    hass: HomeAssistant,
    aioclient_mock: AiohttpClientMocker,
    letter: str,
    candidates: list[Any],
    expected: str,
) -> None:
    """Prefer an exact house letter match, else the first result."""
    mock_api(aioclient_mock, address={"status": True, "dataList": candidates})
    client = RadAfvalApiClient(async_get_clientsession(hass), "1234AB", "1", letter)
    assert await client.async_get_address_id() == expected


@pytest.mark.parametrize(
    "candidates",
    [
        pytest.param(CANDIDATES, id="other_letters_only"),
        pytest.param([], id="empty"),
    ],
)
async def test_address_letter_without_match_not_found(
    hass: HomeAssistant,
    aioclient_mock: AiohttpClientMocker,
    candidates: list[Any],
) -> None:
    """A given house letter never silently resolves to another address."""
    mock_api(aioclient_mock, address={"status": True, "dataList": candidates})
    client = RadAfvalApiClient(async_get_clientsession(hass), "1234AB", "1", "C")
    with pytest.raises(RadAfvalAddressNotFoundError, match="1234AB 1C not found"):
        await client.async_get_address_id()


async def test_address_id_cached(
    aioclient_mock: AiohttpClientMocker, client: RadAfvalApiClient
) -> None:
    """FetchAdress is called once; later calls reuse the address ID."""
    mock_api(aioclient_mock)

    await client.async_get_pickup_dates(TODAY)
    await client.async_get_pickup_dates(TODAY)
    assert await client.async_get_address_id() == ADDRESS_ID

    assert len(api_payloads(aioclient_mock, FETCH_ADDRESS_URL)) == 1
    assert len(api_payloads(aioclient_mock, GET_CALENDAR_URL)) == 2


async def test_address_id_not_cached_after_lookup_failure(
    aioclient_mock: AiohttpClientMocker, client: RadAfvalApiClient
) -> None:
    """A failed address lookup is retried on the next call."""
    mock_api(aioclient_mock, address_kwargs={"status": HTTPStatus.BAD_GATEWAY})
    with pytest.raises(RadAfvalError):
        await client.async_get_pickup_dates(TODAY)

    aioclient_mock.clear_requests()
    mock_api(aioclient_mock)
    assert await client.async_get_pickup_dates(TODAY)
    assert len(api_payloads(aioclient_mock, FETCH_ADDRESS_URL)) == 1


async def test_address_cache_cleared_after_calendar_error(
    aioclient_mock: AiohttpClientMocker, client: RadAfvalApiClient
) -> None:
    """A GetCalendar failure forces a new address lookup next time."""
    mock_api(aioclient_mock)
    await client.async_get_pickup_dates(TODAY)

    aioclient_mock.clear_requests()
    mock_api(aioclient_mock, calendar_kwargs={"status": HTTPStatus.SERVICE_UNAVAILABLE})
    with pytest.raises(RadAfvalError):
        await client.async_get_pickup_dates(TODAY)
    # The failing call still used the cached ID.
    assert not api_payloads(aioclient_mock, FETCH_ADDRESS_URL)
    assert len(api_payloads(aioclient_mock, GET_CALENDAR_URL)) == 1

    aioclient_mock.clear_requests()
    mock_api(aioclient_mock)
    assert await client.async_get_pickup_dates(TODAY)
    assert len(api_payloads(aioclient_mock, FETCH_ADDRESS_URL)) == 1
    assert len(api_payloads(aioclient_mock, GET_CALENDAR_URL)) == 1

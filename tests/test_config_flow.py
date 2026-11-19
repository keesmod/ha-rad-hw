"""Tests for the RAD Hoeksche Waard Afval config and options flows."""

from __future__ import annotations

from http import HTTPStatus
from typing import Any
from unittest.mock import AsyncMock

import aiohttp
import pytest
from homeassistant.config_entries import SOURCE_USER, ConfigEntryState
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType
from pytest_homeassistant_custom_component.common import MockConfigEntry
from pytest_homeassistant_custom_component.test_util.aiohttp import (
    AiohttpClientMocker,
)

from custom_components.rad_hw_afval.const import (
    COMPANY_CODE,
    CONF_DATE_FORMAT,
    CONF_HOUSE_LETTER,
    CONF_POSTAL_CODE,
    CONF_STREET_NUMBER,
    DOMAIN,
)

from .conftest import (
    ENTITY_IDS,
    FETCH_ADDRESS_URL,
    GET_CALENDAR_URL,
    address_with_letter,
    api_payloads,
    create_entry,
    mock_api,
)

USER_INPUT = {
    CONF_POSTAL_CODE: "1234AB",
    CONF_STREET_NUMBER: "1",
    CONF_DATE_FORMAT: "%d-%m-%Y",
}


async def _start(hass: HomeAssistant) -> dict[str, Any]:
    """Start a user flow and check that the form is shown."""
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": SOURCE_USER}
    )
    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "user"
    return result


async def _submit(hass: HomeAssistant, **changes: Any) -> dict[str, Any]:
    """Start a user flow and submit USER_INPUT with ``changes`` applied."""
    result = await _start(hass)
    return await hass.config_entries.flow.async_configure(
        result["flow_id"], {**USER_INPUT, **changes}
    )


def _fetch_payload(postal_code: str, number: int, letter: str) -> dict[str, Any]:
    """Return the expected FetchAdress payload."""
    return {
        "companyCode": COMPANY_CODE,
        "postCode": postal_code,
        "houseNumber": number,
        "houseLetter": letter,
        "houseNumberAddition": "",
    }


async def test_form_shown(hass: HomeAssistant) -> None:
    """The user step asks for the address and date format, not waste types."""
    result = await _start(hass)
    assert result["errors"] == {}
    assert set(result["data_schema"].schema) == {
        CONF_POSTAL_CODE,
        CONF_STREET_NUMBER,
        CONF_DATE_FORMAT,
    }


async def test_create_entry(
    hass: HomeAssistant,
    mock_api_ok: AiohttpClientMocker,
    mock_setup_entry: AsyncMock,
) -> None:
    """A valid address creates a current entry (version 1.2) without options."""
    result = await _submit(hass)

    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["title"] == "1234AB 1"
    assert result["data"] == {
        CONF_POSTAL_CODE: "1234AB",
        CONF_STREET_NUMBER: "1",
        CONF_DATE_FORMAT: "%d-%m-%Y",
    }
    assert result["options"] == {}
    entry = result["result"]
    assert entry.unique_id == "1234AB_1"
    assert entry.version == 1
    assert entry.minor_version == 2
    assert entry.options == {}
    assert len(mock_setup_entry.mock_calls) == 1

    assert api_payloads(mock_api_ok, FETCH_ADDRESS_URL) == [
        _fetch_payload("1234AB", 1, "")
    ]
    assert not api_payloads(mock_api_ok, GET_CALENDAR_URL)


async def test_create_entry_defaults(
    hass: HomeAssistant,
    mock_api_ok: AiohttpClientMocker,
    mock_setup_entry: AsyncMock,
) -> None:
    """The date format falls back to its default."""
    result = await _start(hass)
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {CONF_POSTAL_CODE: "1234AB", CONF_STREET_NUMBER: "1"}
    )

    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["data"][CONF_DATE_FORMAT] == "%d-%m-%Y"
    assert result["options"] == {}


@pytest.mark.parametrize("street_number", ["12a", "12A", "12 A", "12-a", " 12 - a "])
async def test_house_letter(
    hass: HomeAssistant,
    aioclient_mock: AiohttpClientMocker,
    mock_setup_entry: AsyncMock,
    street_number: str,
) -> None:
    """A house letter is split off, upper-cased and stored separately."""
    mock_api(aioclient_mock, address=address_with_letter("A"))
    result = await _submit(hass, **{CONF_STREET_NUMBER: street_number})

    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["title"] == "1234AB 12A"
    assert result["result"].unique_id == "1234AB_12A"
    assert result["data"] == {
        CONF_POSTAL_CODE: "1234AB",
        CONF_STREET_NUMBER: "12",
        CONF_DATE_FORMAT: "%d-%m-%Y",
        CONF_HOUSE_LETTER: "A",
    }
    assert api_payloads(aioclient_mock, FETCH_ADDRESS_URL) == [
        _fetch_payload("1234AB", 12, "A")
    ]


@pytest.mark.parametrize(("street_number", "expected"), [("012", "12"), (" 7 ", "7")])
async def test_house_number_normalized(
    hass: HomeAssistant,
    mock_api_ok: AiohttpClientMocker,
    mock_setup_entry: AsyncMock,
    street_number: str,
    expected: str,
) -> None:
    """Leading zeros and spaces are removed from the house number."""
    result = await _submit(hass, **{CONF_STREET_NUMBER: street_number})

    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["title"] == f"1234AB {expected}"
    assert result["result"].unique_id == f"1234AB_{expected}"
    assert result["data"][CONF_STREET_NUMBER] == expected
    assert CONF_HOUSE_LETTER not in result["data"]


@pytest.mark.parametrize("postal_code", ["1234 ab", " 1234ab ", "1234\tAB", "1234AB"])
async def test_postal_code_normalized(
    hass: HomeAssistant,
    mock_api_ok: AiohttpClientMocker,
    mock_setup_entry: AsyncMock,
    postal_code: str,
) -> None:
    """Whitespace is removed and letters are upper-cased."""
    result = await _submit(hass, **{CONF_POSTAL_CODE: postal_code})

    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["result"].unique_id == "1234AB_1"
    assert result["data"][CONF_POSTAL_CODE] == "1234AB"
    assert api_payloads(mock_api_ok, FETCH_ADDRESS_URL)[0]["postCode"] == "1234AB"


@pytest.mark.parametrize(
    "postal_code", ["", "123AB", "12345A", "ABCD12", "1234A", "1234ABC", "1234-AB"]
)
async def test_invalid_postal_code(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker, postal_code: str
) -> None:
    """Postal codes that are not Dutch are rejected before any API call."""
    result = await _submit(hass, **{CONF_POSTAL_CODE: postal_code})

    assert result["type"] is FlowResultType.FORM
    assert result["errors"] == {CONF_POSTAL_CODE: "invalid_postal_code"}
    assert aioclient_mock.call_count == 0


@pytest.mark.parametrize(
    "street_number", ["", "abc", "0", "00", "0a", "12ab", "a12", "12.5", "-1", "1 2"]
)
async def test_invalid_house_number(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker, street_number: str
) -> None:
    """House numbers that are not a positive number plus letter are rejected."""
    result = await _submit(hass, **{CONF_STREET_NUMBER: street_number})

    assert result["type"] is FlowResultType.FORM
    assert result["errors"] == {CONF_STREET_NUMBER: "invalid_street_number"}
    assert aioclient_mock.call_count == 0


async def test_multiple_errors(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker
) -> None:
    """All field errors are reported together."""
    result = await _submit(hass, **{CONF_POSTAL_CODE: "x", CONF_STREET_NUMBER: "y"})

    assert result["errors"] == {
        CONF_POSTAL_CODE: "invalid_postal_code",
        CONF_STREET_NUMBER: "invalid_street_number",
    }
    assert aioclient_mock.call_count == 0


async def test_address_not_found_then_recover(
    hass: HomeAssistant,
    aioclient_mock: AiohttpClientMocker,
    mock_setup_entry: AsyncMock,
) -> None:
    """An unknown address shows an error; a corrected one is accepted."""
    mock_api(aioclient_mock, address={"status": True, "dataList": []})
    result = await _start(hass)
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], USER_INPUT
    )

    assert result["type"] is FlowResultType.FORM
    assert result["errors"] == {"base": "address_not_found"}

    aioclient_mock.clear_requests()
    mock_api(aioclient_mock)
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {**USER_INPUT, CONF_STREET_NUMBER: "3"}
    )

    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["result"].unique_id == "1234AB_3"
    assert len(mock_setup_entry.mock_calls) == 1


@pytest.mark.parametrize(
    "response",
    [
        pytest.param({"status": HTTPStatus.INTERNAL_SERVER_ERROR}, id="http_500"),
        pytest.param(
            {"json": {"status": False, "dataList": None, "messageCode": 2}},
            id="status_false",
        ),
        pytest.param({"text": "<html>maintenance</html>"}, id="not_json"),
        pytest.param({"exc": aiohttp.ClientConnectionError()}, id="client_error"),
        pytest.param({"exc": TimeoutError()}, id="timeout"),
    ],
)
async def test_cannot_connect(
    hass: HomeAssistant,
    aioclient_mock: AiohttpClientMocker,
    response: dict[str, Any],
) -> None:
    """API failures show cannot_connect."""
    mock_api(aioclient_mock, address_kwargs=response)
    result = await _submit(hass)

    assert result["type"] is FlowResultType.FORM
    assert result["errors"] == {"base": "cannot_connect"}


@pytest.mark.parametrize(
    ("postal_code", "street_number"),
    [("1234AB", "1"), ("1234 ab", "01")],
)
async def test_already_configured(
    hass: HomeAssistant,
    aioclient_mock: AiohttpClientMocker,
    postal_code: str,
    street_number: str,
) -> None:
    """The same address cannot be added twice."""
    create_entry().add_to_hass(hass)

    result = await _submit(
        hass, **{CONF_POSTAL_CODE: postal_code, CONF_STREET_NUMBER: street_number}
    )

    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "already_configured"
    assert aioclient_mock.call_count == 0


async def test_options_flow(
    hass: HomeAssistant,
    init_integration: MockConfigEntry,
    aioclient_mock: AiohttpClientMocker,
) -> None:
    """The options flow only changes the date format and reloads the entry."""
    entry = init_integration
    calls = aioclient_mock.call_count

    result = await hass.config_entries.options.async_init(entry.entry_id)
    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "init"
    assert not result["errors"]
    assert set(result["data_schema"].schema) == {CONF_DATE_FORMAT}

    result = await hass.config_entries.options.async_configure(
        result["flow_id"], {CONF_DATE_FORMAT: "%Y-%m-%d"}
    )
    await hass.async_block_till_done()

    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert entry.options == {CONF_DATE_FORMAT: "%Y-%m-%d"}
    assert entry.state is ConfigEntryState.LOADED
    # The reload created a new client, which looked up the address again.
    assert aioclient_mock.call_count == calls + 2

    rest = hass.states.get(ENTITY_IDS["rest"])
    assert rest.state == "2026-12-04"
    assert rest.attributes["formatted_date"] == "2026-12-04"
    # Every waste type keeps its sensor.
    for waste_type, entity_id in ENTITY_IDS.items():
        state = hass.states.get(entity_id)
        assert state is not None, entity_id
        assert state.attributes["waste_type"] == waste_type


@pytest.mark.parametrize(
    ("data_format", "options", "expected"),
    [
        pytest.param("%d/%m/%Y", {CONF_DATE_FORMAT: "%Y"}, "%Y", id="from_options"),
        pytest.param("%d/%m/%Y", {}, "%d/%m/%Y", id="from_data"),
        pytest.param(None, {}, "%d-%m-%Y", id="default"),
    ],
)
async def test_options_flow_defaults(
    hass: HomeAssistant,
    data_format: str | None,
    options: dict[str, Any],
    expected: str,
) -> None:
    """The form suggests the current options, then the entry data."""
    data = {CONF_POSTAL_CODE: "1234AB", CONF_STREET_NUMBER: "1"}
    if data_format is not None:
        data[CONF_DATE_FORMAT] = data_format
    entry = create_entry(data=data, options=options)
    entry.add_to_hass(hass)

    result = await hass.config_entries.options.async_init(entry.entry_id)

    schema = result["data_schema"].schema
    assert {str(key): key.description["suggested_value"] for key in schema} == {
        CONF_DATE_FORMAT: expected
    }
    # The default is the built-in format, so clearing the field resets it.
    assert {str(key): key.default() for key in schema} == {CONF_DATE_FORMAT: "%d-%m-%Y"}


async def test_options_flow_cleared_field_resets_default(
    hass: HomeAssistant, mock_setup_entry: AsyncMock
) -> None:
    """Submitting the form without a value stores the default format."""
    entry = create_entry(options={CONF_DATE_FORMAT: "%Y"})
    entry.add_to_hass(hass)

    result = await hass.config_entries.options.async_init(entry.entry_id)
    result = await hass.config_entries.options.async_configure(result["flow_id"], {})

    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert entry.options == {CONF_DATE_FORMAT: "%d-%m-%Y"}

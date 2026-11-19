"""Config flow for RAD Hoeksche Waard Afval."""

from __future__ import annotations

import re
from typing import Any

import homeassistant.helpers.config_validation as cv
import voluptuous as vol
from homeassistant.config_entries import (
    ConfigEntry,
    ConfigFlow,
    ConfigFlowResult,
    OptionsFlow,
)
from homeassistant.core import callback
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .api import RadAfvalAddressNotFoundError, RadAfvalApiClient, RadAfvalError
from .const import (
    CONF_DATE_FORMAT,
    CONF_HOUSE_LETTER,
    CONF_POSTAL_CODE,
    CONF_RESOURCES,
    CONF_STREET_NUMBER,
    DEFAULT_DATE_FORMAT,
    DOMAIN,
    SENSOR_TYPES,
)

POSTAL_CODE_RE = re.compile(r"[0-9]{4}[A-Z]{2}")
# "12", "12a", "12 A" and "12-a" are accepted; the letter is optional.
HOUSE_NUMBER_RE = re.compile(r"([0-9]+)\s*-?\s*([A-Z]?)")

USER_SCHEMA = vol.Schema(
    {
        vol.Required(CONF_POSTAL_CODE): str,
        vol.Required(CONF_STREET_NUMBER): str,
        vol.Optional(CONF_DATE_FORMAT, default=DEFAULT_DATE_FORMAT): str,
        vol.Required(CONF_RESOURCES, default=list(SENSOR_TYPES)): cv.multi_select(
            SENSOR_TYPES
        ),
    }
)


def _parse_house_number(value: str) -> tuple[str, str] | None:
    """Split a house number like "12a" into ("12", "A")."""
    match = HOUSE_NUMBER_RE.fullmatch(value.strip().upper())
    if match is None or int(match[1]) == 0:
        return None
    return str(int(match[1])), match[2]


class RadAfvalConfigFlow(ConfigFlow, domain=DOMAIN):
    """Handle a config flow for RAD Hoeksche Waard Afval."""

    VERSION = 1

    @staticmethod
    @callback
    def async_get_options_flow(config_entry: ConfigEntry) -> RadAfvalOptionsFlow:
        """Get the options flow for this handler."""
        return RadAfvalOptionsFlow()

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Ask for the address and check it against the API."""
        errors: dict[str, str] = {}

        if user_input is not None:
            postal_code = re.sub(r"\s+", "", str(user_input[CONF_POSTAL_CODE]).upper())
            house = _parse_house_number(str(user_input[CONF_STREET_NUMBER]))

            if not POSTAL_CODE_RE.fullmatch(postal_code):
                errors[CONF_POSTAL_CODE] = "invalid_postal_code"
            if house is None:
                errors[CONF_STREET_NUMBER] = "invalid_street_number"
            if not user_input.get(CONF_RESOURCES):
                errors[CONF_RESOURCES] = "no_waste_types"

            if not errors and house is not None:
                number, letter = house
                await self.async_set_unique_id(f"{postal_code}_{number}{letter}")
                self._abort_if_unique_id_configured()

                client = RadAfvalApiClient(
                    async_get_clientsession(self.hass), postal_code, number, letter
                )
                try:
                    await client.async_get_address_id()
                except RadAfvalAddressNotFoundError:
                    errors["base"] = "address_not_found"
                except RadAfvalError:
                    errors["base"] = "cannot_connect"
                else:
                    data = {
                        CONF_POSTAL_CODE: postal_code,
                        CONF_STREET_NUMBER: number,
                        CONF_DATE_FORMAT: user_input.get(
                            CONF_DATE_FORMAT, DEFAULT_DATE_FORMAT
                        ),
                    }
                    if letter:
                        data[CONF_HOUSE_LETTER] = letter
                    return self.async_create_entry(
                        title=f"{postal_code} {number}{letter}",
                        data=data,
                        options={CONF_RESOURCES: user_input[CONF_RESOURCES]},
                    )

        return self.async_show_form(
            step_id="user",
            data_schema=self.add_suggested_values_to_schema(USER_SCHEMA, user_input),
            errors=errors,
        )


class RadAfvalOptionsFlow(OptionsFlow):
    """Change the waste types and date format."""

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Manage the options."""
        errors: dict[str, str] = {}
        if user_input is not None:
            if user_input.get(CONF_RESOURCES):
                return self.async_create_entry(data=user_input)
            errors[CONF_RESOURCES] = "no_waste_types"

        entry = self.config_entry
        schema = vol.Schema(
            {
                vol.Required(
                    CONF_RESOURCES,
                    default=entry.options.get(CONF_RESOURCES, list(SENSOR_TYPES)),
                ): cv.multi_select(SENSOR_TYPES),
                vol.Optional(
                    CONF_DATE_FORMAT,
                    default=entry.options.get(
                        CONF_DATE_FORMAT,
                        entry.data.get(CONF_DATE_FORMAT, DEFAULT_DATE_FORMAT),
                    ),
                ): str,
            }
        )
        return self.async_show_form(step_id="init", data_schema=schema, errors=errors)

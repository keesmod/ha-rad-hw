"""Config flow for RAD Hoeksche Waard Afval integration."""

import logging
import re
from typing import Any, Dict, Optional

import voluptuous as vol

from homeassistant import config_entries
from homeassistant.core import callback
from homeassistant.data_entry_flow import FlowResult
import homeassistant.helpers.config_validation as cv

from .const import (
    CONF_DATE_FORMAT,
    CONF_POSTAL_CODE,
    CONF_RESOURCES,
    CONF_STREET_NUMBER,
    DEFAULT_DATE_FORMAT,
    DOMAIN,
    SENSOR_TYPES,
    WASTE_TYPE_GFT,
    WASTE_TYPE_PAPIER,
    WASTE_TYPE_PMD,
    WASTE_TYPE_REST,
)

_LOGGER = logging.getLogger(__name__)

RESOURCE_SCHEMA = vol.Schema(
    {vol.Required(CONF_RESOURCES): cv.multi_select(SENSOR_TYPES)}
)


class RadAfvalConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Handle a config flow for RAD Hoeksche Waard Afval."""

    VERSION = 1

    @staticmethod
    @callback
    def async_get_options_flow(
        config_entry: config_entries.ConfigEntry,
    ) -> config_entries.OptionsFlow:
        """Get the options flow for this handler."""
        return RadAfvalOptionsFlowHandler(config_entry)

    async def async_step_user(
        self, user_input: Optional[Dict[str, Any]] = None
    ) -> FlowResult:
        """Handle the initial step."""
        errors: Dict[str, str] = {}

        if user_input is not None:
            postal_code = user_input[CONF_POSTAL_CODE]
            street_number = user_input[CONF_STREET_NUMBER]

            # Validate postal code format (Dutch format)
            if not re.match(r"^\d{4}[A-Z]{2}$", postal_code):
                errors[CONF_POSTAL_CODE] = "invalid_postal_code"

            # Validate street number
            if not str(street_number).isdigit():
                errors[CONF_STREET_NUMBER] = "invalid_street_number"

            if not errors:
                # Create a unique ID based on postal code and street number
                await self.async_set_unique_id(f"{postal_code}_{street_number}")
                self._abort_if_unique_id_configured()

                return self.async_create_entry(
                    title=f"{postal_code} {street_number}",
                    data={
                        CONF_POSTAL_CODE: postal_code,
                        CONF_STREET_NUMBER: street_number,
                        CONF_DATE_FORMAT: user_input.get(
                            CONF_DATE_FORMAT, DEFAULT_DATE_FORMAT
                        ),
                    },
                    options={
                        CONF_RESOURCES: user_input.get(
                            CONF_RESOURCES,
                            [
                                WASTE_TYPE_REST,
                                WASTE_TYPE_GFT,
                                WASTE_TYPE_PAPIER,
                                WASTE_TYPE_PMD,
                            ],
                        ),
                    },
                )

        resource_defaults = [
            WASTE_TYPE_REST,
            WASTE_TYPE_GFT,
            WASTE_TYPE_PAPIER,
            WASTE_TYPE_PMD,
        ]
        return self.async_show_form(
            step_id="user",
            data_schema=vol.Schema(
                {
                    vol.Required(CONF_POSTAL_CODE): str,
                    vol.Required(CONF_STREET_NUMBER): str,
                    vol.Optional(CONF_DATE_FORMAT, default=DEFAULT_DATE_FORMAT): str,
                    vol.Required(
                        CONF_RESOURCES, default=resource_defaults
                    ): cv.multi_select(SENSOR_TYPES),
                }
            ),
            errors=errors,
        )


class RadAfvalOptionsFlowHandler(config_entries.OptionsFlow):
    """Handle a option flow for RAD Hoeksche Waard Afval."""

    def __init__(self, config_entry: config_entries.ConfigEntry) -> None:
        """Initialize options flow."""
        self._config_entry = config_entry  # Store as a private attribute instead

    async def async_step_init(
        self, user_input: Optional[Dict[str, Any]] = None
    ) -> FlowResult:
        """Handle options flow."""
        if user_input is not None:
            return self.async_create_entry(title="", data=user_input)

        resources_default = self._config_entry.options.get(
            CONF_RESOURCES,
            [WASTE_TYPE_REST, WASTE_TYPE_GFT, WASTE_TYPE_PAPIER, WASTE_TYPE_PMD],
        )

        date_format_default = self._config_entry.data.get(
            CONF_DATE_FORMAT, DEFAULT_DATE_FORMAT
        )

        return self.async_show_form(
            step_id="init",
            data_schema=vol.Schema(
                {
                    vol.Required(
                        CONF_RESOURCES, default=resources_default
                    ): cv.multi_select(SENSOR_TYPES),
                    vol.Optional(CONF_DATE_FORMAT, default=date_format_default): str,
                }
            ),
        )

"""Data update coordinator for the RAD Hoeksche Waard Afval integration."""

import logging
from typing import Any, Dict

import async_timeout

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .api import RadAfvalApiClient
from .const import DOMAIN, SCAN_INTERVAL

_LOGGER = logging.getLogger(__name__)


class RadAfvalDataUpdateCoordinator(DataUpdateCoordinator):
    """Class to manage fetching RAD Hoeksche Waard Afval data."""

    def __init__(self, hass: HomeAssistant, config_entry: ConfigEntry) -> None:
        """Initialize the data update coordinator."""
        self.config_entry = config_entry
        postal_code = config_entry.data["postal_code"]
        street_number = config_entry.data["street_number"]

        self.api_client = RadAfvalApiClient(
            async_get_clientsession(hass),
            postal_code,
            street_number,
        )

        _LOGGER.debug(
            "Initializing RAD HW Afval coordinator for %s %s",
            postal_code,
            street_number,
        )

        super().__init__(
            hass,
            _LOGGER,
            name=f"{DOMAIN}_{config_entry.unique_id}",
            update_interval=SCAN_INTERVAL,
        )

    async def _async_update_data(self) -> Dict[str, Any]:
        """Fetch data from the RAD Hoeksche Waard Afval API."""
        postal_code = self.config_entry.data["postal_code"]
        street_number = self.config_entry.data["street_number"]

        try:
            _LOGGER.debug(
                "Updating RAD HW Afval data for %s %s", postal_code, street_number
            )

            async with async_timeout.timeout(30):
                data = await self.api_client.async_get_data()

                if data is None:
                    error_msg = (
                        f"Failed to fetch data for {postal_code} {street_number}"
                    )
                    _LOGGER.error(error_msg)
                    raise UpdateFailed(error_msg)

                if not data:
                    _LOGGER.warning(
                        "API returned successfully but no waste data was found for %s %s. "
                        "Check if the postal code and street number are correct.",
                        postal_code,
                        street_number,
                    )

                _LOGGER.debug(
                    "Successfully updated RAD HW Afval data with %d entries", len(data)
                )
                return data

        except async_timeout.TimeoutError as err:
            error_msg = (
                f"Timeout fetching data for {postal_code} {street_number}: {err}"
            )
            _LOGGER.error(error_msg)
            raise UpdateFailed(error_msg) from err
        except Exception as err:
            error_msg = f"Error fetching data for {postal_code} {street_number}: {err}"
            _LOGGER.exception(error_msg)
            raise UpdateFailed(error_msg) from err

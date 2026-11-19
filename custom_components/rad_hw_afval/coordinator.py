"""Data update coordinator for the RAD Hoeksche Waard Afval integration."""

from __future__ import annotations

import logging
from datetime import date

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed
from homeassistant.util import dt as dt_util

from .api import RadAfvalApiClient, RadAfvalError
from .const import (
    CONF_HOUSE_LETTER,
    CONF_POSTAL_CODE,
    CONF_STREET_NUMBER,
    DOMAIN,
    RETRY_INTERVAL,
    SCAN_INTERVAL,
)

_LOGGER = logging.getLogger(__name__)

type RadAfvalConfigEntry = ConfigEntry[RadAfvalDataUpdateCoordinator]


class RadAfvalDataUpdateCoordinator(DataUpdateCoordinator[dict[str, list[date]]]):
    """Fetch the pickup calendar for one address.

    The data holds all known pickup dates per waste type; the sensors pick the
    next date themselves so their state stays correct between refreshes.
    """

    config_entry: RadAfvalConfigEntry

    def __init__(self, hass: HomeAssistant, entry: RadAfvalConfigEntry) -> None:
        """Initialize the coordinator."""
        super().__init__(
            hass,
            _LOGGER,
            config_entry=entry,
            name=f"{DOMAIN}_{entry.unique_id}",
            update_interval=SCAN_INTERVAL,
            always_update=False,
        )
        self.api = RadAfvalApiClient(
            async_get_clientsession(hass),
            str(entry.data[CONF_POSTAL_CODE]),
            str(entry.data[CONF_STREET_NUMBER]),
            str(entry.data.get(CONF_HOUSE_LETTER, "")),
        )

    async def _async_update_data(self) -> dict[str, list[date]]:
        """Fetch pickup dates from the API."""
        try:
            data = await self.api.async_get_pickup_dates(dt_util.now().date())
        except RadAfvalError as err:
            self.update_interval = RETRY_INTERVAL
            raise UpdateFailed(str(err)) from err

        self.update_interval = SCAN_INTERVAL
        if not data:
            _LOGGER.warning(
                "No pickup dates found for %s; check the address",
                self.config_entry.title,
            )
        return data

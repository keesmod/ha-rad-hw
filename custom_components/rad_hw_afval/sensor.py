"""Sensor platform for RAD Hoeksche Waard Afval."""

from __future__ import annotations

from datetime import date, datetime
from typing import Any, Final

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorEntityDescription,
)
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.device_registry import DeviceEntryType, DeviceInfo
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback
from homeassistant.helpers.event import async_track_time_change
from homeassistant.helpers.update_coordinator import CoordinatorEntity
from homeassistant.loader import async_get_integration
from homeassistant.util import dt as dt_util

from .api import next_pickup
from .const import (
    CONF_DATE_FORMAT,
    DEFAULT_DATE_FORMAT,
    DOMAIN,
    SENSOR_TYPES,
    WASTE_TYPE_GFT,
    WASTE_TYPE_PAPIER,
    WASTE_TYPE_PMD,
    WASTE_TYPE_REST,
)
from .coordinator import RadAfvalConfigEntry, RadAfvalDataUpdateCoordinator

# All entities share one coordinator and never poll themselves.
PARALLEL_UPDATES = 0

WASTE_TYPE_ICONS: Final = {
    WASTE_TYPE_REST: "mdi:trash-can",
    WASTE_TYPE_GFT: "mdi:leaf",
    WASTE_TYPE_PAPIER: "mdi:newspaper",
    WASTE_TYPE_PMD: "mdi:recycle",
}

SENSOR_DESCRIPTIONS: Final = {
    waste_type: SensorEntityDescription(
        key=waste_type,
        name=name,
        icon=WASTE_TYPE_ICONS[waste_type],
        device_class=SensorDeviceClass.DATE,
    )
    for waste_type, name in SENSOR_TYPES.items()
}


async def async_setup_entry(
    hass: HomeAssistant,
    entry: RadAfvalConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up one sensor per waste type."""
    coordinator = entry.runtime_data
    # An empty stored format falls back to the default, as in 1.2.x.
    date_format = (
        entry.options.get(CONF_DATE_FORMAT, entry.data.get(CONF_DATE_FORMAT))
        or DEFAULT_DATE_FORMAT
    )
    integration = await async_get_integration(hass, DOMAIN)
    device_info = DeviceInfo(
        identifiers={(DOMAIN, str(entry.unique_id))},
        name=f"RAD HW Afval {entry.title}",
        manufacturer="RAD Hoeksche Waard",
        model="Afvalkalender",
        sw_version=str(integration.version),
        entry_type=DeviceEntryType.SERVICE,
    )

    async_add_entities(
        RadAfvalSensor(coordinator, description, device_info, date_format)
        for description in SENSOR_DESCRIPTIONS.values()
    )


class RadAfvalSensor(CoordinatorEntity[RadAfvalDataUpdateCoordinator], SensorEntity):
    """Next pickup date for one waste type."""

    _attr_has_entity_name = True

    def __init__(
        self,
        coordinator: RadAfvalDataUpdateCoordinator,
        description: SensorEntityDescription,
        device_info: DeviceInfo,
        date_format: str,
    ) -> None:
        """Initialize the sensor."""
        super().__init__(coordinator)
        self.entity_description = description
        self._date_format = date_format
        self._attr_unique_id = f"{coordinator.config_entry.unique_id}_{description.key}"
        self._attr_device_info = device_info

    async def async_added_to_hass(self) -> None:
        """Re-evaluate the state just after local midnight."""
        await super().async_added_to_hass()
        self.async_on_remove(
            async_track_time_change(
                self.hass, self._async_midnight, hour=0, minute=0, second=1
            )
        )

    @callback
    def _async_midnight(self, _now: datetime) -> None:
        """Move to the next pickup date when the day changes."""
        self.async_write_ha_state()

    @property
    def _dates(self) -> list[date]:
        """Return all known pickup dates for this waste type."""
        return (self.coordinator.data or {}).get(self.entity_description.key, [])

    @property
    def available(self) -> bool:
        """Return True if the last refresh worked and this type has dates."""
        return super().available and bool(self._dates)

    @property
    def native_value(self) -> date | None:
        """Return the next pickup date."""
        return next_pickup(self._dates, dt_util.now().date())

    @property
    def extra_state_attributes(self) -> dict[str, Any] | None:
        """Return days until pickup and the formatted date."""
        today = dt_util.now().date()
        pickup = next_pickup(self._dates, today)
        if pickup is None:
            return None

        days_until = (pickup - today).days
        attributes: dict[str, Any] = {
            "next_pickup_in_days": days_until,
            "waste_type": self.entity_description.key,
            "is_past_date": days_until < 0,
        }
        attributes["formatted_date"] = pickup.strftime(self._date_format)
        return attributes

"""Sensor platform for RAD Hoeksche Waard Afval."""

import logging
from typing import Any, Final, Optional

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorEntityDescription,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.typing import StateType
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import (
    CONF_DATE_FORMAT,
    CONF_RESOURCES,
    DEFAULT_DATE_FORMAT,
    DOMAIN,
    SENSOR_TYPES,
    WASTE_TYPE_GFT,
    WASTE_TYPE_PAPIER,
    WASTE_TYPE_PMD,
    WASTE_TYPE_REST,
)
from .coordinator import RadAfvalDataUpdateCoordinator

_LOGGER = logging.getLogger(__name__)


WASTE_TYPE_TO_ICON = {
    WASTE_TYPE_REST: "mdi:trash-can",
    WASTE_TYPE_GFT: "mdi:leaf",
    WASTE_TYPE_PAPIER: "mdi:newspaper",
    WASTE_TYPE_PMD: "mdi:recycle",
}


# Create sensor descriptions
SENSOR_DESCRIPTIONS: Final = {
    waste_type: SensorEntityDescription(
        key=waste_type,
        name=SENSOR_TYPES[waste_type],
        icon=WASTE_TYPE_TO_ICON.get(waste_type, "mdi:trash-can"),
        device_class=SensorDeviceClass.DATE,
        entity_category=None,
    )
    for waste_type, friendly_name in SENSOR_TYPES.items()
}


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up the RAD Hoeksche Waard Afval sensor platform."""
    coordinator = hass.data[DOMAIN][entry.entry_id]
    waste_types = entry.options.get(CONF_RESOURCES, list(SENSOR_TYPES.keys()))
    date_format = entry.options.get(
        CONF_DATE_FORMAT, entry.data.get(CONF_DATE_FORMAT, DEFAULT_DATE_FORMAT)
    )

    _LOGGER.debug(
        "Setting up RAD HW Afval sensors for %s with waste types: %s",
        entry.title,
        waste_types,
    )

    entities = []

    # Create sensor entities for each waste type
    for waste_type in waste_types:
        if waste_type in SENSOR_DESCRIPTIONS:
            _LOGGER.debug("Creating sensor for waste type: %s", waste_type)
            entities.append(
                RadAfvalSensor(
                    coordinator=coordinator,
                    description=SENSOR_DESCRIPTIONS[waste_type],
                    waste_type=waste_type,
                    date_format=date_format,
                )
            )
        else:
            _LOGGER.warning("Unknown waste type: %s", waste_type)

    if entities:
        _LOGGER.debug("Adding %d RAD HW Afval sensor entities", len(entities))
        async_add_entities(entities)
    else:
        _LOGGER.error("No RAD HW Afval sensors were created!")


class RadAfvalSensor(CoordinatorEntity, SensorEntity):
    """Implementation of a RAD Hoeksche Waard Afval sensor."""

    def __init__(
        self,
        coordinator: RadAfvalDataUpdateCoordinator,
        description: SensorEntityDescription,
        waste_type: str,
        date_format: Optional[str] = None,
    ) -> None:
        """Initialize the sensor."""
        super().__init__(coordinator)
        self.entity_description = description
        self.waste_type = waste_type
        self.date_format = date_format or DEFAULT_DATE_FORMAT

        # Set unique_id using the entry's unique_id and the waste type
        self._attr_unique_id = f"{coordinator.config_entry.unique_id}_{waste_type}"

        # Set the name
        self._attr_name = f"RAD HW Afval {SENSOR_TYPES[waste_type]}"

        # Set device info
        self._attr_device_info = {
            "identifiers": {(DOMAIN, coordinator.config_entry.unique_id)},
            "name": f"RAD HW Afval {coordinator.config_entry.title}",
            "manufacturer": "RAD Hoeksche Waard",
            "model": "Afvalkalender",
            "sw_version": "1.2.1",
        }

        _LOGGER.debug(
            "Initialized sensor %s with unique_id %s",
            self._attr_name,
            self._attr_unique_id,
        )

    @property
    def available(self) -> bool:
        """Return True if entity is available."""
        if not self.coordinator.last_update_success:
            return False

        # Check if the waste type is in the data
        has_data = (
            self.coordinator.data is not None
            and self.waste_type in self.coordinator.data
        )

        if not has_data and _LOGGER.isEnabledFor(logging.DEBUG):
            _LOGGER.debug(
                "Sensor %s is unavailable because no data is available for waste type %s",
                self._attr_name,
                self.waste_type,
            )

        return has_data

    @property
    def native_value(self) -> StateType:
        """Return the state of the sensor."""
        if not self.available:
            return None

        waste_data = self.coordinator.data[self.waste_type]
        next_date = waste_data.get("next_date")

        # For date device class, we must return a date object directly
        # The formatted date should go in the extra state attributes
        if next_date:
            return next_date  # Return the actual date object, not a string

        return None

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return the state attributes."""
        if not self.available:
            return {}

        waste_data = self.coordinator.data[self.waste_type]
        attributes = {
            "next_pickup_in_days": waste_data.get("days_until"),
            "waste_type": self.waste_type,
        }

        # Add formatted date as an attribute
        next_date = waste_data.get("next_date")
        if next_date:
            # Add indicator if this is a past date
            days_until = waste_data.get("days_until", 0)
            attributes["is_past_date"] = days_until < 0

            # Add formatted date
            try:
                attributes["formatted_date"] = next_date.strftime(self.date_format)
            except ValueError as err:
                _LOGGER.error(
                    "Error formatting date %s with format %s: %s",
                    next_date.isoformat(),
                    self.date_format,
                    err,
                )

        return attributes

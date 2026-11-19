"""The RAD Hoeksche Waard Afval integration."""

from __future__ import annotations

from homeassistant.const import Platform
from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er

from .const import CONF_RESOURCES, DOMAIN, SENSOR_TYPES
from .coordinator import RadAfvalConfigEntry, RadAfvalDataUpdateCoordinator

PLATFORMS = [Platform.SENSOR]


async def async_setup_entry(hass: HomeAssistant, entry: RadAfvalConfigEntry) -> bool:
    """Set up RAD Hoeksche Waard Afval from a config entry."""
    coordinator = RadAfvalDataUpdateCoordinator(hass, entry)
    await coordinator.async_config_entry_first_refresh()
    entry.runtime_data = coordinator

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    entry.async_on_unload(entry.add_update_listener(_async_update_listener))
    return True


async def async_unload_entry(hass: HomeAssistant, entry: RadAfvalConfigEntry) -> bool:
    """Unload a config entry."""
    return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)


async def async_migrate_entry(hass: HomeAssistant, entry: RadAfvalConfigEntry) -> bool:
    """Migrate config entries from older versions."""
    if entry.version > 1:
        # Downgrade from a future major version.
        return False

    if entry.minor_version < 2:
        # Config entry 1.1 (integration 1.2.x and older) stored the selected
        # waste types in the options. From config entry 1.2 (integration 1.3.0)
        # every waste type has a sensor and users disable the ones they don't
        # want, so register earlier deselected types as disabled sensors. This
        # also covers sensors that were never created or that the user deleted.
        options = dict(entry.options)
        selected = options.pop(CONF_RESOURCES, None)
        if selected is not None:
            registry = er.async_get(hass)
            for key, name in SENSOR_TYPES.items():
                if key in selected:
                    continue
                reg_entry = registry.async_get_or_create(
                    Platform.SENSOR,
                    DOMAIN,
                    f"{entry.unique_id}_{key}",
                    config_entry=entry,
                    suggested_object_id=f"RAD HW Afval {entry.title} {name}",
                    disabled_by=er.RegistryEntryDisabler.USER,
                )
                if reg_entry.disabled_by is None:
                    registry.async_update_entity(
                        reg_entry.entity_id,
                        disabled_by=er.RegistryEntryDisabler.USER,
                    )
        hass.config_entries.async_update_entry(entry, options=options, minor_version=2)

    return True


async def _async_update_listener(
    hass: HomeAssistant, entry: RadAfvalConfigEntry
) -> None:
    """Reload the entry when its options change."""
    await hass.config_entries.async_reload(entry.entry_id)

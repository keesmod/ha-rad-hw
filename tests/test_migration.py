"""Tests for migrating config entries from version 1.1 to version 1.2.

Config entry version 1.1 is what integration 1.2.x and older wrote.

Up to 1.2.x the user picked waste types and only those got a sensor; the
choice was stored as ``options["resources"]``. From 1.3.0 every waste type
has a sensor and the migration turns the old choice into disabled entities.
"""

from __future__ import annotations

from datetime import timedelta
from http import HTTPStatus
from typing import Any

import pytest
from freezegun.api import FrozenDateTimeFactory
from homeassistant.config_entries import ConfigEntryState
from homeassistant.const import STATE_UNAVAILABLE, Platform
from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er
from pytest_homeassistant_custom_component.common import (
    MockConfigEntry,
    async_fire_time_changed,
)
from pytest_homeassistant_custom_component.test_util.aiohttp import (
    AiohttpClientMocker,
)

from custom_components.rad_hw_afval import async_migrate_entry
from custom_components.rad_hw_afval.const import (
    CONF_DATE_FORMAT,
    CONF_RESOURCES,
    DOMAIN,
    SENSOR_TYPES,
)

from .conftest import (
    ALL_WASTE_TYPES,
    ENTITY_IDS,
    ENTRY_DATA,
    UNIQUE_ID,
    V122_ENTITY_IDS,
    create_entry,
    mock_api,
)

USER = er.RegistryEntryDisabler.USER

# What a 1.2.2 options flow stored after deselecting GFT and PMD.
LEGACY_OPTIONS = {CONF_RESOURCES: ["rest", "papier"], CONF_DATE_FORMAT: "%d/%m"}


def _legacy_entry(options: dict[str, Any], **kwargs: Any) -> MockConfigEntry:
    """Return a config entry as written by integration 1.2.x."""
    return create_entry(options=options, **{"minor_version": 1, **kwargs})


def _register_v122(
    entity_registry: er.EntityRegistry,
    entry: MockConfigEntry,
    key: str,
    disabled_by: er.RegistryEntryDisabler | None = None,
) -> er.RegistryEntry:
    """Register a sensor the way 1.2.2 did, with its old entity_id."""
    registered = entity_registry.async_get_or_create(
        Platform.SENSOR,
        DOMAIN,
        f"{UNIQUE_ID}_{key}",
        config_entry=entry,
        suggested_object_id=V122_ENTITY_IDS[key].split(".", 1)[1],
        original_name=f"RAD HW Afval {SENSOR_TYPES[key]}",
        disabled_by=disabled_by,
    )
    assert registered.entity_id == V122_ENTITY_IDS[key]
    assert registered.disabled_by is disabled_by
    return registered


def _by_key(
    entity_registry: er.EntityRegistry, entry: MockConfigEntry
) -> dict[str, er.RegistryEntry]:
    """Return the entry's registry entries keyed by waste type."""
    return {
        reg.unique_id.removeprefix(f"{UNIQUE_ID}_"): reg
        for reg in er.async_entries_for_config_entry(entity_registry, entry.entry_id)
    }


def _disabled(
    entity_registry: er.EntityRegistry, entry: MockConfigEntry
) -> dict[str, er.RegistryEntryDisabler | None]:
    """Return disabled_by per waste type."""
    return {
        key: reg.disabled_by for key, reg in _by_key(entity_registry, entry).items()
    }


async def _setup(hass: HomeAssistant, entry: MockConfigEntry) -> None:
    """Set up an entry that was already added to hass."""
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    assert entry.state is ConfigEntryState.LOADED


async def _reload(hass: HomeAssistant, entry: MockConfigEntry) -> None:
    """Reload a loaded entry."""
    assert await hass.config_entries.async_reload(entry.entry_id)
    await hass.async_block_till_done()
    assert entry.state is ConfigEntryState.LOADED


async def _setup_migrated_v122(
    hass: HomeAssistant, entity_registry: er.EntityRegistry
) -> MockConfigEntry:
    """Migrate a 1.2.2 entry with GFT and PMD deselected and set it up.

    GFT was selected once and deselected later, so 1.2.2 left an enabled
    registry entry behind. PMD was never selected and never registered.
    """
    entry = _legacy_entry(LEGACY_OPTIONS)
    entry.add_to_hass(hass)
    for key in ("rest", "gft", "papier"):
        _register_v122(entity_registry, entry, key)
    await _setup(hass, entry)
    return entry


async def test_migrate_deselection_to_disabled_entities(
    hass: HomeAssistant,
    entity_registry: er.EntityRegistry,
    mock_api_ok: AiohttpClientMocker,
) -> None:
    """Deselected types become disabled entities; the rest keeps working."""
    entry = await _setup_migrated_v122(hass, entity_registry)

    assert entry.version == 1
    assert entry.minor_version == 2
    assert entry.options == {CONF_DATE_FORMAT: "%d/%m"}
    assert entry.data == ENTRY_DATA

    by_key = _by_key(entity_registry, entry)
    assert set(by_key) == set(ALL_WASTE_TYPES)

    # Registered and enabled before: now disabled by the user, same entity_id.
    assert by_key["gft"].entity_id == V122_ENTITY_IDS["gft"]
    assert by_key["gft"].disabled_by is USER
    assert hass.states.get(V122_ENTITY_IDS["gft"]) is None

    # Never registered before: registered now with a new-style entity_id,
    # disabled like the user's own choice.
    assert by_key["pmd"].entity_id == ENTITY_IDS["pmd"]
    assert by_key["pmd"].disabled_by is USER
    assert hass.states.get(ENTITY_IDS["pmd"]) is None

    # Selected types keep their 1.2.2 entity_id and show the date format kept
    # from the options.
    for key, state, formatted in (
        ("rest", "2026-12-04", "04/12"),
        ("papier", "2026-11-20", "20/11"),
    ):
        assert by_key[key].entity_id == V122_ENTITY_IDS[key]
        assert by_key[key].disabled_by is None
        current = hass.states.get(V122_ENTITY_IDS[key])
        assert current.state == state
        assert current.attributes["formatted_date"] == formatted
        assert hass.states.get(ENTITY_IDS[key]) is None


@pytest.mark.parametrize(
    "resources",
    [
        pytest.param(["rest", "gft", "papier", "pmd"], id="all"),
        pytest.param(["pmd", "textiel", "papier", "gft", "rest"], id="unknown_extra"),
    ],
)
async def test_migrate_all_selected(
    hass: HomeAssistant,
    entity_registry: er.EntityRegistry,
    mock_api_ok: AiohttpClientMocker,
    resources: list[str],
) -> None:
    """With every type selected nothing is disabled."""
    entry = _legacy_entry({CONF_RESOURCES: resources})
    entry.add_to_hass(hass)
    for key in ALL_WASTE_TYPES:
        _register_v122(entity_registry, entry, key)

    await _setup(hass, entry)

    assert entry.minor_version == 2
    assert entry.options == {}
    assert entry.data == ENTRY_DATA
    assert _disabled(entity_registry, entry) == dict.fromkeys(ALL_WASTE_TYPES)
    for entity_id in V122_ENTITY_IDS.values():
        assert hass.states.get(entity_id).state != STATE_UNAVAILABLE


@pytest.mark.parametrize(
    ("resources", "deselected"),
    [
        pytest.param(["pmd"], ["rest", "gft", "papier"], id="single"),
        pytest.param(["gft", "rest"], ["papier", "pmd"], id="order_ignored"),
        pytest.param([], ["rest", "gft", "papier", "pmd"], id="empty"),
    ],
)
async def test_migrate_never_registered(
    hass: HomeAssistant,
    entity_registry: er.EntityRegistry,
    mock_api_ok: AiohttpClientMocker,
    resources: list[str],
    deselected: list[str],
) -> None:
    """Deselected types that never had an entity are registered disabled."""
    entry = _legacy_entry({CONF_RESOURCES: resources})
    entry.add_to_hass(hass)

    await _setup(hass, entry)

    assert entry.options == {}
    assert entry.data == ENTRY_DATA
    assert _disabled(entity_registry, entry) == {
        key: USER if key in deselected else None for key in ALL_WASTE_TYPES
    }


@pytest.mark.parametrize(
    "options",
    [
        pytest.param({}, id="no_options"),
        pytest.param({CONF_DATE_FORMAT: "%d/%m"}, id="date_format_only"),
    ],
)
async def test_migrate_without_resources(
    hass: HomeAssistant,
    entity_registry: er.EntityRegistry,
    mock_api_ok: AiohttpClientMocker,
    options: dict[str, Any],
) -> None:
    """Entries without a stored selection had all sensors; none is disabled."""
    entry = _legacy_entry(options)
    entry.add_to_hass(hass)
    _register_v122(entity_registry, entry, "gft")

    await _setup(hass, entry)

    assert entry.minor_version == 2
    assert entry.options == options
    assert entry.data == ENTRY_DATA
    assert _disabled(entity_registry, entry) == dict.fromkeys(ALL_WASTE_TYPES)
    assert hass.states.get(V122_ENTITY_IDS["gft"]).state == "2026-11-27"


async def test_migrate_keeps_existing_disabled_by(
    hass: HomeAssistant,
    entity_registry: er.EntityRegistry,
    mock_api_ok: AiohttpClientMocker,
) -> None:
    """Entities the user disabled earlier stay disabled, selected or not."""
    entry = _legacy_entry(LEGACY_OPTIONS)
    entry.add_to_hass(hass)
    _register_v122(entity_registry, entry, "gft", disabled_by=USER)  # deselected
    _register_v122(entity_registry, entry, "rest", disabled_by=USER)  # selected
    _register_v122(entity_registry, entry, "papier")

    await _setup(hass, entry)

    assert _disabled(entity_registry, entry) == {
        "rest": USER,
        "gft": USER,
        "papier": None,
        "pmd": USER,
    }
    assert hass.states.get(V122_ENTITY_IDS["rest"]) is None
    assert hass.states.get(V122_ENTITY_IDS["papier"]).state == "2026-11-20"


async def test_migrate_deleted_entity_stays_disabled(
    hass: HomeAssistant,
    entity_registry: er.EntityRegistry,
    mock_api_ok: AiohttpClientMocker,
) -> None:
    """A deselected sensor the user deleted in 1.2.x comes back disabled."""
    entry = _legacy_entry(LEGACY_OPTIONS)
    entry.add_to_hass(hass)
    for key in ("rest", "gft", "papier"):
        _register_v122(entity_registry, entry, key)
    # The user deleted the "no longer provided" GFT sensor after deselecting it.
    entity_registry.async_remove(V122_ENTITY_IDS["gft"])

    await _setup(hass, entry)

    by_key = _by_key(entity_registry, entry)
    assert set(by_key) == set(ALL_WASTE_TYPES)
    assert by_key["gft"].disabled_by is USER
    assert by_key["pmd"].disabled_by is USER
    assert hass.states.get(by_key["gft"].entity_id) is None
    assert hass.states.get(by_key["pmd"].entity_id) is None
    assert hass.states.get(V122_ENTITY_IDS["rest"]).state == "2026-12-04"


async def test_migrate_future_major_version_fails(
    hass: HomeAssistant,
    entity_registry: er.EntityRegistry,
    mock_api_ok: AiohttpClientMocker,
) -> None:
    """An entry from a newer major version is not downgraded."""
    entry = _legacy_entry(LEGACY_OPTIONS, version=2)
    entry.add_to_hass(hass)
    _register_v122(entity_registry, entry, "gft")

    assert not await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()

    assert entry.state is ConfigEntryState.MIGRATION_ERROR
    assert entry.version == 2
    assert entry.minor_version == 1
    assert entry.options == LEGACY_OPTIONS
    assert entry.data == ENTRY_DATA
    assert _disabled(entity_registry, entry) == {"gft": None}
    assert mock_api_ok.call_count == 0

    # Recent HA versions refuse the downgrade before calling the integration,
    # so call the integration's own guard directly as well.
    assert not await async_migrate_entry(hass, entry)
    assert entry.version == 2
    assert entry.minor_version == 1
    assert entry.options == LEGACY_OPTIONS
    assert entry.data == ENTRY_DATA
    assert _disabled(entity_registry, entry) == {"gft": None}


async def test_newer_minor_version_loads_unchanged(
    hass: HomeAssistant,
    entity_registry: er.EntityRegistry,
    mock_api_ok: AiohttpClientMocker,
) -> None:
    """A newer minor version of the same major version still loads."""
    entry = create_entry(options={CONF_DATE_FORMAT: "%d/%m"}, minor_version=3)
    entry.add_to_hass(hass)

    await _setup(hass, entry)

    assert entry.minor_version == 3
    assert entry.options == {CONF_DATE_FORMAT: "%d/%m"}
    assert entry.data == ENTRY_DATA
    assert _disabled(entity_registry, entry) == dict.fromkeys(ALL_WASTE_TYPES)


async def test_reenabled_entity_stays_enabled(
    hass: HomeAssistant,
    entity_registry: er.EntityRegistry,
    mock_api_ok: AiohttpClientMocker,
) -> None:
    """The migration runs once; a sensor the user enables again stays enabled."""
    entry = await _setup_migrated_v122(hass, entity_registry)
    assert _disabled(entity_registry, entry)["pmd"] is USER

    entity_registry.async_update_entity(ENTITY_IDS["pmd"], disabled_by=None)
    await _reload(hass, entry)

    assert entity_registry.async_get(ENTITY_IDS["pmd"]).disabled_by is None
    assert hass.states.get(ENTITY_IDS["pmd"]).state == "2026-11-19"

    await _reload(hass, entry)
    assert entity_registry.async_get(ENTITY_IDS["pmd"]).disabled_by is None
    assert hass.states.get(ENTITY_IDS["pmd"]).state == "2026-11-19"


async def test_migration_survives_setup_retry(
    hass: HomeAssistant,
    entity_registry: er.EntityRegistry,
    aioclient_mock: AiohttpClientMocker,
    frozen_time: FrozenDateTimeFactory,
) -> None:
    """A failing first refresh after the migration still ends up disabled."""
    mock_api(aioclient_mock, calendar_kwargs={"status": HTTPStatus.BAD_GATEWAY})
    entry = _legacy_entry(LEGACY_OPTIONS)
    entry.add_to_hass(hass)
    for key in ("rest", "gft", "papier"):
        _register_v122(entity_registry, entry, key)

    assert not await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()

    # The migration ran before the setup failed and is stored.
    assert entry.state is ConfigEntryState.SETUP_RETRY
    assert entry.minor_version == 2
    assert entry.options == {CONF_DATE_FORMAT: "%d/%m"}
    assert entry.data == ENTRY_DATA
    assert _disabled(entity_registry, entry) == {
        "rest": None,
        "gft": USER,
        "papier": None,
        "pmd": USER,
    }

    aioclient_mock.clear_requests()
    mock_api(aioclient_mock)
    frozen_time.tick(timedelta(minutes=1))
    async_fire_time_changed(hass)
    await hass.async_block_till_done(wait_background_tasks=True)

    assert entry.state is ConfigEntryState.LOADED
    assert entry.minor_version == 2
    assert _disabled(entity_registry, entry) == {
        "rest": None,
        "gft": USER,
        "papier": None,
        "pmd": USER,
    }
    assert hass.states.get(V122_ENTITY_IDS["rest"]).state == "2026-12-04"
    assert hass.states.get(ENTITY_IDS["pmd"]) is None


async def test_migration_is_idempotent(
    hass: HomeAssistant,
    entity_registry: er.EntityRegistry,
    mock_api_ok: AiohttpClientMocker,
) -> None:
    """Later setups do not migrate again or disable re-enabled entities."""
    entry = await _setup_migrated_v122(hass, entity_registry)
    data = dict(entry.data)
    options = dict(entry.options)
    disabled = _disabled(entity_registry, entry)
    assert disabled == {"rest": None, "gft": USER, "papier": None, "pmd": USER}

    await _reload(hass, entry)
    assert entry.minor_version == 2
    assert entry.data == data
    assert entry.options == options
    assert _disabled(entity_registry, entry) == disabled

    # The user turns both waste types back on.
    entity_registry.async_update_entity(V122_ENTITY_IDS["gft"], disabled_by=None)
    entity_registry.async_update_entity(ENTITY_IDS["pmd"], disabled_by=None)
    await _reload(hass, entry)
    await _reload(hass, entry)

    assert _disabled(entity_registry, entry) == dict.fromkeys(ALL_WASTE_TYPES)
    assert hass.states.get(V122_ENTITY_IDS["gft"]).state == "2026-11-27"
    assert hass.states.get(ENTITY_IDS["pmd"]).state == "2026-11-19"
    assert entry.data == data
    assert entry.options == options

    # Calling the migration on a migrated entry changes nothing either.
    assert await async_migrate_entry(hass, entry)
    assert entry.minor_version == 2
    assert entry.data == data
    assert entry.options == options
    assert _disabled(entity_registry, entry) == dict.fromkeys(ALL_WASTE_TYPES)

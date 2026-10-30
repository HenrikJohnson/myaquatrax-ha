"""The MyAquaTrax integration."""
from __future__ import annotations

import logging

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant

from .const import DOMAIN
from .coordinator import AquaTraxCoordinator

_LOGGER = logging.getLogger(__name__)

PLATFORMS: list[Platform] = [Platform.SENSOR]


type AquaTraxConfigEntry = ConfigEntry[AquaTraxCoordinator]


async def async_setup_entry(hass: HomeAssistant, entry: AquaTraxConfigEntry) -> bool:
    """Set up MyAquaTrax from a config entry."""
    coordinator = AquaTraxCoordinator(hass, entry.data)
    await coordinator.async_config_entry_first_refresh()

    entry.runtime_data = coordinator

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)

    return True


async def async_unload_entry(hass: HomeAssistant, entry: AquaTraxConfigEntry) -> bool:
    """Unload a config entry."""
    return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)

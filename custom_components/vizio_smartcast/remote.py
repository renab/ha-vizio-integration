"""Remote platform for Vizio SmartCast devices."""

from __future__ import annotations

import asyncio
from collections.abc import Iterable
from datetime import timedelta
import logging
from typing import Any

from pyvizio import VizioAsync
import voluptuous as vol

from homeassistant.components.remote import (
    ATTR_DELAY_SECS,
    ATTR_NUM_REPEATS,
    DEFAULT_DELAY_SECS,
    RemoteEntity,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import (
    CONF_ACCESS_TOKEN,
    CONF_DEVICE_CLASS,
    CONF_HOST,
    CONF_NAME,
)
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ServiceValidationError
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from .const import DEFAULT_TIMEOUT, DEVICE_ID, DOMAIN, VIZIO_DEVICE_CLASSES

PARALLEL_UPDATES = 0
SCAN_INTERVAL = timedelta(seconds=30)

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant,
    config_entry: ConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up a Vizio remote entity."""
    host = config_entry.data[CONF_HOST]
    token = config_entry.data.get(CONF_ACCESS_TOKEN)
    name = config_entry.data[CONF_NAME]
    device_class = config_entry.data[CONF_DEVICE_CLASS]

    device = VizioAsync(
        DEVICE_ID,
        host,
        name,
        auth_token=token,
        device_type=VIZIO_DEVICE_CLASSES[device_class],
        session=async_get_clientsession(hass, False),
        timeout=DEFAULT_TIMEOUT,
    )

    async_add_entities(
        [VizioRemote(config_entry, device, name)], update_before_add=True
    )


class VizioRemote(RemoteEntity):
    """Remote entity for Vizio SmartCast devices."""

    _attr_has_entity_name = True
    _attr_name = "Remote"

    def __init__(self, config_entry: ConfigEntry, device: VizioAsync, name: str) -> None:
        """Initialize the remote entity."""
        self._config_entry = config_entry
        self._device = device

        unique_id = config_entry.unique_id
        assert unique_id
        self._attr_unique_id = unique_id
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, unique_id)},
            manufacturer="VIZIO",
            name=name,
        )

        valid_keys = set(self._device.get_remote_keys_list())
        self._command_map: dict[str, str] = {key.lower(): key for key in valid_keys}

    async def async_update(self) -> None:
        """Retrieve latest power state of the device."""
        try:
            is_on = await self._device.get_power_state(log_api_exception=False)
        except Exception as err:
            _LOGGER.debug(
                "Error getting power state for %s: %s",
                self._config_entry.data[CONF_HOST],
                err,
            )
            self._attr_available = False
            return

        if is_on is None:
            self._attr_available = False
            return

        self._attr_available = True
        self._attr_is_on = is_on

    def _resolve_command(self, command: str) -> str:
        """Resolve a lowercased command string to a pyvizio key name."""
        if resolved := self._command_map.get(command):
            return resolved
        raise ServiceValidationError(
            translation_domain=DOMAIN,
            translation_key="unknown_command",
            translation_placeholders={"command": command},
        )

    async def async_turn_on(self, **kwargs: Any) -> None:
        """Turn on the device."""
        await self._device.pow_on(log_api_exception=False)
        self._attr_is_on = True

    async def async_turn_off(self, **kwargs: Any) -> None:
        """Turn off the device."""
        await self._device.pow_off(log_api_exception=False)
        self._attr_is_on = False

    async def async_send_command(self, command: Iterable[str], **kwargs: Any) -> None:
        """Send remote commands to the device."""
        num_repeats: int = kwargs.get(ATTR_NUM_REPEATS, 1)
        delay: float = kwargs.get(ATTR_DELAY_SECS, DEFAULT_DELAY_SECS)
        resolved = [vol.All(vol.Lower, self._resolve_command)(cmd) for cmd in command]

        for i in range(num_repeats):
            for cmd in resolved:
                await self._device.remote(cmd, log_api_exception=False)
            if i < num_repeats - 1:
                await asyncio.sleep(delay)

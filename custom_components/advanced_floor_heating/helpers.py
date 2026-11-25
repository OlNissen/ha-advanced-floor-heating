"""Shared helpers for the Advanced Floor Heating integration."""
from homeassistant.core import callback
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.dispatcher import async_dispatcher_connect

from .const import DOMAIN


# Signaler: Masteren skifter tilstand / et rums alarmer aendrer sig
MASTER_SIGNAL = f"{DOMAIN}_master_update"
ALARM_SIGNAL = f"{DOMAIN}_alarm_update"


def update_signal(entry_id: str) -> str:
    """Dispatcher signal sent by the climate entity whenever its state changed."""
    return f"{DOMAIN}_{entry_id}_update"


def device_info(entry) -> DeviceInfo:
    """One device per room, so all entities of a room are grouped together."""
    return DeviceInfo(
        identifiers={(DOMAIN, entry.entry_id)},
        name=entry.data["name"],
        manufacturer="OlNissen",
        model="Advanced Floor Heating",
    )


class UpdateListenerMixin:
    """Lets helper entities (sensor/number) refresh the moment the climate entity changes.

    The class using this mixin must set ``self._entry_id``.
    """

    _attr_should_poll = False

    async def async_added_to_hass(self):
        await super().async_added_to_hass()
        self.async_on_remove(
            async_dispatcher_connect(
                self.hass, update_signal(self._entry_id), self._handle_climate_update
            )
        )

    @callback
    def _handle_climate_update(self):
        self.async_write_ha_state()

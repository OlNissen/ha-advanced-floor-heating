"""Masterens hjemkomsttidspunkt: huset forvarmes, så det er varmt, når I kommer hjem."""
from datetime import datetime

from homeassistant.components.datetime import DateTimeEntity
from homeassistant.helpers.dispatcher import async_dispatcher_connect
from homeassistant.helpers.restore_state import RestoreEntity

from .const import DOMAIN, MASTER_KEY
from .helpers import device_info, MASTER_SIGNAL, MASTER_VALUES_SIGNAL


async def async_setup_entry(hass, entry, async_add_entities):
    async_add_entities([MasterReturnDateTime(entry)])


class MasterReturnDateTime(RestoreEntity, DateTimeEntity):
    """Sæt Masteren til Ubeboet/Frostsikker og vælg hjemkomst. Et tidspunkt i fortiden annullerer."""

    _attr_should_poll = False
    _attr_icon = "mdi:home-clock-outline"

    def __init__(self, entry):
        self._attr_name = f"{entry.data['name']} Hjemkomst"
        self._attr_unique_id = f"{entry.entry_id}_return_at"
        self._attr_device_info = device_info(entry)

    @property
    def _hub(self):
        return self.hass.data[DOMAIN].get(MASTER_KEY)

    async def async_added_to_hass(self):
        await super().async_added_to_hass()
        last = await self.async_get_last_state()
        if last is not None and self._hub:
            try:
                # Også et tidspunkt, der er passeret under en genstart, gendannes: så startes varmen straks
                value = datetime.fromisoformat(last.state)
            except (TypeError, ValueError):
                value = None
            if value is not None and value.tzinfo is not None:
                self._hub.return_at = value
        for signal in (MASTER_SIGNAL, MASTER_VALUES_SIGNAL):
            self.async_on_remove(async_dispatcher_connect(self.hass, signal, self.async_write_ha_state))

    @property
    def native_value(self):
        return self._hub.return_at if self._hub else None

    @property
    def extra_state_attributes(self):
        hub = self._hub
        if not hub:
            return {}
        start = hub.preheat_start()
        hours, slowest = hub.preheat_needed()
        return {
            "forvarmning_starter": start.isoformat() if start else None,
            "forvarmning_timer": round(hours, 1),
            "langsomste_rum": slowest,
        }

    async def async_set_value(self, value):
        if self._hub:
            self._hub.set_return_at(value)
        self.async_write_ha_state()

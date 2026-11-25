"""Tilstandsvaelgere: Masterens husstilstand og hvert rums egen tilstand."""
from homeassistant.components.select import SelectEntity
from homeassistant.helpers.dispatcher import async_dispatcher_connect
from homeassistant.helpers.restore_state import RestoreEntity

from .const import (
    DOMAIN, MASTER_KEY, HOUSE_MODES, ROOM_MODE_OPTIONS, MODE_OCCUPIED,
    CONF_ENTRY_TYPE, TYPE_MASTER,
)
from .helpers import UpdateListenerMixin, device_info, MASTER_SIGNAL


async def async_setup_entry(hass, entry, async_add_entities):
    if entry.data.get(CONF_ENTRY_TYPE) == TYPE_MASTER:
        async_add_entities([MasterModeSelect(entry)])
    else:
        async_add_entities([RoomModeSelect(entry)])


class MasterModeSelect(RestoreEntity, SelectEntity):
    """Husets tilstand (Beboet / Ubeboet / Frostsikker / Slukket) - sendes ud til alle rum."""

    _attr_should_poll = False
    _attr_icon = "mdi:home-thermometer"
    _attr_options = HOUSE_MODES

    def __init__(self, entry):
        self._entry = entry
        self._attr_name = entry.data["name"]
        self._attr_unique_id = f"{entry.entry_id}_master_mode"
        self._attr_device_info = device_info(entry)

    @property
    def _hub(self):
        return self.hass.data[DOMAIN].get(MASTER_KEY)

    async def async_added_to_hass(self):
        await super().async_added_to_hass()
        last = await self.async_get_last_state()
        if last is not None and last.state in HOUSE_MODES and self._hub:
            # Genskab tilstanden uden at sende besked (rummene laeser den selv ved start)
            self._hub.set_mode(last.state, notify=False)
        self.async_on_remove(
            async_dispatcher_connect(self.hass, MASTER_SIGNAL, self.async_write_ha_state)
        )
        if self._hub:
            self._hub.notify()

    @property
    def current_option(self):
        return self._hub.mode if self._hub else MODE_OCCUPIED

    async def async_select_option(self, option):
        if self._hub:
            self._hub.set_mode(option)
        self.async_write_ha_state()


class RoomModeSelect(UpdateListenerMixin, SelectEntity):
    """Rummets egen tilstand: 'Fælles' foelger Masteren, ellers overstyrer den."""

    _attr_icon = "mdi:home-switch"
    _attr_options = ROOM_MODE_OPTIONS

    def __init__(self, entry):
        self._attr_name = f"{entry.data['name']} Husstilstand"
        self._attr_unique_id = f"{entry.entry_id}_room_mode"
        self._attr_device_info = device_info(entry)
        self._entry_id = entry.entry_id

    @property
    def current_option(self):
        climate = self.hass.data[DOMAIN].get(self._entry_id)
        return climate.mode_override if climate else None

    async def async_select_option(self, option):
        climate = self.hass.data[DOMAIN].get(self._entry_id)
        if climate:
            await climate.async_set_mode_override(option)

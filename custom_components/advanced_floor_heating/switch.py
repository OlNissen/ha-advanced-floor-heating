"""Kontakt der starter/stopper autotune af PID for et rum."""
from homeassistant.components.switch import SwitchEntity
from .const import DOMAIN, CONF_ENTRY_TYPE, TYPE_PUMP
from .helpers import UpdateListenerMixin, device_info


async def async_setup_entry(hass, entry, async_add_entities):
    if entry.data.get(CONF_ENTRY_TYPE) == TYPE_PUMP:
        from .pump_entities import pump_switches
        async_add_entities(pump_switches(entry))
        return
    async_add_entities([AutotuneSwitch(entry)])


class AutotuneSwitch(UpdateListenerMixin, SwitchEntity):
    """Tændt = autotune kører. Tænd for at starte (standardværdier), sluk for at afbryde."""

    _attr_icon = "mdi:auto-fix"

    def __init__(self, entry):
        self._attr_name = f"{entry.data['name']} Autotune"
        self._attr_unique_id = f"{entry.entry_id}_autotune"
        self._attr_device_info = device_info(entry)
        self._entry_id = entry.entry_id

    def _climate(self):
        return self.hass.data[DOMAIN].get(self._entry_id)

    @property
    def is_on(self):
        climate = self._climate()
        return bool(climate and climate.autotune_active)

    @property
    def extra_state_attributes(self):
        climate = self._climate()
        return {"status": climate._autotune_msg if climate else None}

    async def async_turn_on(self, **kwargs):
        climate = self._climate()
        if climate:
            await climate.async_start_autotune()

    async def async_turn_off(self, **kwargs):
        climate = self._climate()
        if climate:
            await climate.async_stop_autotune()

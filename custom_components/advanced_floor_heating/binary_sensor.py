"""Alarmer: ét samlet 'Problem' pr. rum og et for hele huset (Masteren)."""
from homeassistant.components.binary_sensor import BinarySensorEntity, BinarySensorDeviceClass
from homeassistant.helpers.dispatcher import async_dispatcher_connect

from .const import DOMAIN, CONF_ENTRY_TYPE, TYPE_MASTER
from .helpers import UpdateListenerMixin, device_info, ALARM_SIGNAL


async def async_setup_entry(hass, entry, async_add_entities):
    if entry.data.get(CONF_ENTRY_TYPE) == TYPE_MASTER:
        async_add_entities([MasterAlarm(entry)])
    else:
        async_add_entities([RoomAlarm(entry)])


class RoomAlarm(UpdateListenerMixin, BinarySensorEntity):
    """Taendt, naar rummet har en alarm (foeler mangler/gammel, ventil sidder maaske fast)."""

    _attr_device_class = BinarySensorDeviceClass.PROBLEM

    def __init__(self, entry):
        self._attr_name = f"{entry.data['name']} Alarm"
        self._attr_unique_id = f"{entry.entry_id}_alarm"
        self._attr_device_info = device_info(entry)
        self._entry_id = entry.entry_id

    def _climate(self):
        return self.hass.data[DOMAIN].get(self._entry_id)

    @property
    def is_on(self):
        climate = self._climate()
        return bool(climate and climate.alarms)

    @property
    def extra_state_attributes(self):
        climate = self._climate()
        return {"alarmer": climate.alarms if climate else []}


class MasterAlarm(BinarySensorEntity):
    """Taendt, hvis NOGET rum har en alarm. Attributten 'rum' viser hvilke."""

    _attr_should_poll = False
    _attr_device_class = BinarySensorDeviceClass.PROBLEM

    def __init__(self, entry):
        self._attr_name = f"{entry.data['name']} Alarm"
        self._attr_unique_id = f"{entry.entry_id}_alarm"
        self._attr_device_info = device_info(entry)

    async def async_added_to_hass(self):
        self.async_on_remove(
            async_dispatcher_connect(self.hass, ALARM_SIGNAL, self.async_write_ha_state)
        )

    def _alarms(self):
        out = {}
        for key, obj in self.hass.data.get(DOMAIN, {}).items():
            alarms = getattr(obj, "alarms", None)
            if alarms:
                out[obj.name] = alarms
        return out

    @property
    def is_on(self):
        return bool(self._alarms())

    @property
    def extra_state_attributes(self):
        return {"rum": self._alarms()}

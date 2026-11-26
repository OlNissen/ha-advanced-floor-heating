import logging
from homeassistant.components.number import NumberEntity, RestoreNumber
from homeassistant.const import UnitOfTemperature
from homeassistant.helpers.dispatcher import async_dispatcher_connect
from .const import (
    DOMAIN, MASTER_KEY, CONF_ENTRY_TYPE, TYPE_MASTER,
    DEFAULT_UNOCCUPIED_TEMP, DEFAULT_FROST_TEMP,
)
from .helpers import UpdateListenerMixin, device_info, MASTER_SIGNAL, MASTER_VALUES_SIGNAL

_LOGGER = logging.getLogger(__name__)

async def async_setup_entry(hass, entry, async_add_entities):
    """Set up the Room and Floor Setpoint sliders (or the Master's temperatures)."""
    if entry.data.get(CONF_ENTRY_TYPE) == TYPE_MASTER:
        async_add_entities([
            MasterTempNumber(entry, "unoccupied", "Ubeboet Temperatur", DEFAULT_UNOCCUPIED_TEMP, 10, 25),
            MasterTempNumber(entry, "frost", "Frost Temperatur", DEFAULT_FROST_TEMP, 5, 20),
            MasterSummerNumber(entry),
            MasterPreheatNumber(entry),
        ])
        return
    async_add_entities([RoomSetpointNumber(entry), FloorSetpointNumber(entry)])


class MasterTempNumber(RestoreNumber):
    """Masterens temperaturer: hvad et rum holder i Ubeboet / Frostsikker."""

    _attr_should_poll = False
    _attr_native_unit_of_measurement = UnitOfTemperature.CELSIUS
    _attr_native_step = 0.5

    def __init__(self, entry, kind, label, default, min_value, max_value):
        self._kind = kind
        self._default = default
        self._attr_name = f"{entry.data['name']} {label}"
        self._attr_unique_id = f"{entry.entry_id}_{kind}_temp"
        self._attr_device_info = device_info(entry)
        self._attr_native_min_value = float(min_value)
        self._attr_native_max_value = float(max_value)
        self._attr_icon = "mdi:snowflake-thermometer" if kind == "frost" else "mdi:home-export-outline"

    @property
    def _hub(self):
        return self.hass.data[DOMAIN].get(MASTER_KEY)

    async def async_added_to_hass(self):
        await super().async_added_to_hass()
        last = await self.async_get_last_number_data()
        if last is not None and last.native_value is not None and self._hub:
            self._set(last.native_value, notify=False)
        self.async_on_remove(
            async_dispatcher_connect(self.hass, MASTER_SIGNAL, self.async_write_ha_state)
        )

    def _set(self, value, notify=True):
        if self._kind == "frost":
            self._hub.set_frost_temp(value, notify)
        else:
            self._hub.set_unoccupied_temp(value, notify)

    @property
    def native_value(self):
        if not self._hub:
            return self._default
        return self._hub.frost_temp if self._kind == "frost" else self._hub.unoccupied_temp

    async def async_set_native_value(self, value):
        if self._hub:
            self._set(value)
        self.async_write_ha_state()


class _MasterSettingNumber(RestoreNumber):
    """Fælles for Masterens øvrige tal-indstillinger."""

    _attr_should_poll = False
    _attr_native_min_value = 0.0

    def __init__(self, entry, label, uid):
        self._attr_name = f"{entry.data['name']} {label}"
        self._attr_unique_id = f"{entry.entry_id}_{uid}"
        self._attr_device_info = device_info(entry)

    @property
    def _hub(self):
        return self.hass.data[DOMAIN].get(MASTER_KEY)

    async def async_added_to_hass(self):
        await super().async_added_to_hass()
        for signal in (MASTER_SIGNAL, MASTER_VALUES_SIGNAL):
            self.async_on_remove(async_dispatcher_connect(self.hass, signal, self.async_write_ha_state))


class MasterSummerNumber(_MasterSettingNumber):
    """Sommerstop: varmen holder pause, når døgnmidlet ude når grænsen. 0 = slået fra."""

    _attr_native_unit_of_measurement = UnitOfTemperature.CELSIUS
    _attr_native_step = 0.5
    _attr_native_max_value = 25.0
    _attr_icon = "mdi:sun-thermometer-outline"

    def __init__(self, entry):
        super().__init__(entry, "Sommerstop Grænse", "summer_limit")

    async def async_added_to_hass(self):
        await super().async_added_to_hass()
        hub = self._hub
        if hub is None:
            return
        last_state = await self.async_get_last_state()
        if last_state is not None and last_state.attributes.get("middel_data"):
            hub.summer.restore(last_state.attributes["middel_data"])
        last = await self.async_get_last_number_data()
        if last is not None and last.native_value is not None:
            hub.set_summer_limit(last.native_value, notify=False)

    @property
    def native_value(self):
        return self._hub.summer.limit if self._hub else 0.0

    @property
    def extra_state_attributes(self):
        hub = self._hub
        if not hub:
            return {}
        mean = hub.summer.mean
        return {
            "aktiv": hub.summer_active,
            "ude_doegnmiddel": None if mean is None else round(mean, 1),
            "middel_data": hub.summer.as_dict(),   # gemmes, så middelværdien overlever en genstart
        }

    async def async_set_native_value(self, value):
        if self._hub:
            self._hub.set_summer_limit(value)
        self.async_write_ha_state()


class MasterPreheatNumber(_MasterSettingNumber):
    """Ferie: faste timers forvarmning før hjemkomst. 0 = beregn ud fra rummenes varmemodeller."""

    _attr_native_unit_of_measurement = "h"
    _attr_native_step = 1.0
    _attr_native_max_value = 72.0
    _attr_icon = "mdi:timer-sand"

    def __init__(self, entry):
        super().__init__(entry, "Ferie Forvarmning", "preheat_hours")

    async def async_added_to_hass(self):
        await super().async_added_to_hass()
        last = await self.async_get_last_number_data()
        if last is not None and last.native_value is not None and self._hub:
            self._hub.preheat_manual_hours = float(last.native_value)

    @property
    def native_value(self):
        return self._hub.preheat_manual_hours if self._hub else 0.0

    async def async_set_native_value(self, value):
        if self._hub:
            self._hub.preheat_manual_hours = float(value)
            self._hub.notify_values()
        self.async_write_ha_state()


class RoomSetpointNumber(UpdateListenerMixin, NumberEntity):
    """Number entity: viser og styrer rummets måltemperatur (rum-setpunkt)."""

    def __init__(self, entry):
        self._attr_name = f"{entry.data['name']} Rum Setpunkt"
        self._attr_unique_id = f"{entry.entry_id}_room_setpoint"
        self._attr_device_info = device_info(entry)
        self._attr_native_unit_of_measurement = UnitOfTemperature.CELSIUS
        self._attr_native_step = 0.5
        self._attr_native_min_value = 10.0
        self._attr_native_max_value = 30.0
        self._entry_id = entry.entry_id

    @property
    def native_value(self):
        climate = self.hass.data[DOMAIN].get(self._entry_id)
        if climate:
            return float(climate._target_temp_room)
        return None

    async def async_set_native_value(self, value: float):
        climate = self.hass.data[DOMAIN].get(self._entry_id)
        if climate:
            await climate.async_set_room_temperature(value)

class FloorSetpointNumber(UpdateListenerMixin, NumberEntity):
    """Number entity to control the floor target temperature."""

    def __init__(self, entry):
        self._attr_name = f"{entry.data['name']} Gulv Setpunkt"
        self._attr_unique_id = f"{entry.entry_id}_floor_setpoint"
        self._attr_device_info = device_info(entry)
        self._attr_native_unit_of_measurement = UnitOfTemperature.CELSIUS
        self._attr_native_step = 0.5
        self._attr_native_min_value = 15.0
        self._attr_native_max_value = 35.0
        self._entry_id = entry.entry_id

    @property
    def native_value(self):
        """Read the floor setpoint directly from the climate entity."""
        climate = self.hass.data[DOMAIN].get(self._entry_id)
        if climate:
            return float(climate._target_temp_floor)
        return None

    async def async_set_native_value(self, value: float):
        """Write the new floor setpoint to the climate entity (floor only - not the room)."""
        climate = self.hass.data[DOMAIN].get(self._entry_id)
        if climate:
            await climate.async_set_floor_temperature(value)

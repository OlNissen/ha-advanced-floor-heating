import logging
from homeassistant.components.number import NumberEntity, RestoreNumber
from homeassistant.const import UnitOfTemperature
from homeassistant.helpers.dispatcher import async_dispatcher_connect
from .const import (
    DOMAIN, MASTER_KEY, CONF_ENTRY_TYPE, TYPE_MASTER,
    DEFAULT_UNOCCUPIED_TEMP, DEFAULT_FROST_TEMP,
)
from .helpers import UpdateListenerMixin, device_info, MASTER_SIGNAL

_LOGGER = logging.getLogger(__name__)

async def async_setup_entry(hass, entry, async_add_entities):
    """Set up the Room and Floor Setpoint sliders (or the Master's temperatures)."""
    if entry.data.get(CONF_ENTRY_TYPE) == TYPE_MASTER:
        async_add_entities([
            MasterTempNumber(entry, "unoccupied", "Ubeboet Temperatur", DEFAULT_UNOCCUPIED_TEMP, 10, 25),
            MasterTempNumber(entry, "frost", "Frost Temperatur", DEFAULT_FROST_TEMP, 5, 20),
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

import logging
from homeassistant.components.number import NumberEntity
from homeassistant.const import UnitOfTemperature
from .const import DOMAIN
from .helpers import UpdateListenerMixin, device_info

_LOGGER = logging.getLogger(__name__)

async def async_setup_entry(hass, entry, async_add_entities):
    """Set up the Room and Floor Setpoint sliders."""
    async_add_entities([RoomSetpointNumber(entry), FloorSetpointNumber(entry)])

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

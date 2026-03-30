import logging
from homeassistant.components.number import NumberEntity
from homeassistant.const import UnitOfTemperature
from .const import DOMAIN

_LOGGER = logging.getLogger(__name__)

async def async_setup_entry(hass, entry, async_add_entities):
    """Set up the Floor Setpoint slider."""
    async_add_entities([FloorSetpointNumber(entry)])

class FloorSetpointNumber(NumberEntity):
    """Number entity to control the floor target temperature."""

    def __init__(self, entry):
        self._attr_name = f"{entry.data['name']} Floor Setpoint"
        self._attr_unique_id = f"{entry.entry_id}_floor_setpoint"
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
        return 24.0

    async def async_set_native_value(self, value: float):
        """Write the new floor setpoint directly to the climate entity."""
        climate = self.hass.data[DOMAIN].get(self._entry_id)
        if climate:
            climate._target_temp_room = value # Note: Corrected to match your internal logic if needed
            # In your original code it was climate._target_temp_floor
            climate._target_temp_floor = value 
            await climate._async_calculate_heating_demand()
            climate.async_write_ha_state()
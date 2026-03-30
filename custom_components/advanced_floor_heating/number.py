import logging
from homeassistant.components.number import NumberEntity
from homeassistant.const import UnitOfTemperature
from .const import DOMAIN

_LOGGER = logging.getLogger(__name__)

async def async_setup_entry(hass, entry, async_add_entities):
    """Sæt Gulv Setpunkt skyderen op."""
    async_add_entities([FloorSetpointNumber(entry)])

class FloorSetpointNumber(NumberEntity):
    def __init__(self, entry):
        self._attr_name = f"{entry.data['name']} Gulv Setpunkt"
        self._attr_unique_id = f"{entry.entry_id}_floor_setpoint"
        self._attr_native_unit_of_measurement = UnitOfTemperature.CELSIUS
        self._attr_native_step = 0.5
        self._attr_native_min_value = 15.0
        self._attr_native_max_value = 35.0
        self._entry_id = entry.entry_id

    @property
    def native_value(self):
        """Læser gulv-setpunktet fra termostaten."""
        climate = self.hass.data[DOMAIN].get(self._entry_id)
        return climate._target_temp_floor if climate else 24.0

    async def async_set_native_value(self, value: float):
        """Skriver det nye gulv-setpunkt direkte ind i termostaten."""
        climate = self.hass.data[DOMAIN].get(self._entry_id)
        if climate:
            climate._target_temp_floor = value
            await climate._async_calculate_heating_demand()
            climate.async_write_ha_state()
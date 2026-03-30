"""Sensor platform for Advanced Floor Heating."""
import logging
from homeassistant.components.sensor import SensorEntity
from homeassistant.const import PERCENTAGE
from .const import DOMAIN

_LOGGER = logging.getLogger(__name__)

async def async_setup_entry(hass, entry, async_add_entities):
    """Set up both sensors (PID and Status)."""
    async_add_entities([
        PIDSignalSensor(entry),
        RegulationStatusSensor(entry)
    ])

class PIDSignalSensor(SensorEntity):
    """Sensor to track the PID output signal."""
    
    def __init__(self, entry):
        self._attr_name = f"{entry.data['name']} PID Signal"
        self._attr_unique_id = f"{entry.entry_id}_pid_signal"
        self._attr_native_unit_of_measurement = PERCENTAGE
        self._entry_id = entry.entry_id

    @property
    def native_value(self):
        """Read the PID value directly from the climate entity."""
        try:
            climate_entity = self.hass.data[DOMAIN].get(self._entry_id)
            if climate_entity:
                return climate_entity.pid_signal
        except Exception:
            _LOGGER.error("Could not read PID signal from climate entity")
        return 0

class RegulationStatusSensor(SensorEntity):
    """Sensor to track the current regulation status text."""
    
    def __init__(self, entry):
        self._attr_name = f"{entry.data['name']} Regulation Status"
        self._attr_unique_id = f"{entry.entry_id}_regulation_status"
        self._attr_icon = "mdi:brain"
        self._entry_id = entry.entry_id

    @property
    def native_value(self):
        """Read the status text directly from the climate entity."""
        try:
            climate_entity = self.hass.data[DOMAIN].get(self._entry_id)
            if climate_entity:
                return climate_entity.regulation_status
        except Exception:
            _LOGGER.error("Could not read regulation status from climate entity")
        return "Unknown"
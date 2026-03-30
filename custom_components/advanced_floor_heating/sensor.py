import logging
from homeassistant.components.sensor import SensorEntity
from homeassistant.const import PERCENTAGE
from .const import DOMAIN

_LOGGER = logging.getLogger(__name__)

async def async_setup_entry(hass, entry, async_add_entities):
    """Sæt begge sensorer op (PID og Status)."""
    async_add_entities([
        PIDSignalSensor(entry),
        RegulationStatusSensor(entry) # NY SENSOR HER
    ])

class PIDSignalSensor(SensorEntity):
    def __init__(self, entry):
        self._attr_name = f"{entry.data['name']} PID Signal"
        self._attr_unique_id = f"{entry.entry_id}_pid_signal"
        self._attr_native_unit_of_measurement = PERCENTAGE
        self._entry_id = entry.entry_id

    @property
    def native_value(self):
        """Læser PID værdien direkte fra termostaten."""
        try:
            climate_entity = self.hass.data[DOMAIN].get(self._entry_id)
            if climate_entity:
                return climate_entity.pid_signal
        except Exception:
            pass
        return 0

class RegulationStatusSensor(SensorEntity):
    def __init__(self, entry):
        self._attr_name = f"{entry.data['name']} Reguleringsstatus"
        self._attr_unique_id = f"{entry.entry_id}_regulation_status"
        self._attr_icon = "mdi:brain" # Giver et lille hjerne-ikon
        self._entry_id = entry.entry_id

    @property
    def native_value(self):
        """Læser status-teksten direkte fra termostaten."""
        try:
            climate_entity = self.hass.data[DOMAIN].get(self._entry_id)
            if climate_entity:
                return climate_entity.regulation_status
        except Exception:
            pass
        return "Ukendt"
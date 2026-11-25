"""Sensor platform for Advanced Floor Heating."""
import logging
from homeassistant.components.sensor import SensorEntity, SensorDeviceClass, SensorStateClass
from homeassistant.const import PERCENTAGE, UnitOfTime
from homeassistant.const import UnitOfTemperature
from homeassistant.helpers.dispatcher import async_dispatcher_connect
from .const import DOMAIN, MASTER_KEY, CONF_ENTRY_TYPE, TYPE_MASTER
from .helpers import UpdateListenerMixin, device_info, MASTER_SIGNAL, MASTER_VALUES_SIGNAL

_LOGGER = logging.getLogger(__name__)

async def async_setup_entry(hass, entry, async_add_entities):
    """Set up the room sensors (PID, Status, runtime today) - or the Master's outdoor/sun sensors."""
    if entry.data.get(CONF_ENTRY_TYPE) == TYPE_MASTER:
        async_add_entities([MasterOutdoorSensor(entry), MasterSolarSensor(entry)])
        return
    async_add_entities([
        PIDSignalSensor(entry),
        RegulationStatusSensor(entry),
        RuntimeTodaySensor(entry),
    ])


class _MasterValueSensor(SensorEntity):
    """Fælles for Masterens sensorer: opdateres jævnligt og når kilden/prognosen ændres."""

    _attr_should_poll = True

    def __init__(self, entry, label, uid):
        self._attr_name = f"{entry.data['name']} {label}"
        self._attr_unique_id = f"{entry.entry_id}_{uid}"
        self._attr_device_info = device_info(entry)

    @property
    def _hub(self):
        return self.hass.data[DOMAIN].get(MASTER_KEY)

    async def async_added_to_hass(self):
        for sig in (MASTER_SIGNAL, MASTER_VALUES_SIGNAL):
            self.async_on_remove(async_dispatcher_connect(self.hass, sig, self.async_write_ha_state))


class MasterOutdoorSensor(_MasterValueSensor):
    """Den ude-temperatur rummene bruger (efter den valgte kilde)."""

    _attr_device_class = SensorDeviceClass.TEMPERATURE
    _attr_native_unit_of_measurement = UnitOfTemperature.CELSIUS
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_suggested_display_precision = 1

    def __init__(self, entry):
        super().__init__(entry, "Ude Temperatur (brugt)", "outdoor_used")

    @property
    def native_value(self):
        hub = self._hub
        value = hub.outdoor_temp() if hub else None
        return round(value, 1) if value is not None else None

    @property
    def extra_state_attributes(self):
        hub = self._hub
        if not hub:
            return {}
        measured, forecast = hub.measured_temp(), hub.forecast_temp_now()
        return {
            "kilde": hub.source,
            "maaling": round(measured, 1) if measured is not None else None,
            "prognose": round(forecast, 1) if forecast is not None else None,
            "prognose_timer": hub.forecast_hours,
            "prognose_type": hub.forecast_type,
            "prognose_hentet": hub.forecast_at.isoformat() if hub.forecast_at else None,
        }


class MasterSolarSensor(_MasterValueSensor):
    """Sol 0-100 % (solhøjde x klar himmel) - bruges af rummenes sol-fradrag (ks)."""

    _attr_native_unit_of_measurement = PERCENTAGE
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_icon = "mdi:white-balance-sunny"

    def __init__(self, entry):
        super().__init__(entry, "Sol", "solar")

    @property
    def native_value(self):
        hub = self._hub
        return round(hub.solar() * 100) if hub else None

    @property
    def extra_state_attributes(self):
        hub = self._hub
        if not hub:
            return {}
        cloud = hub.cloud_cover()
        return {
            "solhoejde": hub.sun_elevation(),
            "skydaekke": round(cloud) if cloud is not None else None,
        }


class RuntimeTodaySensor(UpdateListenerMixin, SensorEntity):
    """Hvor mange timer ventilen har været åben i dag (nulstilles ved midnat)."""

    _attr_device_class = SensorDeviceClass.DURATION
    _attr_native_unit_of_measurement = UnitOfTime.HOURS
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_icon = "mdi:timer-outline"
    _attr_suggested_display_precision = 1

    def __init__(self, entry):
        self._attr_name = f"{entry.data['name']} Driftstid i dag"
        self._attr_unique_id = f"{entry.entry_id}_runtime_today"
        self._attr_device_info = device_info(entry)
        self._entry_id = entry.entry_id

    @property
    def native_value(self):
        climate = self.hass.data[DOMAIN].get(self._entry_id)
        return climate.runtime_today_hours if climate else None

class PIDSignalSensor(UpdateListenerMixin, SensorEntity):
    """Sensor to track the PID output signal."""

    def __init__(self, entry):
        self._attr_name = f"{entry.data['name']} PID Signal"
        self._attr_unique_id = f"{entry.entry_id}_pid_signal"
        self._attr_device_info = device_info(entry)
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

class RegulationStatusSensor(UpdateListenerMixin, SensorEntity):
    """Sensor to track the current regulation status text."""

    def __init__(self, entry):
        self._attr_name = f"{entry.data['name']} Reguleringsstatus"
        self._attr_unique_id = f"{entry.entry_id}_regulation_status"
        self._attr_device_info = device_info(entry)
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
        return "Ukendt"

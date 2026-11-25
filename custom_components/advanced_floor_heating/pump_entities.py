"""Entiteter for en Pumpegruppe (pumpestyring og shunt-råd)."""
from homeassistant.components.binary_sensor import BinarySensorEntity
from homeassistant.components.button import ButtonEntity
from homeassistant.components.sensor import SensorEntity, SensorDeviceClass, SensorStateClass
from homeassistant.components.switch import SwitchEntity
from homeassistant.const import PERCENTAGE, UnitOfTemperature
from homeassistant.helpers.dispatcher import async_dispatcher_connect
from homeassistant.helpers.restore_state import RestoreEntity

from .const import DOMAIN, ADVICE_UP_HOURS, ADVICE_DOWN_HOURS
from .helpers import device_info, pump_signal
from .pump import ADVICE_UP, _as_list


class _PumpEntity:
    """Fælles: finder gruppens styring og opdaterer, når den ændrer sig."""

    _attr_should_poll = False

    def __init__(self, entry, label, uid):
        self._entry = entry
        self._entry_id = entry.entry_id
        self._attr_name = f"{entry.data['name']} {label}"
        self._attr_unique_id = f"{entry.entry_id}_{uid}"
        self._attr_device_info = device_info(entry)

    @property
    def ctrl(self):
        return self.hass.data[DOMAIN].get(self._entry_id)

    async def async_added_to_hass(self):
        await super().async_added_to_hass()
        self.async_on_remove(
            async_dispatcher_connect(self.hass, pump_signal(self._entry_id), self.async_write_ha_state)
        )


def pump_binary_sensors(entry):
    out = [PumpDemandBinary(entry)]
    if entry.options.get("pump_feedback", entry.data.get("pump_feedback")):
        out.append(PumpRunningBinary(entry))
    return out


def pump_sensors(entry):
    out = [PumpStatusSensor(entry), ValvesOpenSensor(entry), ShuntAdviceSensor(entry)]
    if entry.options.get("shunt_sensor", entry.data.get("shunt_sensor")):
        out.append(ShuntTempSensor(entry))
    return out


def pump_switches(entry):
    return [PumpEnabledSwitch(entry), ShuntAdviceSwitch(entry)]


def pump_buttons(entry):
    return [PumpMotionButton(entry)]


# --------------------------------------------------------------------- binary sensors

class PumpDemandBinary(_PumpEntity, BinarySensorEntity):
    """Tændt, når mindst én ventil i gruppen er åben (varmekald)."""

    _attr_icon = "mdi:radiator"

    def __init__(self, entry):
        super().__init__(entry, "Varmekald", "demand")

    @property
    def is_on(self):
        return bool(self.ctrl and self.ctrl.demand())


class PumpRunningBinary(_PumpEntity, BinarySensorEntity):
    """Pumpens egen tilbagemelding (fra IHC)."""

    _attr_icon = "mdi:pump"

    def __init__(self, entry):
        super().__init__(entry, "Pumpe kører", "pump_running")

    @property
    def is_on(self):
        return self.ctrl.pump_running() if self.ctrl else None


# ----------------------------------------------------------------------------- sensorer

class PumpStatusSensor(_PumpEntity, SensorEntity):
    """Hvad pumpestyringen gør lige nu."""

    _attr_icon = "mdi:pump"

    def __init__(self, entry):
        super().__init__(entry, "Pumpestatus", "status")

    @property
    def native_value(self):
        return self.ctrl.status() if self.ctrl else None


class ValvesOpenSensor(_PumpEntity, SensorEntity):
    """Hvor åbne gruppens ventiler er i gennemsnit (middel af rummenes udgang)."""

    _attr_native_unit_of_measurement = PERCENTAGE
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_icon = "mdi:valve"

    def __init__(self, entry):
        super().__init__(entry, "Ventiler åbne", "valves_open")

    @property
    def native_value(self):
        return self.ctrl.mean_output if self.ctrl else None

    @property
    def extra_state_attributes(self):
        return {"rum_der_regulerer": self.ctrl.rooms_regulating if self.ctrl else None}


class ShuntAdviceSensor(_PumpEntity, SensorEntity):
    """Råd til shuntens termostat: OK, Skru op eller Skru ned."""

    _attr_icon = "mdi:tune-vertical"

    def __init__(self, entry):
        super().__init__(entry, "Shunt Råd", "shunt_advice")

    @property
    def native_value(self):
        c = self.ctrl
        if not c:
            return None
        if c.advice == ADVICE_UP and c.advice_rooms:
            return f"{c.advice} · {', '.join(c.advice_rooms)}"
        return c.advice

    @property
    def extra_state_attributes(self):
        c = self.ctrl
        if not c:
            return {}
        return {
            "raad": c.advice,
            "rum_der_mangler_varme": c.advice_rooms,
            "rum_der_regulerer": c.rooms_regulating,
            "middel_udgang": c.mean_output,
            "besked_efter_timer": ADVICE_UP_HOURS if c.advice == ADVICE_UP else ADVICE_DOWN_HOURS,
        }


class ShuntTempSensor(_PumpEntity, SensorEntity):
    """Shuntens fremløbstemperatur (kopi af den valgte føler)."""

    _attr_device_class = SensorDeviceClass.TEMPERATURE
    _attr_native_unit_of_measurement = UnitOfTemperature.CELSIUS
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_suggested_display_precision = 1

    def __init__(self, entry):
        super().__init__(entry, "Shunt Fremløb", "shunt_temp")

    @property
    def native_value(self):
        c = self.ctrl
        sensor = c.shunt_sensor if c else None
        state = self.hass.states.get(sensor) if sensor else None
        try:
            return round(float(state.state), 1) if state is not None else None
        except (TypeError, ValueError):
            return None


# ----------------------------------------------------------------------------- kontakter

class _RestoredSwitch(_PumpEntity, RestoreEntity, SwitchEntity):
    _flag = "enabled"

    async def async_added_to_hass(self):
        await super().async_added_to_hass()
        last = await self.async_get_last_state()
        if last is not None and last.state in ("on", "off") and self.ctrl:
            await self._set(last.state == "on", notify=False)

    @property
    def is_on(self):
        return bool(self.ctrl and getattr(self.ctrl, self._flag))

    async def async_turn_on(self, **kwargs):
        await self._set(True)

    async def async_turn_off(self, **kwargs):
        await self._set(False)


class PumpEnabledSwitch(_RestoredSwitch):
    """Slår pumpestyringen til/fra (fra = HA rører ikke pumpens kontakter)."""

    _flag = "enabled"
    _attr_icon = "mdi:pump"

    def __init__(self, entry):
        super().__init__(entry, "Pumpestyring aktiv", "pump_enabled")

    async def _set(self, on, notify=True):
        if notify:
            await self.ctrl.async_set_enabled(on)
        else:
            self.ctrl.enabled = on


class ShuntAdviceSwitch(_RestoredSwitch):
    """Slår shunt-beskederne til/fra."""

    _flag = "advice_enabled"
    _attr_icon = "mdi:bell-ring"

    def __init__(self, entry):
        super().__init__(entry, "Shunt-alarm aktiv", "advice_enabled")

    async def _set(self, on, notify=True):
        self.ctrl.advice_enabled = on
        if notify:
            self.ctrl.publish()


# ------------------------------------------------------------------------------- knapper

class PumpMotionButton(_PumpEntity, ButtonEntity):
    """Kør pumpen i 5 minutter nu (motion)."""

    _attr_icon = "mdi:pump"

    def __init__(self, entry):
        super().__init__(entry, "Pumpemotion nu", "pump_motion")

    async def async_press(self):
        if self.ctrl:
            await self.ctrl.async_run_motion(force=True)

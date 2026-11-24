import logging
import asyncio
import voluptuous as vol
from homeassistant.components.climate import (
    ClimateEntity, HVACMode, ClimateEntityFeature
)
from homeassistant.const import UnitOfTemperature, STATE_ON, STATE_UNAVAILABLE, STATE_UNKNOWN
from homeassistant.helpers.restore_state import RestoreEntity
from homeassistant.helpers import entity_platform
from homeassistant.helpers.dispatcher import async_dispatcher_send
from homeassistant.helpers.event import async_track_state_change_event
from .const import (
    DOMAIN, CONF_ROOM_SENSOR, CONF_FLOOR_SENSOR, CONF_HEATER_SWITCH,
    CONF_WINDOW_SENSOR, CONF_MAX_FLOOR_TEMP, DEFAULT_MAX_FLOOR_TEMP,
    PRESET_ROOM_ONLY, PRESET_FLOOR_ONLY, PRESET_BOTH_1_MET, PRESET_BOTH_BOTH_MET,
)
from .helpers import device_info, update_signal

_LOGGER = logging.getLogger(__name__)


def _option(entry, key, default=None):
    """Read a setting: options (set in the UI later) win over the initial config data."""
    if key in entry.options:
        return entry.options[key]
    return entry.data.get(key, default)


async def async_setup_entry(hass, entry, async_add_entities):
    """Set up the climate component from a config entry."""
    entity = AdvancedFloorHeatingEntity(hass, entry)
    hass.data[DOMAIN][entry.entry_id] = entity
    async_add_entities([entity])

    # --- REGISTER CUSTOM SERVICES FOR THE FRONTEND CARD ---
    platform = entity_platform.async_get_current_platform()

    platform.async_register_entity_service(
        "set_room_temperature",
        {vol.Required("temperature"): vol.Coerce(float)},
        "async_set_room_temperature",
    )

    platform.async_register_entity_service(
        "set_floor_temperature",
        {vol.Required("temperature"): vol.Coerce(float)},
        "async_set_floor_temperature",
    )


class AdvancedFloorHeatingEntity(ClimateEntity, RestoreEntity):
    def __init__(self, hass, entry):
        self.hass = hass
        self._entry_id = entry.entry_id
        self._attr_name = entry.data["name"]
        self._attr_unique_id = f"{entry.entry_id}_climate"
        self._attr_device_info = device_info(entry)
        self._room_sensor = entry.data[CONF_ROOM_SENSOR]
        self._floor_sensor = entry.data[CONF_FLOOR_SENSOR]
        self._heater_switch = entry.data[CONF_HEATER_SWITCH]
        # Optional: binary_sensor of the window(s) in this room
        self._window_sensor = _option(entry, CONF_WINDOW_SENSOR) or None

        # Read settings from config options
        self._kp = float(entry.options.get("kp", 10.0))
        self._ki = float(entry.options.get("ki", 2.0))
        self._kd = float(entry.options.get("kd", 1.0))
        self._pid_interval = int(entry.options.get("pid_interval", 30))
        self._cycle_time = int(entry.options.get("cycle_time", 30))

        # Internal time constants
        self._i_time = 9000.0
        self._d_time = 2580.0

        # Target temperatures and safety limits
        self._target_temp_room = 21.0
        self._target_temp_floor = 24.0
        self._max_floor_temp = float(
            _option(entry, CONF_MAX_FLOOR_TEMP, DEFAULT_MAX_FLOOR_TEMP)
        )

        # PID internal state
        self._pid_signal = 0.0
        self._integral_sum = 0.0
        self._last_error = 0.0
        self._regulation_status = "Initialiserer..."
        self._frozen = False  # True while the output is held because a window is open

        self._p_out = 0.0
        self._i_out = 0.0
        self._d_out = 0.0
        self._current_error = 0.0

        self._tasks = []

        self._attr_temperature_unit = UnitOfTemperature.CELSIUS
        self._attr_supported_features = (
            ClimateEntityFeature.TARGET_TEMPERATURE |
            ClimateEntityFeature.PRESET_MODE |
            getattr(ClimateEntityFeature, "TURN_ON", 0) |
            getattr(ClimateEntityFeature, "TURN_OFF", 0)
        )

        # Preset modes
        self._attr_preset_modes = [
            PRESET_ROOM_ONLY,
            PRESET_FLOOR_ONLY,
            PRESET_BOTH_1_MET,
            PRESET_BOTH_BOTH_MET,
        ]
        self._attr_preset_mode = PRESET_BOTH_BOTH_MET
        self._attr_hvac_mode = HVACMode.HEAT
        self._attr_hvac_modes = [HVACMode.HEAT, HVACMode.OFF]

    # ------------------------------------------------------------------ helpers

    def _read_temp(self, entity_id):
        """Return the sensor value as float, or None if missing / not a number."""
        state = self.hass.states.get(entity_id)
        if state is None or state.state in (STATE_UNAVAILABLE, STATE_UNKNOWN):
            return None
        try:
            return float(state.state)
        except (TypeError, ValueError):
            return None

    @property
    def window_open(self):
        """True if a window sensor is configured and reports 'on'.

        A missing/unavailable window sensor counts as closed, so a broken sensor
        can never keep the heating frozen forever.
        """
        if not self._window_sensor:
            return False
        state = self.hass.states.get(self._window_sensor)
        return state is not None and state.state == STATE_ON

    def _publish(self):
        """Write own state and tell the sensor/number entities of this room to refresh."""
        self.async_write_ha_state()
        async_dispatcher_send(self.hass, update_signal(self._entry_id))

    # ---------------------------------------------------------------- lifecycle

    async def async_added_to_hass(self):
        """Restore state and start background loops."""
        await super().async_added_to_hass()

        last_state = await self.async_get_last_state()

        if last_state is not None:
            if last_state.state in self.hvac_modes:
                self._attr_hvac_mode = last_state.state

            preset = last_state.attributes.get("preset_mode")
            if preset in self._attr_preset_modes:
                self._attr_preset_mode = preset

            if "room_target_temperature" in last_state.attributes:
                self._target_temp_room = float(last_state.attributes["room_target_temperature"])

            if "floor_target_temperature" in last_state.attributes:
                self._target_temp_floor = float(last_state.attributes["floor_target_temperature"])

            if "pid_i" in last_state.attributes:
                self._i_out = float(last_state.attributes["pid_i"])
                if self._ki > 0:
                    self._integral_sum = self._i_out / self._ki

            if "pid_e" in last_state.attributes:
                self._current_error = float(last_state.attributes["pid_e"])
                self._last_error = self._current_error

            # Restore the output too, so a window that is open during a restart
            # keeps the output at the value it had before.
            if "control_output" in last_state.attributes:
                self._pid_signal = max(0.0, min(100.0, float(last_state.attributes["control_output"])))

        # React immediately when the window opens or closes
        if self._window_sensor:
            self.async_on_remove(
                async_track_state_change_event(
                    self.hass, [self._window_sensor], self._async_window_changed
                )
            )

        # Start the "Brain" and the "Muscle" tasks
        self._tasks = [
            self.hass.async_create_background_task(self._async_pid_loop(), name=f"PID_Brain_{self.entity_id}"),
            self.hass.async_create_background_task(self._async_pwm_loop(), name=f"PWM_Muscle_{self.entity_id}"),
        ]

    async def async_will_remove_from_hass(self):
        """Stop the loops (otherwise a reload leaves old loops fighting over the switch)."""
        for task in self._tasks:
            task.cancel()
        self._tasks = []
        try:
            await self.hass.services.async_call("switch", "turn_off", {"entity_id": self._heater_switch})
        except Exception:  # noqa: BLE001 - never block unload because the switch is gone
            _LOGGER.debug("Could not turn off %s while unloading", self._heater_switch)

    async def _async_window_changed(self, event):
        await self._async_calculate_heating_demand()

    # --------------------------------------------------------------- properties

    @property
    def pid_signal(self):
        return round(self._pid_signal, 2)

    @property
    def regulation_status(self):
        return self._regulation_status

    @property
    def extra_state_attributes(self):
        """Expose internal PID data for the frontend card."""
        curr_room = self._read_temp(self._room_sensor)
        curr_floor = self._read_temp(self._floor_sensor)

        return {
            "regulation_status": self._regulation_status,
            "room_temperature": curr_room,
            "room_target_temperature": self._target_temp_room,
            "floor_temperature": curr_floor,
            "floor_target_temperature": self._target_temp_floor,
            "max_floor_temperature": self._max_floor_temp,
            "window_sensor": self._window_sensor,
            "window_open": self.window_open,
            "output_frozen": self._frozen,
            "control_output": round(self._pid_signal, 2),
            "kp": self._kp,
            "ki": self._ki,
            "kd": self._kd,
            "pid_p": round(self._p_out, 2),
            "pid_i": round(self._i_out, 2),
            "pid_d": round(self._d_out, 2),
            "pid_e": round(self._current_error, 2),
            "pid_interval": self._pid_interval,
            "pwm_cycle_time": self._cycle_time
        }

    # ------------------------------------------------------------------ control

    async def _async_pid_loop(self):
        """Main loop for PID calculations."""
        while True:
            await self._async_calculate_heating_demand()
            await asyncio.sleep(max(1, self._pid_interval))

    async def _async_calculate_heating_demand(self):
        """The mathematical heart of the integration."""
        if self._attr_hvac_mode == HVACMode.OFF:
            self._pid_signal = 0.0
            self._frozen = False
            self._regulation_status = "Slukket (HVAC OFF)"
            self._publish()
            return

        curr_floor = self._read_temp(self._floor_sensor)
        if curr_floor is None:
            # Without the floor sensor we cannot guarantee the floor limit -> heating off.
            self._pid_signal = 0.0
            self._regulation_status = "Gulvføler mangler (Slukket)"
            self._publish()
            return

        uses_room = self._attr_preset_mode != PRESET_FLOOR_ONLY

        # WINDOW RULE: with an open window the room temperature is meaningless
        # (cold draught), so we must not regulate on it. The output is frozen at
        # its current value until the window is closed again. "Kun Gulv" does not
        # look at the room temperature and therefore keeps regulating normally.
        frozen = uses_room and self.window_open

        if frozen:
            self._frozen = True
            self._regulation_status = f"Vindue åbent - udgang frosset ved {round(self._pid_signal)}%"
        else:
            curr_room = self._read_temp(self._room_sensor) if uses_room else None
            if uses_room and curr_room is None:
                self._pid_signal = 0.0
                self._regulation_status = "Rumføler mangler (Slukket)"
                self._publish()
                return

            self._run_pid(curr_room, curr_floor)

        # Safety stop always wins - also while the output is frozen
        if curr_floor >= self._max_floor_temp:
            self._pid_signal = 0.0
            self._regulation_status = "Sikkerhedsstop (Gulv for varmt!)"
        elif self._pid_signal == 0 and not frozen:
            self._regulation_status = "Mål nået (Slukket)"

        self._publish()

    def _run_pid(self, curr_room, curr_floor):
        """One PID step. Updates _pid_signal and the PID terms."""
        err_f = self._target_temp_floor - curr_floor
        err_r = (self._target_temp_room - curr_room) if curr_room is not None else None

        # Mode Logic
        if self._attr_preset_mode == PRESET_BOTH_BOTH_MET:
            if err_r >= err_f:
                error = err_r
                self._regulation_status = "Rum (Størst behov)"
            else:
                error = err_f
                self._regulation_status = "Gulv (Størst behov)"
        elif self._attr_preset_mode == PRESET_BOTH_1_MET:
            if err_r <= err_f:
                error = err_r
                self._regulation_status = "Rum (Nærmest mål)"
            else:
                error = err_f
                self._regulation_status = "Gulv (Nærmest mål)"
        elif self._attr_preset_mode == PRESET_ROOM_ONLY:
            error = err_r
            self._regulation_status = "Kun Rum"
        else:
            error = err_f
            self._regulation_status = "Kun Gulv"

        # Coming back from a frozen output: forget the old error so the
        # D-term does not give a spike on the first step.
        if self._frozen:
            self._last_error = error
            self._frozen = False

        self._current_error = error
        dt = self._pid_interval

        # P and D calculation
        self._p_out = self._kp * error
        self._d_out = self._kd * ((error - self._last_error) / dt) * self._d_time

        # Integral calculation with Anti-Windup (Clamping)
        i_step = error * (dt / self._i_time)
        test_i_sum = self._integral_sum + i_step
        test_i_out = self._ki * test_i_sum
        test_signal = self._p_out + test_i_out + self._d_out

        if test_signal >= 100.0 and error > 0:
            pass  # Clamp positive
        elif test_signal <= 0.0 and error < 0:
            pass  # Clamp negative
        else:
            self._integral_sum += i_step

        if self._integral_sum < 0.0:
            self._integral_sum = 0.0

        self._i_out = self._ki * self._integral_sum

        # Final PID Signal
        y_signal = self._p_out + self._i_out + self._d_out
        self._pid_signal = max(0.0, min(100.0, y_signal))
        self._last_error = error

    async def _async_pwm_loop(self):
        """Omsætter PID-procent til fysiske tænd/sluk-cyklusser (PWM)."""
        while True:
            cycle = max(1, self._cycle_time)

            # Anti-Micro-Switching: undgå unødvendige klik i relæet
            if self._pid_signal < 1.0:
                on_time = 0
                off_time = cycle
            elif self._pid_signal > 99.0:
                on_time = cycle
                off_time = 0
            else:
                on_time = (self._pid_signal / 100.0) * cycle
                off_time = cycle - on_time

            try:
                if on_time > 0:
                    await self.hass.services.async_call("switch", "turn_on", {"entity_id": self._heater_switch})
                    await asyncio.sleep(on_time)

                if off_time > 0:
                    await self.hass.services.async_call("switch", "turn_off", {"entity_id": self._heater_switch})
                    await asyncio.sleep(off_time)
            except asyncio.CancelledError:
                raise
            except Exception as err:  # noqa: BLE001 - keep the loop alive
                _LOGGER.warning("Could not switch %s: %s", self._heater_switch, err)
                await asyncio.sleep(cycle)

    @property
    def current_temperature(self):
        sensor_id = self._floor_sensor if self._attr_preset_mode == PRESET_FLOOR_ONLY else self._room_sensor
        return self._read_temp(sensor_id)

    @property
    def target_temperature(self):
        if self._attr_preset_mode == PRESET_FLOOR_ONLY:
            return self._target_temp_floor
        return self._target_temp_room

    # --- CUSTOM SERVICES (English) ---
    async def async_set_room_temperature(self, temperature):
        """Sets ONLY the room target temperature."""
        self._target_temp_room = float(temperature)
        await self._async_calculate_heating_demand()

    async def async_set_floor_temperature(self, temperature):
        """Sets ONLY the floor target temperature."""
        self._target_temp_floor = float(temperature)
        await self._async_calculate_heating_demand()

    # Standard fallback command
    async def async_set_temperature(self, **kwargs):
        temp = kwargs.get("temperature")
        if temp is not None:
            if self._attr_preset_mode == PRESET_FLOOR_ONLY:
                self._target_temp_floor = temp
            else:
                self._target_temp_room = temp
            await self._async_calculate_heating_demand()

    async def async_set_preset_mode(self, preset_mode):
        if preset_mode in self._attr_preset_modes:
            self._attr_preset_mode = preset_mode
            await self._async_calculate_heating_demand()

    async def async_set_hvac_mode(self, hvac_mode):
        if hvac_mode in self._attr_hvac_modes:
            self._attr_hvac_mode = hvac_mode
            await self._async_calculate_heating_demand()

    async def async_turn_on(self):
        await self.async_set_hvac_mode(HVACMode.HEAT)

    async def async_turn_off(self):
        await self.async_set_hvac_mode(HVACMode.OFF)

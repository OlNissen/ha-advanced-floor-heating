import logging
import asyncio
import voluptuous as vol
from homeassistant.components.climate import (
    ClimateEntity, HVACMode, ClimateEntityFeature
)
from homeassistant.const import UnitOfTemperature
from homeassistant.helpers.restore_state import RestoreEntity
from homeassistant.helpers import entity_platform
from .const import (
    DOMAIN, CONF_ROOM_SENSOR, CONF_FLOOR_SENSOR, CONF_HEATER_SWITCH, ATTR_PID_SIGNAL
)

_LOGGER = logging.getLogger(__name__)

async def async_setup_entry(hass, entry, async_add_entities):
    """Set up the climate component from a config entry."""
    config = entry.data
    options = entry.options 
    
    entity = AdvancedFloorHeatingEntity(
        hass, 
        entry.entry_id, 
        config["name"], 
        config[CONF_ROOM_SENSOR], 
        config[CONF_FLOOR_SENSOR], 
        config[CONF_HEATER_SWITCH],
        options
    )
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
    def __init__(self, hass, entry_id, name, room_sensor, floor_sensor, heater_switch, options):
        self.hass = hass
        self._attr_name = name
        self._attr_unique_id = f"{entry_id}_climate"
        self._room_sensor = room_sensor
        self._floor_sensor = floor_sensor
        self._heater_switch = heater_switch
        
        # Read settings from config options
        self._kp = float(options.get("kp", 10.0))
        self._ki = float(options.get("ki", 2.0))
        self._kd = float(options.get("kd", 1.0))
        self._pid_interval = int(options.get("pid_interval", 30))
        self._cycle_time = int(options.get("cycle_time", 30))
        
        # Internal time constants
        self._i_time = 9000.0
        self._d_time = 2580.0
        
        # Target temperatures and safety limits
        self._target_temp_room = 21.0
        self._target_temp_floor = 24.0
        self._max_floor_temp = 32.0
        
        # PID internal state
        self._pid_signal = 0.0
        self._integral_sum = 0.0
        self._last_error = 0.0
        self._regulation_status = "Initializing..."
        
        self._p_out = 0.0
        self._i_out = 0.0
        self._d_out = 0.0
        self._current_error = 0.0
        
        self._attr_temperature_unit = UnitOfTemperature.CELSIUS
        self._attr_supported_features = (
            ClimateEntityFeature.TARGET_TEMPERATURE | 
            ClimateEntityFeature.PRESET_MODE
        )
        
        # Translated Preset Modes
        self._attr_preset_modes = [
            "Room Only", 
            "Floor Only", 
            "Room & Floor (1 Met)", 
            "Room & Floor (Both Met)"
        ]
        self._attr_preset_mode = "Room & Floor (Both Met)"
        self._attr_hvac_mode = HVACMode.HEAT
        self._attr_hvac_modes = [HVACMode.HEAT, HVACMode.OFF]

    async def async_added_to_hass(self):
        """Restore state and start background loops."""
        await super().async_added_to_hass()
        
        last_state = await self.async_get_last_state()
        
        if last_state is not None:
            if last_state.state in self.hvac_modes:
                self._attr_hvac_mode = last_state.state

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

        # Start the "Brain" and the "Muscle" tasks
        self.hass.async_create_background_task(self._async_pid_loop(), name=f"PID_Brain_{self.entity_id}")
        self.hass.async_create_background_task(self._async_pwm_loop(), name=f"PWM_Muscle_{self.entity_id}")

    @property
    def pid_signal(self):
        return round(self._pid_signal, 2)

    @property
    def regulation_status(self):
        return self._regulation_status

    @property
    def extra_state_attributes(self):
        """Expose internal PID data for the frontend card."""
        room_st = self.hass.states.get(self._room_sensor)
        floor_st = self.hass.states.get(self._floor_sensor)
        
        curr_room = float(room_st.state) if room_st and room_st.state not in ["unavailable", "unknown"] else 0.0
        curr_floor = float(floor_st.state) if floor_st and floor_st.state not in ["unavailable", "unknown"] else 0.0

        return {
            "regulation_status": self._regulation_status,
            "room_temperature": curr_room,
            "room_target_temperature": self._target_temp_room,
            "floor_temperature": curr_floor,
            "floor_target_temperature": self._target_temp_floor,
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

    async def _async_pid_loop(self):
        """Main loop for PID calculations."""
        while True:
            if self._attr_hvac_mode == HVACMode.OFF:
                self._pid_signal = 0.0
                self._regulation_status = "Off (HVAC OFF)"
                self.async_write_ha_state()
            else:
                await self._async_calculate_heating_demand()
            
            interval = max(1, self._pid_interval)
            await asyncio.sleep(interval)

    async def _async_calculate_heating_demand(self):
        """The mathematical heart of the integration."""
        room_st = self.hass.states.get(self._room_sensor)
        floor_st = self.hass.states.get(self._floor_sensor)
        
        if not room_st or not floor_st or room_st.state in ["unavailable", "unknown"]:
            self._regulation_status = "Waiting for sensor data..."
            return

        curr_room = float(room_st.state)
        curr_floor = float(floor_st.state)
        
        err_r = self._target_temp_room - curr_room
        err_f = self._target_temp_floor - curr_floor
        
        # Mode Logic
        if self._attr_preset_mode == "Room & Floor (Both Met)":
            if err_r >= err_f:
                error = err_r
                self._regulation_status = "Room (Highest demand)"
            else:
                error = err_f
                self._regulation_status = "Floor (Highest demand)"
        elif self._attr_preset_mode == "Room & Floor (1 Met)":
            if err_r <= err_f:
                error = err_r
                self._regulation_status = "Room (Closest to target)"
            else:
                error = err_f
                self._regulation_status = "Floor (Closest to target)"
        elif self._attr_preset_mode == "Room Only":
            error = err_r
            self._regulation_status = "Room Only"
        else:
            error = err_f
            self._regulation_status = "Floor Only"

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

        # Safety and Zero-output check
        if curr_floor >= self._max_floor_temp:
            self._pid_signal = 0
            self._regulation_status = "Safety stop (Floor too hot!)"
        elif self._pid_signal == 0:
            self._regulation_status = "Target reached (Off)"

        self.async_write_ha_state()

    async def _async_pwm_loop(self):
        """Converts PID percentage to physical switch cycles."""
        while True:
            cycle = max(1, self._cycle_time) 
            
            on_time = (self._pid_signal / 100.0) * cycle
            off_time = cycle - on_time

            if on_time > 0:
                await self.hass.services.async_call("switch", "turn_on", {"entity_id": self._heater_switch})
                await asyncio.sleep(on_time)
            
            if off_time > 0:
                await self.hass.services.async_call("switch", "turn_off", {"entity_id": self._heater_switch})
                await asyncio.sleep(off_time)

    @property
    def current_temperature(self):
        sensor_id = self._floor_sensor if self._attr_preset_mode == "Floor Only" else self._room_sensor
        state = self.hass.states.get(sensor_id)
        if state and state.state not in ["unavailable", "unknown"]:
            return float(state.state)
        return None

    @property
    def target_temperature(self):
        if self._attr_preset_mode == "Floor Only":
            return self._target_temp_floor
        return self._target_temp_room

    # --- CUSTOM SERVICES (English) ---
    async def async_set_room_temperature(self, temperature):
        """Sets ONLY the room target temperature."""
        self._target_temp_room = float(temperature)
        await self._async_calculate_heating_demand()
        self.async_write_ha_state()

    async def async_set_floor_temperature(self, temperature):
        """Sets ONLY the floor target temperature."""
        self._target_temp_floor = float(temperature)
        await self._async_calculate_heating_demand()
        self.async_write_ha_state()

    # Standard fallback command
    async def async_set_temperature(self, **kwargs):
        temp = kwargs.get("temperature")
        if temp is not None:
            if self._attr_preset_mode == "Floor Only":
                self._target_temp_floor = temp
            else:
                self._target_temp_room = temp
            await self._async_calculate_heating_demand()
            self.async_write_ha_state()

    async def async_set_preset_mode(self, preset_mode):
        if preset_mode in self._attr_preset_modes:
            self._attr_preset_mode = preset_mode
            await self._async_calculate_heating_demand()
            self.async_write_ha_state()
            
    async def async_set_hvac_mode(self, hvac_mode):
        if hvac_mode in self._attr_hvac_modes:
            self._attr_hvac_mode = hvac_mode
            self.async_write_ha_state()
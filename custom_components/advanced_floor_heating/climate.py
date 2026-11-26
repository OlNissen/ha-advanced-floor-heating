import logging
import asyncio
import time
import voluptuous as vol
from homeassistant.components.climate import (
    ClimateEntity, HVACMode, ClimateEntityFeature
)
from homeassistant.const import UnitOfTemperature, STATE_ON, STATE_UNAVAILABLE, STATE_UNKNOWN
from homeassistant.helpers.restore_state import RestoreEntity
from homeassistant.helpers import entity_platform
from homeassistant.helpers.dispatcher import async_dispatcher_send, async_dispatcher_connect
from homeassistant.util import dt as dt_util
from homeassistant.helpers.event import async_track_state_change_event
from .const import (
    DOMAIN, CONF_ROOM_SENSOR, CONF_FLOOR_SENSOR, CONF_HEATER_SWITCH,
    CONF_WINDOW_SENSOR, CONF_MAX_FLOOR_TEMP, DEFAULT_MAX_FLOOR_TEMP,
    CONF_VALVE_EXERCISE_DAYS, DEFAULT_VALVE_EXERCISE_DAYS,
    VALVE_EXERCISE_CYCLES, VALVE_EXERCISE_PHASE_SECONDS,
    PRESET_ROOM_ONLY, PRESET_FLOOR_ONLY, PRESET_BOTH_1_MET, PRESET_BOTH_BOTH_MET,
    MODE_OCCUPIED, MODE_UNOCCUPIED, MODE_FROST, MODE_OFF, MODE_FOLLOW, ROOM_MODE_OPTIONS,
    DEFAULT_UNOCCUPIED_TEMP, DEFAULT_FROST_TEMP,
    CONF_OUTDOOR_KE, CONF_STALE_HOURS, DEFAULT_STALE_HOURS, CONF_SOLAR_GAIN,
    CONF_LINKED_ROOMS, CONF_LINK_WEIGHT, DEFAULT_LINK_WEIGHT, CONF_PUMP_GROUP, CONF_ROOM_PUMP_SWITCH,
    STUCK_VALVE_MINUTES, STUCK_VALVE_MIN_RISE, SENSOR_ALARM_MINUTES, SUPPLY_MARGIN,
    VERIFY_DELAY_SECONDS, VERIFY_RETRIES, CONF_SUMMER_APPLIES, STATUS_SUMMER,
    CONF_HUMIDITY_SENSOR, THERMAL_SAVE_DELAY, FLOOR_LIMIT_MARGIN, STATUS_FLOOR_LIMIT, CONF_BACKUP_SENSOR,
    MOLD_CLEAR_RH, MOLD_ALARM_RH, CONF_SILENT_HOURS, DEFAULT_SILENT_HOURS,
)
from homeassistant.helpers.storage import Store
from .health import (
    find_battery_entities, find_sibling_temperature, find_device_entities, silent_seconds,
    battery_low, surface_humidity, MoldWatch,
)
from .thermal import ThermalModel
from .helpers import device_info, update_signal, MASTER_SIGNAL, ALARM_SIGNAL
from .master import get_master
from .review import RoomMetrics
from .notify import notify
from .const import REVIEW_KEY
from .autotune import RelayAutoTuner, RULES, DEFAULT_RULE

_LOGGER = logging.getLogger(__name__)

# HA 2026.11 omdøbte klima-entitetens temperaturfelter til native_*. De gamle navne virker ikke fra 2027.11,
# og ældre HA kender kun dem. Derfor defineres de gamle kun, når HA ikke har de nye.
_NATIVE_TEMPERATURE = hasattr(ClimateEntity, "native_current_temperature")


def _as_list(value):
    """Gammel opsætning gemte én kontakt som tekst - nu er det en liste."""
    if not value:
        return []
    if isinstance(value, str):
        return [value]
    return [v for v in value if v]


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

    # --- AUTOTUNE AF PID ---
    platform.async_register_entity_service(
        "start_autotune",
        {
            vol.Optional("target"): vol.In(["room", "floor"]),
            vol.Optional("output_step", default=30): vol.All(vol.Coerce(float), vol.Range(min=5, max=50)),
            vol.Optional("noiseband", default=0.2): vol.All(vol.Coerce(float), vol.Range(min=0.05, max=2)),
            vol.Optional("rule", default=DEFAULT_RULE): vol.In(list(RULES)),
            vol.Optional("max_hours", default=24): vol.All(vol.Coerce(float), vol.Range(min=1, max=72)),
        },
        "async_start_autotune",
    )
    platform.async_register_entity_service("stop_autotune", {}, "async_stop_autotune")
    platform.async_register_entity_service("apply_autotune", {}, "async_apply_autotune")


class AdvancedFloorHeatingEntity(ClimateEntity, RestoreEntity):
    def __init__(self, hass, entry):
        self.hass = hass
        self._entry = entry
        self._entry_id = entry.entry_id
        self._attr_name = entry.data["name"]
        self._attr_unique_id = f"{entry.entry_id}_climate"
        self._attr_device_info = device_info(entry)
        self._room_sensor = entry.data.get(CONF_ROOM_SENSOR) or None   # None: rum uden rumføler
        self._floor_sensor = entry.data[CONF_FLOOR_SENSOR]
        self._heater_switch = entry.data[CONF_HEATER_SWITCH]
        # Optional: binary_sensor of the window(s) in this room
        # Optional: ét eller flere vindues-/dørkontakter (binary_sensor) i rummet
        self._window_sensors = _as_list(_option(entry, CONF_WINDOW_SENSOR))

        # Read settings from config options
        self._kp = float(entry.options.get("kp", 10.0))
        self._ki = float(entry.options.get("ki", 2.0))
        self._kd = float(entry.options.get("kd", 1.0))
        self._pid_interval = int(entry.options.get("pid_interval", 30))
        self._cycle_time = int(entry.options.get("cycle_time", 30))

        # Ventilmotion (mod fastsiddende ventiler)
        self._exercise_days = float(
            _option(entry, CONF_VALVE_EXERCISE_DAYS, DEFAULT_VALVE_EXERCISE_DAYS) or 0
        )
        self._last_valve_on = time.time()  # sidste gang ventilen var åben (epoch); genindlæses ved genstart
        self._exercise_start = None        # monotonic-tid hvor en igangværende motion startede

        # Husets tilstand: rummet foelger Masteren, medmindre det har sin egen tilstand
        self._mode_override = MODE_FOLLOW
        self._reset_d = False  # naeste PID-skridt glemmer gammel fejl (ingen D-spike efter tilstandsskift)

        # Udekompensation (ke = 0 -> slaaet fra) og gamle foelere
        self._ke = float(_option(entry, CONF_OUTDOOR_KE, 0.0) or 0.0)
        self._stale_hours = float(_option(entry, CONF_STALE_HOURS, DEFAULT_STALE_HOURS) or 0.0)
        self._ks = float(_option(entry, CONF_SOLAR_GAIN, 0.0) or 0.0)  # sol-fradrag (% udgang ved fuld sol)
        self._ff_out = 0.0

        # Koblede rum (samme luftrum, hver sin shunt/gulv): fælles rumtemperatur som vægtet middel
        self._linked_rooms = _as_list(_option(entry, CONF_LINKED_ROOMS))
        self._link_weight = float(_option(entry, CONF_LINK_WEIGHT, DEFAULT_LINK_WEIGHT) or DEFAULT_LINK_WEIGHT)

        # Pumpe: hvilken gruppe rummet hører til, og kontakten der tænder pumpen for rummet
        self._pump_group = _option(entry, CONF_PUMP_GROUP) or None
        self._pump_switch = _option(entry, CONF_ROOM_PUMP_SWITCH) or None

        # Målinger til gennemgang (udsving m.m.)
        self._metrics = RoomMetrics()

        # Alarmer og driftstid
        self._alarms = []
        self._sensor_bad_since = {}   # entity_id -> monotonic-tid hvor den begyndte at mangle
        self._full_since = None       # monotonic: hvornaar udgangen blev ved >= 90 %
        self._full_floor0 = None      # gulvtemperatur dengang
        self._runtime_s = 0.0         # sekunder med aaben ventil i dag
        self._runtime_date = None     # dato (ISO) for _runtime_s

        # Batteri på følerne og telestat der ikke svarer
        self._battery_entities = {}    # føler -> batteri-entiteter på samme enhed
        self._battery_scanned = None   # monotonic: hvornår der sidst blev ledt efter dem
        self._battery_state = {}       # batteri-entitet -> lavt?
        self._switch_bad_since = None
        self._verify_task = None
        self._verify_want = None
        self._failed_command = None    # "on"/"off", som telestaten ikke fulgte

        # Sommerstop, skimmelrisiko og lært varmemodel
        summer = _option(entry, CONF_SUMMER_APPLIES, True)
        self._summer_applies = True if summer is None else bool(summer)
        self._humidity_sensor = _option(entry, CONF_HUMIDITY_SENSOR) or None
        self._humidity_temp_sensor = None   # temperaturen på fugtfølerens egen enhed
        self._humidity_temp_scanned = None
        # Tavs batteriføler (gælder rum-, reserve- og fugtføler, aldrig gulvføleren)
        silent = _option(entry, CONF_SILENT_HOURS, DEFAULT_SILENT_HOURS)
        self._silent_hours = DEFAULT_SILENT_HOURS if silent is None else float(silent)
        self._device_cache = {}    # føler -> (hvornår slået op, entiteter, har batteri)
        # Reserve-rumføler (giver kun mening, når rummet har en rumføler)
        self._backup_sensor = (_option(entry, CONF_BACKUP_SENSOR) or None) if self._room_sensor else None
        self._mold = MoldWatch()
        self._thermal = ThermalModel()
        self._thermal_source = None    # "rum" eller "gulv": hvad modellen er lært på
        self._thermal_store = None

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
        self._floor_limited = False  # True, mens PID'en regulerer efter gulvgrænsen

        self._p_out = 0.0
        self._i_out = 0.0
        self._d_out = 0.0
        self._current_error = 0.0

        self._tasks = []

        # Autotune
        self._tuner = None
        self._tuner_target = None
        self._tuner_result = None
        self._autotune_msg = None

        if _NATIVE_TEMPERATURE:
            self._attr_native_temperature_unit = UnitOfTemperature.CELSIUS
        else:
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
        if self._room_sensor is None:
            # Uden rumføler kan rummet kun reguleres efter gulvet
            self._attr_preset_modes = [PRESET_FLOOR_ONLY]
            self._attr_preset_mode = PRESET_FLOOR_ONLY
        self._attr_hvac_mode = HVACMode.HEAT
        self._attr_hvac_modes = [HVACMode.HEAT, HVACMode.OFF]

    # ------------------------------------------------------------------ helpers

    def _sensor_problem(self, entity_id):
        """None hvis foeleren er i orden, ellers 'mangler' eller 'gammel'."""
        if not entity_id:
            return "mangler"
        state = self.hass.states.get(entity_id)
        if state is None or state.state in (STATE_UNAVAILABLE, STATE_UNKNOWN):
            return "mangler"
        try:
            float(state.state)
        except (TypeError, ValueError):
            return "mangler"
        if self._stale_hours > 0:
            seen = getattr(state, "last_reported", None) or state.last_updated
            if (dt_util.utcnow() - seen).total_seconds() > self._stale_hours * 3600:
                return "gammel"
        if self._is_silent(entity_id):
            return "tavs"
        return None

    def _is_silent(self, entity_id):
        """True, når en trådløs batteriføler ikke har ændret nogen værdi i `silent_hours` timer."""
        if self._silent_hours <= 0:
            return False
        if entity_id not in (self._room_sensor, getattr(self, "_backup_sensor", None),
                             getattr(self, "_humidity_sensor", None)):
            return False
        now = time.monotonic()
        cached = self._device_cache.get(entity_id)
        if cached is None or now - cached[0] >= 3600:
            entities, battery = find_device_entities(self.hass, entity_id)
            cached = self._device_cache[entity_id] = (now, entities, battery)
        _, entities, battery = cached
        if not battery:
            return False   # kablede følere (fx IHC) melder kun ved ændring og tjekkes ikke
        quiet = silent_seconds([self.hass.states.get(e) for e in entities], dt_util.utcnow())
        return quiet is not None and quiet > self._silent_hours * 3600

    def _read_temp(self, entity_id):
        """Return the sensor value as float, or None if missing / stale / not a number."""
        if self._sensor_problem(entity_id) is not None:
            return None
        return float(self.hass.states.get(entity_id).state)

    # ------------------------------------------------------------- koblede rum

    def _linked_entities(self):
        """De koblede rums regulatorer (kun dem der findes og er indlæst)."""
        wanted = set(self._linked_rooms)
        if not wanted:
            return []
        return [
            obj for obj in self.hass.data.get(DOMAIN, {}).values()
            if obj is not self and getattr(obj, "entity_id", None) in wanted
            and hasattr(obj, "_room_sensor")
        ]

    def _own_room_temp(self):
        """Rummets egen temperatur: rumføleren, ellers reserveføleren."""
        value = self._read_temp(self._room_sensor)
        if value is None and self._backup_sensor:
            value = self._read_temp(self._backup_sensor)
        return value

    @property
    def using_backup(self):
        return bool(
            self._backup_sensor and self._read_temp(self._room_sensor) is None
            and self._read_temp(self._backup_sensor) is not None
        )

    def _control_room_temp(self):
        """Rumtemperaturen regulatoren bruger: eget rum, eller vægtet middel med de koblede rum.

        Mangler en føler, bruges de øvrige. None hvis ingen føler er til rådighed.
        """
        pairs = []
        own = self._own_room_temp()
        if own is not None:
            pairs.append((self._link_weight, own))
        for other in self._linked_entities():
            value = other._own_room_temp()
            if value is not None:
                pairs.append((other._link_weight, value))
        if not pairs:
            return None
        if len(pairs) == 1:
            return pairs[0][1]
        total = sum(w for w, _ in pairs)
        return sum(w * t for w, t in pairs) / total

    async def _async_sync_room_setpoint(self, value):
        """Et koblet rum følger, når rum-setpunktet ændres (gulv-setpunkter er hvert rums egne)."""
        for other in self._linked_entities():
            if other._target_temp_room != value:
                other._target_temp_room = value
                await other._async_calculate_heating_demand()

    # ---------------------------------------------------------- husets tilstand

    @property
    def mode_override(self):
        return self._mode_override

    @property
    def house_mode(self):
        """Den tilstand rummet faktisk holder: egen tilstand, ellers Masterens."""
        if self._mode_override != MODE_FOLLOW:
            return self._mode_override
        hub = get_master(self.hass)
        return hub.mode if hub else MODE_OCCUPIED

    @property
    def house_mode_source(self):
        if self._mode_override != MODE_FOLLOW:
            return "rum"
        return "master" if get_master(self.hass) else "ingen"

    def _mode_temp(self, mode):
        hub = get_master(self.hass)
        if mode == MODE_FROST:
            return hub.frost_temp if hub else DEFAULT_FROST_TEMP
        return hub.unoccupied_temp if hub else DEFAULT_UNOCCUPIED_TEMP

    @property
    def _setback(self):
        """Hvor mange grader setpunkterne saenkes af husets tilstand (0 i Beboet)."""
        mode = self.house_mode
        if mode in (MODE_UNOCCUPIED, MODE_FROST):
            return max(0.0, self._target_temp_room - self._mode_temp(mode))
        return 0.0

    @property
    def effective_room_target(self):
        return self._target_temp_room - self._setback

    @property
    def effective_floor_target(self):
        return max(10.0, self._target_temp_floor - self._setback)

    @property
    def alarms(self):
        return list(self._alarms)

    @property
    def runtime_today_hours(self):
        self._roll_runtime_day()
        return round(self._runtime_s / 3600.0, 2)

    def _roll_runtime_day(self):
        today = dt_util.now().date().isoformat()
        if self._runtime_date != today:
            self._runtime_date = today
            self._runtime_s = 0.0

    async def async_set_mode_override(self, mode):
        if mode in ROOM_MODE_OPTIONS and mode != self._mode_override:
            self._mode_override = mode
            self._reset_d = True
            self._metrics.reset_hunt()
            await self._async_calculate_heating_demand()

    async def _async_master_changed(self):
        self._reset_d = True
        self._metrics.reset_hunt()
        await self._async_calculate_heating_demand()

    @property
    def open_sensors(self):
        """Liste over de vindues-/dørkontakter, der siger 'åben' lige nu."""
        out = []
        for sensor in self._window_sensors:
            state = self.hass.states.get(sensor)
            if state is not None and state.state == STATE_ON:
                out.append(sensor)
        return out

    @property
    def window_open(self):
        """True hvis NOGEN af rummets vinduer/døre er åbne.

        En manglende/unavailable kontakt tæller som lukket, så en defekt sensor
        aldrig kan holde varmen frosset for evigt.
        """
        return len(self.open_sensors) > 0

    # ----------------------------------------------------- sommerstop og varmemodel

    @property
    def summer_stopped(self):
        """True, når Masterens sommerstop gælder dette rum lige nu."""
        if not self._summer_applies:
            return False
        hub = get_master(self.hass)
        return bool(hub is not None and getattr(hub, "summer_active", False))

    def _model_source(self):
        return "gulv" if self._attr_preset_mode == PRESET_FLOOR_ONLY else "rum"

    def _model_temp(self):
        if self._model_source() == "gulv":
            return self._read_temp(self._floor_sensor)
        return self._control_room_temp()

    def _record_thermal(self, now=None):
        """Saml et målepunkt til varmemodellen - kun mens målingerne siger noget om rummet."""
        if self._tuner is not None or self._exercise_start is not None or self.window_open:
            self._thermal.interrupt()
            return
        source = self._model_source()
        if self._thermal_source != source:
            # Rum- og gulvmålinger må ikke blandes: begynd forfra, hvis tilstanden skifter mellem dem
            if self._thermal_source is not None:
                self._thermal.restore({})
            self._thermal_source = source
        output = 0.0 if self._attr_hvac_mode == HVACMode.OFF else self._pid_signal
        added = self._thermal.add(
            time.time() if now is None else now, output, self._model_temp(), self._outdoor_temp()
        )
        if added and self._thermal_store is not None:
            self._thermal_store.async_delay_save(self._thermal_data, THERMAL_SAVE_DELAY)

    def _thermal_data(self):
        return {"source": self._thermal_source, **self._thermal.as_dict()}

    def preheat_hours(self):
        """Timer fra nu til rummet er tilbage på sit normale mål. None, hvis rummet ikke følger Masteren."""
        if self._attr_hvac_mode == HVACMode.OFF or self._mode_override != MODE_FOLLOW:
            return None
        temp = self._model_temp()
        if temp is None:
            return None
        target = self._target_temp_floor if self._model_source() == "gulv" else self._target_temp_room
        return round(self._thermal.preheat_hours(temp, target, self._outdoor_temp()), 1)

    # ------------------------------------------------------------- skimmelrisiko

    def _read_humidity(self):
        if self._is_silent(self._humidity_sensor):
            return None
        state = self.hass.states.get(self._humidity_sensor)
        try:
            return float(state.state)
        except (AttributeError, TypeError, ValueError):
            return None

    def _mold_temp(self):
        """Relativ fugtighed hører til den temperatur, den er målt ved: brug fugtfølerens egen, hvis den har en."""
        now = time.monotonic()
        if self._humidity_temp_scanned is None or now - self._humidity_temp_scanned >= 3600:
            self._humidity_temp_scanned = now
            self._humidity_temp_sensor = find_sibling_temperature(self.hass, self._humidity_sensor)
        if self._humidity_temp_sensor:
            return self._read_temp(self._humidity_temp_sensor)
        return self._own_room_temp()

    def _update_mold(self):
        if not self._humidity_sensor:
            return
        humidity = self._read_humidity()
        surface = surface_humidity(self._mold_temp(), humidity, self._outdoor_temp())
        change = self._mold.update(surface, time.monotonic())
        key = getattr(self, "entity_id", None) or self.name
        if change == "start":
            notify(
                self.hass, f"afh_mold_{key}", f"Gulvvarme: risiko for skimmel i {self.name}",
                f"**{self.name}:** den koldeste ydervæg har ca. {round(surface)} % fugtighed "
                f"(rummet {round(humidity)} %). Luft ud, eller hold rummet lidt varmere.",
            )
        elif change == "stop":
            notify(
                self.hass, f"afh_mold_{key}", f"Gulvvarme: skimmelrisikoen er ovre i {self.name}",
                f"**{self.name}:** væggen er nede på ca. {round(surface)} % fugtighed.",
            )

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
            # Hvornår var ventilen sidst åben? (så motionen overlever genstart)
            last_on = last_state.attributes.get("last_valve_on")
            if last_on:
                try:
                    from datetime import datetime
                    self._last_valve_on = datetime.fromisoformat(str(last_on)).timestamp()
                except (TypeError, ValueError):
                    pass

            override = last_state.attributes.get("mode_override")
            if override in ROOM_MODE_OPTIONS:
                self._mode_override = override
            if last_state.attributes.get("runtime_date"):
                self._runtime_date = str(last_state.attributes["runtime_date"])
                try:
                    self._runtime_s = float(last_state.attributes.get("runtime_seconds", 0))
                except (TypeError, ValueError):
                    self._runtime_s = 0.0

            if "control_output" in last_state.attributes:
                self._pid_signal = max(0.0, min(100.0, float(last_state.attributes["control_output"])))

        # Den lærte varmemodel gemmes for sig (for stor til attributterne)
        self._thermal_store = Store(self.hass, 1, f"{DOMAIN}_thermal_{self._entry_id}")
        stored = await self._thermal_store.async_load()
        if stored:
            self._thermal.restore(stored)
            self._thermal_source = stored.get("source")

        # React immediately when the window opens or closes
        if self._window_sensors:
            self.async_on_remove(
                async_track_state_change_event(
                    self.hass, self._window_sensors, self._async_window_changed
                )
            )

        # Besked fra Masteren: skift af husets tilstand
        self.async_on_remove(
            # Coroutine direkte: dispatcheren koerer den i event-loopet (en lambda ville
            # blive koert i en traad, og async_create_task fejler dér)
            async_dispatcher_connect(self.hass, MASTER_SIGNAL, self._async_master_changed)
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
        if self._verify_task is not None:
            self._verify_task.cancel()
            self._verify_task = None
        if self._thermal_store is not None:
            await self._thermal_store.async_save(self._thermal_data())
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
        curr_room = self._own_room_temp()
        curr_floor = self._read_temp(self._floor_sensor)

        return {
            "regulation_status": self._regulation_status,
            # 0.0 (ikke None) naar foleren mangler: Lovelace-kortet kalder .toFixed() paa vaerdien
            "room_temperature": curr_room if curr_room is not None else 0.0,
            "room_target_temperature": self._target_temp_room,
            "floor_temperature": curr_floor if curr_floor is not None else 0.0,
            "floor_target_temperature": self._target_temp_floor,
            "max_floor_temperature": self._max_floor_temp,
            "window_sensor": self._window_sensors,
            "open_sensors": self.open_sensors,
            # Bruges af Lovelace-kortet til at vise historik (graf)
            "room_sensor": self._room_sensor,
            "has_room_sensor": self._room_sensor is not None,
            "backup_room_sensor": self._backup_sensor,
            "using_backup": self.using_backup,
            "room_sensor_problem": None if self._room_sensor is None else self._sensor_problem(self._room_sensor),
            "silent_hours": self._silent_hours,
            "floor_sensor": self._floor_sensor,
            "heater_switch": self._heater_switch,
            "window_open": self.window_open,
            "output_frozen": self._frozen,
            "floor_limited": self._floor_limited,
            "control_output": round(self._pid_signal, 2),
            "kp": self._kp,
            "ki": self._ki,
            "kd": self._kd,
            "pid_p": round(self._p_out, 2),
            "pid_i": round(self._i_out, 2),
            "pid_d": round(self._d_out, 2),
            "pid_e": round(self._current_error, 2),
            "pid_interval": self._pid_interval,
            "pwm_cycle_time": self._cycle_time,
            "house_mode": self.house_mode,
            "house_mode_source": self.house_mode_source,
            "mode_override": self._mode_override,
            "effective_room_target": round(self.effective_room_target, 2),
            "effective_floor_target": round(self.effective_floor_target, 2),
            "pump_group": self._pump_group,
            "pump_switch": self._pump_switch,
            "linked_rooms": self._linked_rooms,
            "link_weight": self._link_weight,
            "control_room_temperature": (
                round(self._control_room_temp(), 2) if self._control_room_temp() is not None else None
            ),
            "hunting": self._metrics.hunting(),
            "pending_proposal": self._pending_proposal(),
            "outdoor_ke": self._ke,
            "solar_gain": self._ks,
            "pid_ff": round(self._ff_out, 2),
            "stale_hours": self._stale_hours,
            "alarms": self._alarms,
            "alarm": bool(self._alarms),
            "runtime_seconds": round(self._runtime_s),
            "runtime_date": self._runtime_date,
            "valve_exercise_days": self._exercise_days,
            "valve_exercising": self._exercise_start is not None,
            "last_valve_on": self._iso(self._last_valve_on),
            "autotune_active": self.autotune_active,
            "autotune_status": self._autotune_msg,
            "autotune_result": self._tuner_result,
            "summer_stop": self.summer_stopped,
            "summer_stop_applies": self._summer_applies,
            "thermal_model": self._thermal.fit(),
            "thermal_windows": len(self._thermal.windows),
            "preheat_hours": self.preheat_hours(),
            "humidity_sensor": self._humidity_sensor,
            "surface_humidity": None if self._mold.surface is None else round(self._mold.surface),
            "mold_risk": self._mold.risk,
            "mold_limits": [MOLD_CLEAR_RH, MOLD_ALARM_RH],
        }

    # ------------------------------------------------------------------ control

    async def _async_pid_loop(self):
        """Main loop for PID calculations."""
        while True:
            await self._async_calculate_heating_demand()
            self._record_metrics()
            self._record_thermal()
            await asyncio.sleep(max(1, self._pid_interval))

    def _record_metrics(self):
        """Gem et måle-punkt til gennemgangen - kun mens rummet regulerer helt normalt."""
        if (
            self._attr_hvac_mode == HVACMode.OFF
            or self.house_mode == MODE_OFF
            or self._tuner is not None
            or self._exercise_start is not None
        ):
            return
        status = self._regulation_status or ""
        if "mangler" in status or "gammel" in status or "tavs" in status or status.startswith(("Sikkerhedsstop", "Sommerstop", STATUS_FLOOR_LIMIT)):
            return
        floor = self._read_temp(self._floor_sensor)
        if floor is None:
            return
        ctrl = self._control_room_temp() if self._attr_preset_mode != PRESET_FLOOR_ONLY else floor
        self._metrics.add(time.time(), self._current_error, ctrl, floor, self._pid_signal, self._frozen)

    @staticmethod
    def _iso(epoch):
        from datetime import datetime, timezone
        return datetime.fromtimestamp(epoch, tz=timezone.utc).isoformat() if epoch else None

    def _handle_valve_exercise(self):
        """Ventilmotion. Returnerer True, mens en motion kører (så PID'en springes over).

        Har ventilen ikke været åben i `valve_exercise_days` dage, motioneres den som i IHC-programmet:
        3 cyklusser, hver med 10 min åben og 10 min lukket, så termomotoren ikke sætter sig.
        Gulv-sikkerheden gælder også her.
        """
        now = time.monotonic()
        if self._exercise_start is not None:
            floor = self._read_temp(self._floor_sensor)
            elapsed = now - self._exercise_start
            phase = int(elapsed // VALVE_EXERCISE_PHASE_SECONDS)
            if phase >= 2 * VALVE_EXERCISE_CYCLES or floor is None or floor >= self._max_floor_temp - 0.5:
                self._exercise_start = None
                self._pid_signal = 0.0
                return False
            opening = (phase % 2 == 0)
            self._pid_signal = 100.0 if opening else 0.0
            if opening:
                self._last_valve_on = time.time()
            self._regulation_status = (
                f"Ventilmotion ({phase // 2 + 1}/{VALVE_EXERCISE_CYCLES}, "
                f"{'åben' if opening else 'lukket'})"
            )
            return True

        if (
            self._exercise_days > 0
            and self._tuner is None
            and time.time() - self._last_valve_on > self._exercise_days * 86400
        ):
            floor = self._read_temp(self._floor_sensor)
            if floor is not None and floor < self._max_floor_temp - 1.0:
                _LOGGER.info("%s: ventilen har ikke været åben i %s dage - kører ventilmotion",
                             self.name, self._exercise_days)
                self._exercise_start = now
                self._pid_signal = 100.0
                self._last_valve_on = time.time()
                self._frozen = False
                self._regulation_status = f"Ventilmotion (1/{VALVE_EXERCISE_CYCLES}, åben)"
                return True
        return False

    async def _async_calculate_heating_demand(self):
        """The mathematical heart of the integration."""
        if self._handle_valve_exercise():
            self._publish()
            return

        mode = self.house_mode
        if self._attr_hvac_mode == HVACMode.OFF or mode == MODE_OFF:
            if self._tuner is not None:
                self._autotune_abort("regulatoren blev slukket")
            self._pid_signal = 0.0
            self._frozen = False
            if self._attr_hvac_mode == HVACMode.OFF:
                self._regulation_status = "Slukket (HVAC OFF)"
            else:
                self._regulation_status = f"Slukket ({'Master' if self.house_mode_source == 'master' else 'Rum'})"
            self._update_alarms()
            self._publish()
            return

        curr_floor = self._read_temp(self._floor_sensor)
        if curr_floor is None:
            # Without the floor sensor we cannot guarantee the floor limit -> heating off.
            problem = self._sensor_problem(self._floor_sensor) or "mangler"
            if self._tuner is not None:
                self._autotune_abort(f"gulvføler {problem}")
            self._pid_signal = 0.0
            self._regulation_status = f"Gulvføler {problem} (Slukket)"
            self._update_alarms()
            self._publish()
            return

        if self._tuner is not None:
            if mode != MODE_OCCUPIED:
                self._autotune_abort(f"husets tilstand er {mode}")
            else:
                self._autotune_step(curr_floor)
            self._update_alarms()
            self._publish()
            return

        if self.summer_stopped:
            self._floor_limited = False
            self._pid_signal = 0.0
            self._frozen = False
            self._reset_d = True  # ingen D-spike, når varmen tændes igen
            self._regulation_status = STATUS_SUMMER
            self._update_alarms()
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
            curr_room = self._control_room_temp() if uses_room else None
            if uses_room and curr_room is None:
                problem = self._sensor_problem(self._room_sensor) or "mangler"
                self._pid_signal = 0.0
                self._regulation_status = f"Rumføler {problem} (Slukket)"
                self._update_alarms()
                self._publish()
                return

            self._run_pid(curr_room, curr_floor)

        # Safety stop always wins - also while the output is frozen
        if curr_floor >= self._max_floor_temp:
            self._pid_signal = 0.0
            self._regulation_status = "Sikkerhedsstop (Gulv for varmt!)"
        elif self._pid_signal == 0 and not frozen and not self._floor_limited:
            self._regulation_status = "Mål nået (Slukket)"

        self._update_alarms()
        self._publish()

    # ----------------------------------------------------------- forslag og gennemgang

    def _review(self):
        return self.hass.data.get(DOMAIN, {}).get(REVIEW_KEY)

    def _pending_proposal(self):
        mgr = self._review()
        return mgr.get_proposal(self.entity_id) if mgr is not None else None

    async def async_apply_params(self, params):
        """Gem nye værdier (Kp/Ki/Kd, ke, ks, vægt) i rummets indstillinger; rummet genindlæses."""
        options = {**self._entry.options, **params}
        self.hass.config_entries.async_update_entry(self._entry, options=options)

    async def async_apply_proposal(self):
        mgr = self._review()
        if mgr is not None:
            await mgr.async_apply_proposal(self)

    # ----------------------------------------------------------------- alarmer

    def _update_alarms(self):
        """Opdater rummets alarmer: foeler mangler/gammel i en periode, ventil der ikke varmer."""
        now = time.monotonic()
        alarms = []
        for label, entity in (("Rumføler", self._room_sensor), ("Gulvføler", self._floor_sensor),
                              ("Reserveføler", self._backup_sensor)):
            if entity is None:
                continue  # rummet har ikke denne føler
            problem = self._sensor_problem(entity)
            if problem is None:
                self._sensor_bad_since.pop(entity, None)
            else:
                since = self._sensor_bad_since.setdefault(entity, now)
                if now - since >= SENSOR_ALARM_MINUTES * 60:
                    note = " (reserven styrer)" if entity == self._room_sensor and self.using_backup else ""
                    alarms.append(f"{label} {problem}{note}")

        # Telestaten: væk i en periode, eller følger ikke kommandoen
        switch = self.hass.states.get(self._heater_switch)
        if switch is None or switch.state in (STATE_UNAVAILABLE, STATE_UNKNOWN):
            if self._switch_bad_since is None:
                self._switch_bad_since = now
            if now - self._switch_bad_since >= SENSOR_ALARM_MINUTES * 60:
                alarms.append("Telestat mangler")
        else:
            self._switch_bad_since = None
        if self._failed_command is not None:
            alarms.append("Telestat følger ikke kommandoen")

        alarms.extend(self._battery_alarms(now))

        # Ventil der sidder fast: fuld udgang i lang tid uden at gulvet stiger
        floor = self._read_temp(self._floor_sensor)
        # Er shuntens fremløb for koldt til at varme gulvet, er det ikke ventilen, der er fejl
        # (rådet om at skrue shunten op tager sig af det) -> ingen alarm og nulstil uret
        group = self.hass.data.get(DOMAIN, {}).get(self._pump_group) if self._pump_group else None
        supply = group.supply_temp() if hasattr(group, "supply_temp") else None
        supply_low = supply is not None and supply < self.effective_floor_target + SUPPLY_MARGIN
        heating = (
            self._pid_signal >= 90.0
            and self._exercise_start is None
            and self._tuner is None
            and floor is not None
            and floor < self.effective_floor_target - 1.0
            and floor < self._max_floor_temp - 1.0
            and not supply_low
        )
        if heating:
            if self._full_since is None or floor - self._full_floor0 >= STUCK_VALVE_MIN_RISE:
                self._full_since = now
                self._full_floor0 = floor
            elif now - self._full_since >= STUCK_VALVE_MINUTES * 60:
                alarms.append("Ventil sidder muligvis fast (fuld udgang, gulvet stiger ikke)")
        else:
            self._full_since = None
            self._full_floor0 = None

        self._update_mold()

        if alarms != self._alarms:
            old = self._alarms
            new = [a for a in alarms if a not in old]
            self._alarms = alarms
            key = getattr(self, "entity_id", None) or self.name
            if alarms:
                _LOGGER.warning("%s: alarm: %s", self.name, "; ".join(alarms))
                if new:
                    notify(
                        self.hass, f"afh_alarm_{key}", f"Gulvvarme: alarm i {self.name}",
                        f"**{self.name}:** " + "; ".join(alarms) + ".",
                    )
            else:
                # Samme id: beskeden (og en evt. push) erstattes af "løst"
                notify(
                    self.hass, f"afh_alarm_{key}", f"Gulvvarme: løst i {self.name}",
                    f"**{self.name}:** " + "; ".join(old) + " – er løst.",
                )
            async_dispatcher_send(self.hass, ALARM_SIGNAL)

    def _battery_alarms(self, now):
        """Lavt batteri på rum- og gulvfølerens enhed. Teksten er uden procent, så beskeden ikke gentages."""
        if self._battery_scanned is None or now - self._battery_scanned >= 3600:
            self._battery_scanned = now
            self._battery_entities = {
                sensor: find_battery_entities(self.hass, sensor)
                for sensor in (self._room_sensor, self._floor_sensor, self._backup_sensor, self._humidity_sensor)
                if sensor
            }
        alarms, seen = [], set()
        for label, sensor in (("rumføler", self._room_sensor), ("gulvføler", self._floor_sensor),
                              ("reserveføler", self._backup_sensor), ("fugtføler", self._humidity_sensor)):
            for battery in self._battery_entities.get(sensor, []):
                if battery in seen:
                    continue
                seen.add(battery)
                low, _level = battery_low(
                    self.hass.states.get(battery), battery, self._battery_state.get(battery, False)
                )
                self._battery_state[battery] = low
                if low:
                    alarms.append(f"Lavt batteri i {label}")
        return alarms

    # ------------------------------------------------------ kontrol af kommandoer

    async def _async_set_valve(self, on):
        """Send kommandoen til telestaten, og kontrollér bagefter, at den blev fulgt."""
        await self.hass.services.async_call(
            "switch", "turn_on" if on else "turn_off", {"entity_id": self._heater_switch}
        )
        self._start_verify("on" if on else "off")

    def _start_verify(self, want):
        task = self._verify_task
        if task is not None and not task.done():
            if self._verify_want == want:
                return  # den samme kommando kontrolleres allerede
            task.cancel()
        self._verify_want = want
        self._verify_task = self.hass.async_create_background_task(
            self._async_verify(want), name=f"Verify_{self.entity_id}"
        )

    async def _async_verify(self, want):
        """Kom kommandoen ikke frem, sendes den igen. PWM-tiderne påvirkes ikke."""
        for attempt in range(VERIFY_RETRIES + 1):
            await asyncio.sleep(VERIFY_DELAY_SECONDS)
            state = self.hass.states.get(self._heater_switch)
            if state is None or state.state in (STATE_UNAVAILABLE, STATE_UNKNOWN):
                return  # dækkes af "Telestat mangler"
            if state.state == want:
                # Alarmen slettes kun, når netop den kommando, der fejlede, bliver fulgt
                if self._failed_command == want:
                    self._failed_command = None
                return
            if attempt < VERIFY_RETRIES:
                _LOGGER.warning("%s: %s fulgte ikke '%s' - sender igen", self.name, self._heater_switch, want)
                try:
                    await self.hass.services.async_call(
                        "switch", "turn_on" if want == "on" else "turn_off",
                        {"entity_id": self._heater_switch},
                    )
                except Exception as err:  # noqa: BLE001
                    _LOGGER.warning("Could not switch %s: %s", self._heater_switch, err)
        self._failed_command = want

    def _outdoor_temp(self):
        """Ude-temperatur fra Masteren (efter dens valgte kilde: måling, prognose eller begge)."""
        hub = get_master(self.hass)
        return hub.outdoor_temp() if hub is not None else None

    def _solar(self):
        """Sol 0..1 fra Masteren (solhøjde x klar himmel)."""
        hub = get_master(self.hass)
        return hub.solar() if hub is not None else 0.0

    def _add_runtime(self, seconds):
        self._roll_runtime_day()
        self._runtime_s += seconds

    # ---------------------------------------------------------------- autotune

    @property
    def autotune_active(self):
        return self._tuner is not None

    def _autotune_abort(self, reason):
        _LOGGER.warning("Autotune af %s afbrudt: %s", self.name, reason)
        self._tuner = None
        self._pid_signal = 0.0
        self._autotune_msg = f"Autotune afbrudt: {reason}"
        self._regulation_status = self._autotune_msg

    def _autotune_step(self, curr_floor):
        """Ét skridt af autotunen. Kaldes i stedet for PID'en, mens en test kører."""
        tuner = self._tuner
        target = self._tuner_target

        if target == "room" and self.window_open:
            return self._autotune_abort("vindue åbent")
        pv = self._control_room_temp() if target == "room" else self._read_temp(self._floor_sensor)
        if pv is None:
            return self._autotune_abort("føler mangler")
        # Gulv-sikkerheden gælder altid - og en afkortet test giver ugyldige tal
        if curr_floor >= self._max_floor_temp - 0.5:
            return self._autotune_abort("gulvet nærmer sig max gulvtemperatur (sænk udgangstrin eller setpunkt)")

        self._pid_signal = tuner.update(pv, time.monotonic())

        if tuner.failed:
            return self._autotune_abort(tuner.failed)
        if tuner.finished:
            self._tuner_result = tuner.result
            self._tuner = None
            # Overgå blødt til PID'en: lad I-leddet holde det udgangsniveau, testen svingede om
            if self._ki > 0:
                self._integral_sum = tuner.bias / self._ki
                self._i_out = tuner.bias
            if target == "room":
                self._last_error = self._target_temp_room - pv
            else:
                self._last_error = self._target_temp_floor - pv
            self._autotune_msg = tuner.progress_text() + " - tryk 'Anvend Autotune' for at bruge dem"
            self._regulation_status = self._autotune_msg
            return
        self._autotune_msg = tuner.progress_text()
        self._regulation_status = f"{self._autotune_msg} - udgang {round(self._pid_signal)}%"

    async def async_start_autotune(self, target=None, output_step=30, noiseband=0.2,
                                   rule=DEFAULT_RULE, max_hours=24):
        """Start autotune. Regulerer på rum, hvis driftstilstanden bruger rummet, ellers på gulv."""
        if self._attr_hvac_mode == HVACMode.OFF:
            self._autotune_msg = "Autotune kan ikke startes: regulatoren er slukket"
            self._publish()
            return
        if self.house_mode != MODE_OCCUPIED:
            self._autotune_msg = f"Autotune kan ikke startes: husets tilstand er {self.house_mode}"
            self._publish()
            return
        if target is None:
            target = "floor" if self._attr_preset_mode == PRESET_FLOOR_ONLY else "room"
        pv = self._control_room_temp() if target == "room" else self._read_temp(self._floor_sensor)
        if pv is None:
            self._autotune_msg = "Autotune kan ikke startes: føler mangler"
            self._publish()
            return
        setpoint = self._target_temp_room if target == "room" else self._target_temp_floor
        # Bias: det udgangsniveau, regulatoren selv har fundet frem til (I-leddet), ellers et gæt
        if self._pid_signal > 5:
            bias = self._pid_signal
        elif self._i_out > 5:
            bias = self._i_out
        else:
            bias = 40.0
        self._tuner = RelayAutoTuner(
            setpoint, bias, step=output_step, noiseband=noiseband, rule=rule,
            max_seconds=max_hours * 3600,
        )
        self._tuner_target = target
        self._tuner_result = None
        self._frozen = False
        self._autotune_msg = f"Autotune startet på {'rum' if target == 'room' else 'gulv'} (setpunkt {setpoint} °C)"
        _LOGGER.info("%s: %s", self.name, self._autotune_msg)
        await self._async_calculate_heating_demand()

    async def async_stop_autotune(self):
        if self._tuner is not None:
            self._autotune_abort("stoppet manuelt")
            self._publish()

    async def async_apply_autotune(self):
        """Gem de fundne PID-værdier i rummets indstillinger (genindlæser rummet)."""
        r = self._tuner_result
        if not r:
            self._autotune_msg = "Der er intet autotune-resultat at anvende"
            self._publish()
            return
        options = {**self._entry.options, "kp": r["kp"], "ki": r["ki"], "kd": r["kd"]}
        self.hass.config_entries.async_update_entry(self._entry, options=options)

    def _run_pid(self, curr_room, curr_floor):
        """One PID step. Updates _pid_signal and the PID terms."""
        eff_room = self.effective_room_target
        err_f = self.effective_floor_target - curr_floor
        err_r = (eff_room - curr_room) if curr_room is not None else None

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

        # Blød gulvgrænse: kræver gulvet mindre varme end tilstanden beder om, regulerer PID'en efter
        # gulvet (lige under maks.), til rummet/gulvmålet igen er det mindste. Så undgås savtakket
        # tænd/sluk ved det hårde stop, og I-leddet løber ikke op imens.
        limit_error = (self._max_floor_temp - FLOOR_LIMIT_MARGIN) - curr_floor
        self._floor_limited = limit_error < error
        if self._floor_limited:
            error = limit_error
            self._regulation_status = (
                f"{STATUS_FLOOR_LIMIT} (holder gulvet ved {self._max_floor_temp - FLOOR_LIMIT_MARGIN:.1f}°)"
            )

        # Coming back from a frozen output: forget the old error so the
        # D-term does not give a spike on the first step.
        if self._frozen or self._reset_d:
            self._last_error = error
            self._frozen = False
            self._reset_d = False

        self._current_error = error
        dt = self._pid_interval

        # P and D calculation
        self._p_out = self._kp * error
        self._d_out = self._kd * ((error - self._last_error) / dt) * self._d_time

        # Integral calculation with Anti-Windup (Clamping)
        i_step = error * (dt / self._i_time)
        test_i_sum = self._integral_sum + i_step
        test_i_out = self._ki * test_i_sum
        # Udekompensation (valgfri): fast tillaeg efter hvor koldt det er ude
        # og et fradrag, når solen varmer (ks). Begge er 0 som standard.
        self._ff_out = 0.0
        if self._ke > 0:
            outdoor = self._outdoor_temp()
            if outdoor is not None:
                self._ff_out += max(0.0, self._ke * (eff_room - outdoor))
        if self._ks > 0:
            self._ff_out -= self._ks * self._solar()
        test_signal = self._p_out + test_i_out + self._d_out + self._ff_out

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
        y_signal = self._p_out + self._i_out + self._d_out + self._ff_out
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
                    await self._async_set_valve(True)
                    self._last_valve_on = time.time()
                    await asyncio.sleep(on_time)
                    self._add_runtime(on_time)

                if off_time > 0:
                    await self._async_set_valve(False)
                    await asyncio.sleep(off_time)
            except asyncio.CancelledError:
                raise
            except Exception as err:  # noqa: BLE001 - keep the loop alive
                _LOGGER.warning("Could not switch %s: %s", self._heater_switch, err)
                await asyncio.sleep(cycle)

    @property
    def native_current_temperature(self):
        if self._attr_preset_mode == PRESET_FLOOR_ONLY:
            return self._read_temp(self._floor_sensor)
        return self._own_room_temp()

    @property
    def native_target_temperature(self):
        if self._attr_preset_mode == PRESET_FLOOR_ONLY:
            return self._target_temp_floor
        return self._target_temp_room

    if not _NATIVE_TEMPERATURE:
        current_temperature = native_current_temperature
        target_temperature = native_target_temperature

    # --- CUSTOM SERVICES (English) ---
    async def async_set_room_temperature(self, temperature):
        """Sets ONLY the room target temperature."""
        self._target_temp_room = float(temperature)
        self._metrics.reset_hunt()
        await self._async_calculate_heating_demand()
        await self._async_sync_room_setpoint(self._target_temp_room)

    async def async_set_floor_temperature(self, temperature):
        """Sets ONLY the floor target temperature."""
        self._target_temp_floor = float(temperature)
        self._metrics.reset_hunt()
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
            if self._attr_preset_mode != PRESET_FLOOR_ONLY:
                await self._async_sync_room_setpoint(self._target_temp_room)

    async def async_set_preset_mode(self, preset_mode):
        if preset_mode in self._attr_preset_modes:
            self._attr_preset_mode = preset_mode
            self._metrics.reset_hunt()
            await self._async_calculate_heating_demand()

    async def async_set_hvac_mode(self, hvac_mode):
        if hvac_mode in self._attr_hvac_modes:
            self._attr_hvac_mode = hvac_mode
            await self._async_calculate_heating_demand()

    async def async_turn_on(self):
        await self.async_set_hvac_mode(HVACMode.HEAT)

    async def async_turn_off(self):
        await self.async_set_hvac_mode(HVACMode.OFF)

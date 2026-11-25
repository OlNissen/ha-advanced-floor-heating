import voluptuous as vol
from homeassistant import config_entries
from homeassistant.core import callback
from homeassistant.helpers import selector
from .const import (
    DOMAIN, CONF_ROOM_SENSOR, CONF_FLOOR_SENSOR, CONF_HEATER_SWITCH,
    CONF_WINDOW_SENSOR, CONF_MAX_FLOOR_TEMP, DEFAULT_MAX_FLOOR_TEMP,
    CONF_VALVE_EXERCISE_DAYS, DEFAULT_VALVE_EXERCISE_DAYS,
    CONF_ENTRY_TYPE, TYPE_ROOM, TYPE_MASTER, DEFAULT_MASTER_NAME,
    CONF_OUTDOOR_SENSOR, CONF_OUTDOOR_KE, CONF_STALE_HOURS, DEFAULT_STALE_HOURS,
    CONF_WEATHER_ENTITY, CONF_FORECAST_HOURS, DEFAULT_FORECAST_HOURS, CONF_SOLAR_GAIN,
    CONF_LINKED_ROOMS, CONF_LINK_WEIGHT, DEFAULT_LINK_WEIGHT,
    CONF_REVIEW_DAYS, DEFAULT_REVIEW_DAYS, CONF_ALLOW_AI_CHANGES,
    TYPE_PUMP, CONF_GROUP_ROOMS, CONF_PUMP_SWITCHES, CONF_PUMP_FEEDBACK, CONF_SHUNT_SENSOR,
    CONF_PUMP_STOP_MINUTES, DEFAULT_PUMP_STOP_MINUTES, CONF_PUMP_MOTION_DAYS, DEFAULT_PUMP_MOTION_DAYS,
    CONF_NOTIFY_IN_HA, CONF_NOTIFY_MOBILES, CONF_PUMP_GROUP, CONF_ROOM_PUMP_SWITCH,
)

def _group_options(hass):
    """Pumpegrupperne som valgmuligheder (værdi = entry_id)."""
    return [
        {"value": e.entry_id, "label": e.title}
        for e in hass.config_entries.async_entries(DOMAIN)
        if e.data.get(CONF_ENTRY_TYPE) == TYPE_PUMP
    ]


def _guess_pump_switch(hass, heater_switch):
    """Rummets pumpekontakt hedder ofte som telestaten, bare med _pumpestyring (switch.stue_telestat -> ..._pumpestyring)."""
    if not heater_switch or not heater_switch.endswith("_telestat"):
        return None
    guess = heater_switch[: -len("_telestat")] + "_pumpestyring"
    return guess if hass.states.get(guess) is not None else None


class AdvancedFloorHeatingConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Handle a config flow for Advanced Floor Heating."""
    VERSION = 1

    async def async_step_user(self, user_input=None):
        """Vaelg, om der tilfoejes et rum eller husets Master."""
        return self.async_show_menu(step_id="user", menu_options=["room", "pump_group", "master"])

    async def async_step_master(self, user_input=None):
        """Masteren: husets tilstand, der sendes ud til alle rum (kun én)."""
        for entry in self._async_current_entries():
            if entry.data.get(CONF_ENTRY_TYPE) == TYPE_MASTER:
                return self.async_abort(reason="master_exists")
        if user_input is not None:
            data = {"name": user_input["name"], CONF_ENTRY_TYPE: TYPE_MASTER}
            for key in (CONF_OUTDOOR_SENSOR, CONF_WEATHER_ENTITY):
                if user_input.get(key):
                    data[key] = user_input[key]
            return self.async_create_entry(title=user_input["name"], data=data)
        return self.async_show_form(
            step_id="master",
            data_schema=vol.Schema({
                vol.Required("name", default=DEFAULT_MASTER_NAME): str,
                vol.Optional(CONF_OUTDOOR_SENSOR): selector.EntitySelector(
                    selector.EntitySelectorConfig(domain="sensor", device_class="temperature")
                ),
                vol.Optional(CONF_WEATHER_ENTITY): selector.EntitySelector(
                    selector.EntitySelectorConfig(domain="weather")
                ),
            }),
        )

    async def async_step_pump_group(self, user_input=None):
        """En pumpegruppe: rum der deler pumpe og shunt (pumpestyring + shunt-råd)."""
        if user_input is not None:
            data = {k: v for k, v in user_input.items() if v not in (None, "", [])}
            data[CONF_ENTRY_TYPE] = TYPE_PUMP
            return self.async_create_entry(title=user_input["name"], data=data)
        return self.async_show_form(
            step_id="pump_group",
            data_schema=vol.Schema({
                vol.Required("name", default="Teknikrum"): str,
                vol.Optional(CONF_PUMP_FEEDBACK): selector.EntitySelector(
                    selector.EntitySelectorConfig(domain="binary_sensor")
                ),
                vol.Optional(CONF_SHUNT_SENSOR): selector.EntitySelector(
                    selector.EntitySelectorConfig(domain="sensor", device_class="temperature")
                ),
            }),
        )

    async def async_step_room(self, user_input=None):
        """Handle the step where a room is added."""
        if user_input is not None:
            data = dict(user_input)
            data[CONF_ENTRY_TYPE] = TYPE_ROOM
            return self.async_create_entry(title=user_input["name"], data=data)

        return self.async_show_form(
            step_id="room",
            data_schema=vol.Schema({
                vol.Required("name", default="Mit Rum"): str,
                vol.Required(CONF_ROOM_SENSOR): selector.EntitySelector(
                    selector.EntitySelectorConfig(domain="sensor", device_class="temperature")
                ),
                vol.Required(CONF_FLOOR_SENSOR): selector.EntitySelector(
                    selector.EntitySelectorConfig(domain="sensor", device_class="temperature")
                ),
                vol.Required(CONF_HEATER_SWITCH): selector.EntitySelector(
                    selector.EntitySelectorConfig(domain="switch")
                ),
                vol.Optional(CONF_WINDOW_SENSOR): selector.EntitySelector(
                    selector.EntitySelectorConfig(domain="binary_sensor", multiple=True)
                ),
                vol.Optional(CONF_PUMP_GROUP): selector.SelectSelector(
                    selector.SelectSelectorConfig(
                        options=_group_options(self.hass), mode=selector.SelectSelectorMode.DROPDOWN
                    )
                ),
                vol.Optional(CONF_ROOM_PUMP_SWITCH): selector.EntitySelector(
                    selector.EntitySelectorConfig(domain="switch")
                ),
            }),
        )

    @staticmethod
    @callback
    def async_get_options_flow(config_entry):
        """Get the options flow for this handler."""
        return AdvancedFloorHeatingOptionsFlowHandler()

class AdvancedFloorHeatingOptionsFlowHandler(config_entries.OptionsFlow):
    """Handle the options flow to tune PID parameters."""
    async def async_step_init(self, user_input=None):
        """Manage the options settings."""
        options = self.config_entry.options
        if self.config_entry.data.get(CONF_ENTRY_TYPE) == TYPE_MASTER:
            return await self.async_step_master_options(user_input)
        if self.config_entry.data.get(CONF_ENTRY_TYPE) == TYPE_PUMP:
            return await self.async_step_pump_options(user_input)
        # Window sensor: options win over what was typed in when the room was created
        window_sensor = options.get(
            CONF_WINDOW_SENSOR, self.config_entry.data.get(CONF_WINDOW_SENSOR)
        )
        # Gammel opsætning: én kontakt som tekst -> liste
        if isinstance(window_sensor, str):
            window_sensor = [window_sensor]
        window_sensor = window_sensor or []
        linked = options.get(CONF_LINKED_ROOMS, self.config_entry.data.get(CONF_LINKED_ROOMS))
        if isinstance(linked, str):
            linked = [linked]
        linked = linked or []
        pump_group = options.get(CONF_PUMP_GROUP, self.config_entry.data.get(CONF_PUMP_GROUP))
        pump_switch = options.get(CONF_ROOM_PUMP_SWITCH, self.config_entry.data.get(CONF_ROOM_PUMP_SWITCH))
        if not pump_switch:
            pump_switch = _guess_pump_switch(
                self.hass, options.get("heater_switch", self.config_entry.data.get("heater_switch"))
            )

        if user_input is not None:
            data = dict(user_input)
            # Store the key even when cleared, so options override the old value
            data.setdefault(CONF_WINDOW_SENSOR, [])
            data.setdefault(CONF_LINKED_ROOMS, [])
            data.setdefault(CONF_PUMP_GROUP, None)
            data.setdefault(CONF_ROOM_PUMP_SWITCH, None)
            return self.async_create_entry(title="", data=data)
        
        window_key = (
            vol.Optional(CONF_WINDOW_SENSOR, description={"suggested_value": window_sensor})
        )

        return self.async_show_form(
            step_id="init",
            data_schema=vol.Schema({
                window_key: selector.EntitySelector(
                    selector.EntitySelectorConfig(domain="binary_sensor", multiple=True)
                ),
                vol.Optional(CONF_PUMP_GROUP, description={"suggested_value": pump_group}): selector.SelectSelector(
                    selector.SelectSelectorConfig(
                        options=_group_options(self.hass), mode=selector.SelectSelectorMode.DROPDOWN
                    )
                ),
                vol.Optional(CONF_ROOM_PUMP_SWITCH, description={"suggested_value": pump_switch}):
                    selector.EntitySelector(selector.EntitySelectorConfig(domain="switch")),
                vol.Optional(CONF_LINKED_ROOMS, description={"suggested_value": linked}): selector.EntitySelector(
                    selector.EntitySelectorConfig(
                        domain="climate", integration="advanced_floor_heating", multiple=True
                    )
                ),
                vol.Required(
                    CONF_LINK_WEIGHT,
                    default=float(options.get(CONF_LINK_WEIGHT, DEFAULT_LINK_WEIGHT)),
                ): selector.NumberSelector(
                    selector.NumberSelectorConfig(mode=selector.NumberSelectorMode.BOX, min=0.1, max=1000, step=0.1)
                ),
                vol.Required(
                    CONF_MAX_FLOOR_TEMP,
                    default=float(options.get(
                        CONF_MAX_FLOOR_TEMP,
                        self.config_entry.data.get(CONF_MAX_FLOOR_TEMP, DEFAULT_MAX_FLOOR_TEMP),
                    )),
                ): selector.NumberSelector(
                    selector.NumberSelectorConfig(mode=selector.NumberSelectorMode.BOX, min=20, max=45, step=0.5)
                ),
                vol.Required(
                    CONF_VALVE_EXERCISE_DAYS,
                    default=float(options.get(CONF_VALVE_EXERCISE_DAYS, DEFAULT_VALVE_EXERCISE_DAYS)),
                ): selector.NumberSelector(
                    selector.NumberSelectorConfig(mode=selector.NumberSelectorMode.BOX, min=0, max=90, step=1)
                ),
                vol.Required(
                    CONF_STALE_HOURS,
                    default=float(options.get(CONF_STALE_HOURS, DEFAULT_STALE_HOURS)),
                ): selector.NumberSelector(
                    selector.NumberSelectorConfig(mode=selector.NumberSelectorMode.BOX, min=0, max=72, step=0.5)
                ),
                vol.Required(
                    CONF_OUTDOOR_KE,
                    default=float(options.get(CONF_OUTDOOR_KE, 0.0)),
                ): selector.NumberSelector(
                    selector.NumberSelectorConfig(mode=selector.NumberSelectorMode.BOX, min=0, max=10, step=0.05)
                ),
                vol.Required(
                    CONF_SOLAR_GAIN,
                    default=float(options.get(CONF_SOLAR_GAIN, 0.0)),
                ): selector.NumberSelector(
                    selector.NumberSelectorConfig(mode=selector.NumberSelectorMode.BOX, min=0, max=100, step=1)
                ),
                vol.Required("kp", default=float(options.get("kp", 10.0))): selector.NumberSelector(
                    selector.NumberSelectorConfig(mode=selector.NumberSelectorMode.BOX, min=0, max=1000, step=0.1)
                ),
                vol.Required("ki", default=float(options.get("ki", 2.0))): selector.NumberSelector(
                    selector.NumberSelectorConfig(mode=selector.NumberSelectorMode.BOX, min=0, max=1000, step=0.1)
                ),
                vol.Required("kd", default=float(options.get("kd", 1.0))): selector.NumberSelector(
                    selector.NumberSelectorConfig(mode=selector.NumberSelectorMode.BOX, min=0, max=1000, step=0.1)
                ),
                vol.Required("pid_interval", default=int(options.get("pid_interval", 30))): selector.NumberSelector(
                    selector.NumberSelectorConfig(mode=selector.NumberSelectorMode.BOX, min=1, max=3600, step=1)
                ),
                vol.Required("cycle_time", default=int(options.get("cycle_time", 30))): selector.NumberSelector(
                    selector.NumberSelectorConfig(mode=selector.NumberSelectorMode.BOX, min=1, max=3600, step=1)
                ),
            }),
        )

    async def async_step_master_options(self, user_input=None):
        """Masterens indstillinger: udeføler, vejr-entitet (prognose og sol) og prognosetimer."""
        options = self.config_entry.options
        data_ = self.config_entry.data

        def current(key):
            return options.get(key, data_.get(key))

        chosen_mobiles = current(CONF_NOTIFY_MOBILES) or []
        if isinstance(chosen_mobiles, str):
            chosen_mobiles = [chosen_mobiles]
        found = sorted(
            s for s in self.hass.services.async_services().get("notify", {}) if s.startswith("mobile_app_")
        )
        mobile_options = [
            {"value": s, "label": s.replace("mobile_app_", "")} for s in dict.fromkeys(found + list(chosen_mobiles))
        ]

        if user_input is not None:
            data = dict(user_input)
            # Gem nøglerne også når de er ryddet, så options overstyrer de gamle værdier
            data.setdefault(CONF_OUTDOOR_SENSOR, None)
            data.setdefault(CONF_WEATHER_ENTITY, None)
            data.setdefault(CONF_NOTIFY_MOBILES, [])
            return self.async_create_entry(title="", data=data)
        return self.async_show_form(
            step_id="master_options",
            data_schema=vol.Schema({
                vol.Optional(CONF_OUTDOOR_SENSOR, description={"suggested_value": current(CONF_OUTDOOR_SENSOR)}):
                    selector.EntitySelector(
                        selector.EntitySelectorConfig(domain="sensor", device_class="temperature")
                    ),
                vol.Optional(CONF_WEATHER_ENTITY, description={"suggested_value": current(CONF_WEATHER_ENTITY)}):
                    selector.EntitySelector(selector.EntitySelectorConfig(domain="weather")),
                vol.Required(
                    CONF_FORECAST_HOURS,
                    default=float(current(CONF_FORECAST_HOURS) or DEFAULT_FORECAST_HOURS),
                ): selector.NumberSelector(
                    selector.NumberSelectorConfig(mode=selector.NumberSelectorMode.BOX, min=1, max=12, step=1)
                ),
                vol.Required(
                    CONF_REVIEW_DAYS,
                    default=float(current(CONF_REVIEW_DAYS) or DEFAULT_REVIEW_DAYS),
                ): selector.NumberSelector(
                    selector.NumberSelectorConfig(mode=selector.NumberSelectorMode.BOX, min=3, max=120, step=1)
                ),
                vol.Required(
                    CONF_ALLOW_AI_CHANGES,
                    default=bool(current(CONF_ALLOW_AI_CHANGES)),
                ): selector.BooleanSelector(),
                vol.Required(
                    CONF_NOTIFY_IN_HA,
                    default=True if current(CONF_NOTIFY_IN_HA) is None else bool(current(CONF_NOTIFY_IN_HA)),
                ): selector.BooleanSelector(),
                vol.Optional(
                    CONF_NOTIFY_MOBILES, description={"suggested_value": chosen_mobiles}
                ): selector.SelectSelector(
                    selector.SelectSelectorConfig(
                        options=mobile_options, multiple=True, mode=selector.SelectSelectorMode.DROPDOWN
                    )
                ),
            }),
        )

    async def async_step_pump_options(self, user_input=None):
        """Pumpegruppens indstillinger."""
        options = self.config_entry.options
        data_ = self.config_entry.data

        def current(key):
            return options.get(key, data_.get(key))

        def as_list(value):
            if not value:
                return []
            return [value] if isinstance(value, str) else list(value)

        if user_input is not None:
            data = dict(user_input)
            for key in (CONF_PUMP_FEEDBACK, CONF_SHUNT_SENSOR):
                data.setdefault(key, None)
            for key in (CONF_GROUP_ROOMS, CONF_PUMP_SWITCHES):
                data.setdefault(key, [])
            return self.async_create_entry(title="", data=data)
        return self.async_show_form(
            step_id="pump_options",
            data_schema=vol.Schema({
                vol.Optional(CONF_GROUP_ROOMS, description={"suggested_value": as_list(current(CONF_GROUP_ROOMS))}):
                    selector.EntitySelector(
                        selector.EntitySelectorConfig(
                            domain="climate", integration="advanced_floor_heating", multiple=True
                        )
                    ),
                vol.Optional(CONF_PUMP_SWITCHES, description={"suggested_value": as_list(current(CONF_PUMP_SWITCHES))}):
                    selector.EntitySelector(selector.EntitySelectorConfig(domain="switch", multiple=True)),
                vol.Optional(CONF_PUMP_FEEDBACK, description={"suggested_value": current(CONF_PUMP_FEEDBACK)}):
                    selector.EntitySelector(selector.EntitySelectorConfig(domain="binary_sensor")),
                vol.Optional(CONF_SHUNT_SENSOR, description={"suggested_value": current(CONF_SHUNT_SENSOR)}):
                    selector.EntitySelector(
                        selector.EntitySelectorConfig(domain="sensor", device_class="temperature")
                    ),
                vol.Required(
                    CONF_PUMP_STOP_MINUTES,
                    default=float(current(CONF_PUMP_STOP_MINUTES) if current(CONF_PUMP_STOP_MINUTES) is not None
                                  else DEFAULT_PUMP_STOP_MINUTES),
                ): selector.NumberSelector(
                    selector.NumberSelectorConfig(mode=selector.NumberSelectorMode.BOX, min=0, max=60, step=1)
                ),
                vol.Required(
                    CONF_PUMP_MOTION_DAYS,
                    default=float(current(CONF_PUMP_MOTION_DAYS) if current(CONF_PUMP_MOTION_DAYS) is not None
                                  else DEFAULT_PUMP_MOTION_DAYS),
                ): selector.NumberSelector(
                    selector.NumberSelectorConfig(mode=selector.NumberSelectorMode.BOX, min=0, max=90, step=1)
                ),
            }),
        )

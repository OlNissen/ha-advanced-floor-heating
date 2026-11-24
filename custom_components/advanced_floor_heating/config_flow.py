import voluptuous as vol
from homeassistant import config_entries
from homeassistant.core import callback
from homeassistant.helpers import selector
from .const import (
    DOMAIN, CONF_ROOM_SENSOR, CONF_FLOOR_SENSOR, CONF_HEATER_SWITCH,
    CONF_WINDOW_SENSOR, CONF_MAX_FLOOR_TEMP, DEFAULT_MAX_FLOOR_TEMP,
)

class AdvancedFloorHeatingConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Handle a config flow for Advanced Floor Heating."""
    VERSION = 1

    async def async_step_user(self, user_input=None):
        """Handle the initial step where the user adds the integration."""
        if user_input is not None:
            return self.async_create_entry(title=user_input["name"], data=user_input)

        return self.async_show_form(
            step_id="user",
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
        # Window sensor: options win over what was typed in when the room was created
        window_sensor = options.get(
            CONF_WINDOW_SENSOR, self.config_entry.data.get(CONF_WINDOW_SENSOR)
        )
        # Gammel opsætning: én kontakt som tekst -> liste
        if isinstance(window_sensor, str):
            window_sensor = [window_sensor]
        window_sensor = window_sensor or []

        if user_input is not None:
            data = dict(user_input)
            # Store the key even when cleared, so options override the old value
            data.setdefault(CONF_WINDOW_SENSOR, [])
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
                vol.Required(
                    CONF_MAX_FLOOR_TEMP,
                    default=float(options.get(
                        CONF_MAX_FLOOR_TEMP,
                        self.config_entry.data.get(CONF_MAX_FLOOR_TEMP, DEFAULT_MAX_FLOOR_TEMP),
                    )),
                ): selector.NumberSelector(
                    selector.NumberSelectorConfig(mode=selector.NumberSelectorMode.BOX, min=20, max=45, step=0.5)
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
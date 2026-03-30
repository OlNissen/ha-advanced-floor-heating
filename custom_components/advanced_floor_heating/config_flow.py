import voluptuous as vol
from homeassistant import config_entries
from homeassistant.core import callback
from homeassistant.helpers import selector
from .const import DOMAIN, CONF_ROOM_SENSOR, CONF_FLOOR_SENSOR, CONF_HEATER_SWITCH

class AdvancedFloorHeatingConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    VERSION = 1

    async def async_step_user(self, user_input=None):
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
            }),
        )

    @staticmethod
    @callback
    def async_get_options_flow(config_entry):
        return AdvancedFloorHeatingOptionsFlowHandler()

class AdvancedFloorHeatingOptionsFlowHandler(config_entries.OptionsFlow):
    async def async_step_init(self, user_input=None):
        if user_input is not None:
            return self.async_create_entry(title="", data=user_input)

        options = self.config_entry.options
        
        return self.async_show_form(
            step_id="init",
            data_schema=vol.Schema({
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
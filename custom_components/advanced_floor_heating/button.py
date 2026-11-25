"""Knap der anvender resultatet af en færdig autotune."""
from homeassistant.components.button import ButtonEntity
from .const import DOMAIN, CONF_ENTRY_TYPE, TYPE_PUMP, TYPE_MASTER
from .helpers import device_info


async def async_setup_entry(hass, entry, async_add_entities):
    if entry.data.get(CONF_ENTRY_TYPE) == TYPE_MASTER:
        async_add_entities([MasterTestNotifyButton(entry)])
        return
    if entry.data.get(CONF_ENTRY_TYPE) == TYPE_PUMP:
        from .pump_entities import pump_buttons
        async_add_entities(pump_buttons(entry))
        return
    async_add_entities([ApplyAutotuneButton(entry), ApplyProposalButton(entry)])


class MasterTestNotifyButton(ButtonEntity):
    """Sender en testbesked på den måde, Masteren er sat op til (HA og/eller mobiler)."""

    _attr_icon = "mdi:bell-ring-outline"

    def __init__(self, entry):
        self._attr_name = f"{entry.data['name']} Send Testbesked"
        self._attr_unique_id = f"{entry.entry_id}_test_notify"
        self._attr_device_info = device_info(entry)

    async def async_press(self):
        from .notify import notify
        notify(
            self.hass, "afh_test", "Gulvvarme: testbesked",
            "Hvis du kan læse denne besked, virker notifikationerne fra Advanced Floor Heating.",
        )


class ApplyProposalButton(ButtonEntity):
    """Anvender et forslag til nye indstillinger (fra en AI-gennemgang). Intet ændres uden dette tryk."""

    _attr_icon = "mdi:check-decagram"

    def __init__(self, entry):
        self._attr_name = f"{entry.data['name']} Anvend Forslag"
        self._attr_unique_id = f"{entry.entry_id}_apply_proposal"
        self._attr_device_info = device_info(entry)
        self._entry_id = entry.entry_id

    async def async_press(self):
        climate = self.hass.data[DOMAIN].get(self._entry_id)
        if climate:
            await climate.async_apply_proposal()


class ApplyAutotuneButton(ButtonEntity):
    """Gemmer de fundne Kp/Ki i rummets indstillinger (rummet genindlæses)."""

    _attr_icon = "mdi:content-save-cog"

    def __init__(self, entry):
        self._attr_name = f"{entry.data['name']} Anvend Autotune"
        self._attr_unique_id = f"{entry.entry_id}_apply_autotune"
        self._attr_device_info = device_info(entry)
        self._entry_id = entry.entry_id

    async def async_press(self):
        climate = self.hass.data[DOMAIN].get(self._entry_id)
        if climate:
            await climate.async_apply_autotune()

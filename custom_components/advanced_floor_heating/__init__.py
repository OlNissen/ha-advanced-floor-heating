import logging
from .const import DOMAIN

_LOGGER = logging.getLogger(__name__)

async def async_setup_entry(hass, entry):
    """Set up Advanced Floor Heating from a config entry."""
    hass.data.setdefault(DOMAIN, {})
    
    # Forward the setup to the platforms (climate, sensor, number)
    await hass.config_entries.async_forward_entry_setups(entry, ["climate", "sensor", "number"])
    
    # Listen for option updates (when you change PID settings in the UI)
    entry.async_on_unload(entry.add_update_listener(update_listener))
    
    return True

async def update_listener(hass, entry):
    """Handle options update and reload the entry automatically."""
    await hass.config_entries.async_reload(entry.entry_id)

async def async_unload_entry(hass, entry):
    """Unload a config entry and its platforms."""
    unload_ok = await hass.config_entries.async_unload_platforms(entry, ["climate", "sensor", "number"])
    
    if unload_ok:
        hass.data[DOMAIN].pop(entry.entry_id, None)
        
    return unload_ok
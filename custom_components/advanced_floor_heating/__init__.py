import logging
from .const import DOMAIN, CONF_ENTRY_TYPE, TYPE_MASTER, MASTER_KEY, REVIEW_KEY

_LOGGER = logging.getLogger(__name__)

PLATFORMS_ROOM = ["climate", "sensor", "number", "switch", "button", "select", "binary_sensor"]
PLATFORMS_MASTER = ["select", "number", "binary_sensor", "sensor"]


def is_master(entry):
    return entry.data.get(CONF_ENTRY_TYPE) == TYPE_MASTER


async def async_setup_entry(hass, entry):
    """Set up Advanced Floor Heating (et rum eller Masteren)."""
    hass.data.setdefault(DOMAIN, {})

    # Gennemgang, rapport og forslag (én gang for hele integrationen)
    if REVIEW_KEY not in hass.data[DOMAIN]:
        from .review import ReviewManager, async_register_services
        manager = ReviewManager(hass)
        hass.data[DOMAIN][REVIEW_KEY] = manager
        await manager.async_start()
        async_register_services(hass)

    if is_master(entry):
        from .master import MasterHub
        hub = MasterHub(hass, entry)
        hass.data[DOMAIN][MASTER_KEY] = hub
        await hub.async_start()
        entry.async_on_unload(hub.async_stop)
        platforms = PLATFORMS_MASTER
    else:
        platforms = PLATFORMS_ROOM

    # Forward the setup to the platforms
    await hass.config_entries.async_forward_entry_setups(entry, platforms)

    # Listen for option updates (when you change PID settings in the UI)
    entry.async_on_unload(entry.add_update_listener(update_listener))

    return True


async def update_listener(hass, entry):
    """Handle options update and reload the entry automatically."""
    await hass.config_entries.async_reload(entry.entry_id)


async def async_unload_entry(hass, entry):
    """Unload a config entry and its platforms."""
    platforms = PLATFORMS_MASTER if is_master(entry) else PLATFORMS_ROOM
    unload_ok = await hass.config_entries.async_unload_platforms(entry, platforms)

    if unload_ok:
        hass.data[DOMAIN].pop(MASTER_KEY if is_master(entry) else entry.entry_id, None)

    return unload_ok

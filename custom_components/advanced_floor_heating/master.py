"""Master: husets tilstand (som i IHC), der sendes ud til alle rum."""
import logging

from homeassistant.helpers.dispatcher import async_dispatcher_send

from .const import (
    DOMAIN, MASTER_KEY, MODE_OCCUPIED, HOUSE_MODES,
    DEFAULT_UNOCCUPIED_TEMP, DEFAULT_FROST_TEMP, CONF_OUTDOOR_SENSOR,
)
from .helpers import MASTER_SIGNAL, ALARM_SIGNAL

_LOGGER = logging.getLogger(__name__)


class MasterHub:
    """Holder husets tilstand. Rummene laeser den, og faar besked, naar den aendres."""

    def __init__(self, hass, entry):
        self.hass = hass
        self.entry = entry
        self.mode = MODE_OCCUPIED
        self.unoccupied_temp = DEFAULT_UNOCCUPIED_TEMP
        self.frost_temp = DEFAULT_FROST_TEMP

    @property
    def outdoor_sensor(self):
        opts = self.entry.options
        if CONF_OUTDOOR_SENSOR in opts:
            return opts[CONF_OUTDOOR_SENSOR] or None
        return self.entry.data.get(CONF_OUTDOOR_SENSOR) or None

    def set_mode(self, mode, notify=True):
        if mode in HOUSE_MODES and mode != self.mode:
            self.mode = mode
            if notify:
                self.notify()

    def set_unoccupied_temp(self, value, notify=True):
        self.unoccupied_temp = float(value)
        if notify:
            self.notify()

    def set_frost_temp(self, value, notify=True):
        self.frost_temp = float(value)
        if notify:
            self.notify()

    def notify(self):
        """Giv alle rum besked om, at Masteren er aendret."""
        async_dispatcher_send(self.hass, MASTER_SIGNAL)

    def notify_alarms(self):
        async_dispatcher_send(self.hass, ALARM_SIGNAL)


def get_master(hass):
    """Returnerer Masteren, hvis den er oprettet."""
    return hass.data.get(DOMAIN, {}).get(MASTER_KEY)

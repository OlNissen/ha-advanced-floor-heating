"""Hjælpelogik uden for selve reguleringen: batteri, skimmelrisiko og sommerstop."""
import math

from .const import (
    BATTERY_LOW, BATTERY_OK, MOLD_FRSI, MOLD_ALARM_RH, MOLD_CLEAR_RH, MOLD_HOLD_MINUTES,
    SUMMER_TAU_HOURS, SUMMER_MIN_AGE_HOURS, SUMMER_HYSTERESIS,
)

# ---------------------------------------------------------------- batteri


def find_battery_entities(hass, entity_id):
    """Batteri-entiteter på samme enhed som `entity_id` (tom liste, hvis der ingen er)."""
    return _siblings(hass, entity_id, "battery", ("sensor", "binary_sensor"))


def find_sibling_temperature(hass, entity_id):
    """Temperaturføleren på samme enhed som `entity_id` (fx en fugtføler), ellers None."""
    found = _siblings(hass, entity_id, "temperature", ("sensor",))
    return found[0] if found else None


def find_device_entities(hass, entity_id):
    """Alle sensor-entiteter på samme enhed og om enheden har batteri (= trådløs batteriføler)."""
    everything = _siblings(hass, entity_id, None, ("sensor", "binary_sensor"))
    return everything, bool(_siblings(hass, entity_id, "battery", ("sensor", "binary_sensor")))


def silent_seconds(states, now_utc):
    """Sekunder siden den seneste ændring fra nogen af enhedens entiteter, eller None."""
    newest = None
    for state in states:
        if state is None or state.state in ("unknown", "unavailable"):
            continue
        seen = getattr(state, "last_reported", None) or state.last_updated
        if newest is None or seen > newest:
            newest = seen
    return None if newest is None else (now_utc - newest).total_seconds()


def _siblings(hass, entity_id, wanted_class, domains):
    try:
        from homeassistant.helpers import entity_registry as er
    except ImportError:
        return []
    registry = er.async_get(hass)
    entry = registry.async_get(entity_id)
    if entry is None or not entry.device_id:
        return []
    found = []
    for other in er.async_entries_for_device(registry, entry.device_id):
        device_class = other.device_class or other.original_device_class
        if (wanted_class is None or device_class == wanted_class) and other.entity_id.split(".")[0] in domains:
            found.append(other.entity_id)
    return found


def battery_low(state, entity_id, was_low):
    """(lavt?, procent eller None). Hysterese: lavt under BATTERY_LOW, i orden igen fra BATTERY_OK."""
    if state is None:
        return was_low, None
    if entity_id.startswith("binary_sensor."):
        if state.state == "on":
            return True, None
        if state.state == "off":
            return False, None
        return was_low, None
    try:
        level = float(state.state)
    except (TypeError, ValueError):
        return was_low, None
    limit = BATTERY_OK if was_low else BATTERY_LOW
    return level < limit, level


# ---------------------------------------------------------------- skimmelrisiko


def saturation_pressure(temp):
    """Mættet damptryk i hPa (Magnus-formlen)."""
    return 6.112 * math.exp(17.62 * temp / (243.12 + temp))


def surface_humidity(room_temp, humidity, outdoor_temp, frsi=MOLD_FRSI):
    """Relativ fugtighed på den koldeste ydervæg i %, efter DIN 4108-2 (temperaturfaktor fRsi)."""
    if None in (room_temp, humidity, outdoor_temp):
        return None
    surface = room_temp - max(0.0, room_temp - outdoor_temp) * (1.0 - frsi)
    return min(100.0, humidity * saturation_pressure(room_temp) / saturation_pressure(surface))


class MoldWatch:
    """Risikoen meldes, når væggen har været for fugtig i en periode, og afblæses under en lavere grænse."""

    def __init__(self):
        self.surface = None
        self.risk = False
        self._high_since = None

    def update(self, surface, now):
        """Returnerer "start", "stop" eller None."""
        self.surface = surface
        if surface is None:
            self._high_since = None
            return None
        if surface >= MOLD_ALARM_RH:
            if self._high_since is None:
                self._high_since = now
            if not self.risk and now - self._high_since >= MOLD_HOLD_MINUTES * 60:
                self.risk = True
                return "start"
            return None
        self._high_since = None
        if self.risk and surface < MOLD_CLEAR_RH:
            self.risk = False
            return "stop"
        return None


# ---------------------------------------------------------------- sommerstop


class SummerStop:
    """Glidende udetemperatur (ca. et døgn). Over grænsen stoppes varmen, med hysterese."""

    def __init__(self):
        self.limit = 0.0        # 0 = slået fra
        self.mean = None
        self.since = None       # epoch: første måling i middelværdien
        self.updated = None     # epoch: seneste måling
        self.active = False

    def add(self, outdoor, now):
        if outdoor is None:
            return
        if self.mean is None or self.updated is None or now - self.updated > SUMMER_TAU_HOURS * 3600:
            # Ingen eller for gammel historik: begynd forfra
            self.mean, self.since = float(outdoor), now
        else:
            weight = 1.0 - math.exp(-max(0.0, now - self.updated) / (SUMMER_TAU_HOURS * 3600))
            self.mean += weight * (float(outdoor) - self.mean)
        self.updated = now

    def evaluate(self, now):
        """Opdaterer og returnerer `active`. Kræver nogle timers historik, så én varm måling ikke stopper huset."""
        if self.limit <= 0 or self.mean is None or self.updated is None:
            self.active = False
        elif now - self.updated > SUMMER_TAU_HOURS * 3600:
            self.active = False    # udetemperaturen er væk: varm hellere end at gætte
        elif now - self.since < SUMMER_MIN_AGE_HOURS * 3600:
            self.active = False
        elif self.active:
            self.active = self.mean > self.limit - SUMMER_HYSTERESIS
        else:
            self.active = self.mean >= self.limit
        return self.active

    def as_dict(self):
        return {"mean": self.mean, "since": self.since, "updated": self.updated, "active": self.active}

    def restore(self, data):
        try:
            if data.get("mean") is not None:
                self.mean = float(data["mean"])
                self.since = float(data["since"])
                self.updated = float(data["updated"])
                self.active = bool(data.get("active"))
        except (AttributeError, KeyError, TypeError, ValueError):
            self.mean = self.since = self.updated = None
            self.active = False

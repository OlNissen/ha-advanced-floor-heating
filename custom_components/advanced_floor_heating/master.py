"""Master: husets tilstand (som i IHC), ude-temperatur, prognose og sol - sendes ud til alle rum."""
import logging
import time
from datetime import datetime, timedelta, timezone

from homeassistant.helpers.dispatcher import async_dispatcher_send
from homeassistant.helpers.event import async_track_time_interval, async_call_later

from .const import (
    DOMAIN, MASTER_KEY, MODE_OCCUPIED, HOUSE_MODES,
    DEFAULT_UNOCCUPIED_TEMP, DEFAULT_FROST_TEMP,
    CONF_OUTDOOR_SENSOR, CONF_WEATHER_ENTITY, CONF_FORECAST_HOURS, DEFAULT_FORECAST_HOURS,
    SOURCE_MEASURED, SOURCE_FORECAST, SOURCE_BOTH, OUTDOOR_SOURCES, DEFAULT_OUTDOOR_SOURCE,
    FORECAST_REFRESH_MINUTES, FORECAST_MAX_AGE_HOURS, SOLAR_FULL_ELEVATION,
    CONF_REVIEW_DAYS, DEFAULT_REVIEW_DAYS, CONF_ALLOW_AI_CHANGES,
    CONF_NOTIFY_IN_HA, CONF_NOTIFY_MOBILES,
    MODE_UNOCCUPIED, MODE_FROST, MODE_OFF, PREHEAT_MARGIN_HOURS, PREHEAT_MAX_HOURS, MASTER_TICK_MINUTES,
)
from .health import SummerStop
from .helpers import MASTER_SIGNAL, ALARM_SIGNAL, MASTER_VALUES_SIGNAL

_LOGGER = logging.getLogger(__name__)

# Skydaekke (%) ud fra vejr-tilstanden, hvis vejr-entiteten ikke har cloud_coverage
CONDITION_CLOUD = {
    "sunny": 0, "clear-night": 0, "partlycloudy": 50, "cloudy": 90, "fog": 90,
    "rainy": 100, "pouring": 100, "snowy": 100, "snowy-rainy": 100, "lightning": 100,
    "lightning-rainy": 100, "hail": 100, "windy": 40, "windy-variant": 70, "exceptional": 100,
}


def _num(value):
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _parse_dt(value):
    if isinstance(value, datetime):
        dt = value
    else:
        try:
            dt = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        except ValueError:
            return None
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def parse_forecast(items, now, hours):
    """Middeltemperatur og middel-skydaekke for de naeste `hours` timer.

    Time-prognoser: de punkter, der ligger i vinduet. Dags-prognoser (faa punkter): det foerste punkt
    (middel af temperature og templow, hvis den findes). Returnerer (temp, cloud) - None hvis intet.
    """
    end = now + timedelta(hours=hours)
    temps, clouds = [], []
    for it in items or []:
        dt = _parse_dt(it.get("datetime"))
        t = _num(it.get("temperature"))
        if dt is None or t is None:
            continue
        if now - timedelta(hours=1) < dt <= end:
            temps.append(t)
            c = _num(it.get("cloud_coverage"))
            if c is not None:
                clouds.append(c)
    if not temps:
        for it in items or []:
            t = _num(it.get("temperature"))
            if t is None:
                continue
            low = _num(it.get("templow"))
            temps.append((t + low) / 2 if low is not None else t)
            c = _num(it.get("cloud_coverage"))
            if c is not None:
                clouds.append(c)
            break
    if not temps:
        return None, None
    return sum(temps) / len(temps), (sum(clouds) / len(clouds) if clouds else None)


def solar_factor(elevation, cloud):
    """0..1: hvor meget sol der kommer ind (enkel model: solhoejde x klar himmel)."""
    if elevation is None or cloud is None:
        return 0.0
    height = max(0.0, min(1.0, elevation / SOLAR_FULL_ELEVATION))
    clear = max(0.0, min(1.0, 1.0 - cloud / 100.0))
    return round(height * clear, 3)


class MasterHub:
    """Holder husets tilstand, ude-kilde, prognose og sol. Rummene laeser den, og faar besked, naar den aendres."""

    def __init__(self, hass, entry):
        self.hass = hass
        self.entry = entry
        self.mode = MODE_OCCUPIED
        self.unoccupied_temp = DEFAULT_UNOCCUPIED_TEMP
        self.frost_temp = DEFAULT_FROST_TEMP
        self.source = DEFAULT_OUTDOOR_SOURCE
        self.forecast_temp = None
        self.forecast_cloud = None
        self.forecast_at = None     # datetime (UTC) for sidste vellykkede hentning
        self.forecast_type = None   # hourly / twice_daily / daily
        self._unsub = None
        self._retry_unsub = None
        self._retries = 0
        self._tick_unsub = None
        self.summer = SummerStop()
        self.return_at = None             # datetime (med tidszone): hvornår I er hjemme igen
        self.preheat_manual_hours = 0.0   # 0 = beregn ud fra rummenes varmemodeller

    # ---------------------------------------------------------------- indstillinger

    def _option(self, key):
        opts = self.entry.options
        if key in opts:
            return opts[key] or None
        return self.entry.data.get(key) or None

    @property
    def outdoor_sensor(self):
        return self._option(CONF_OUTDOOR_SENSOR)

    @property
    def weather_entity(self):
        return self._option(CONF_WEATHER_ENTITY)

    def _raw(self, key, default=None):
        opts = self.entry.options
        if key in opts:
            return opts[key]
        return self.entry.data.get(key, default)

    @property
    def notify_in_ha(self):
        value = self._raw(CONF_NOTIFY_IN_HA, True)
        return True if value is None else bool(value)

    @property
    def notify_mobiles(self):
        value = self._raw(CONF_NOTIFY_MOBILES, [])
        if not value:
            return []
        return [value] if isinstance(value, str) else [v for v in value if v]

    @property
    def review_days(self):
        value = _num(self._option(CONF_REVIEW_DAYS))
        return value if value else DEFAULT_REVIEW_DAYS

    @property
    def allow_ai_changes(self):
        return bool(self._option(CONF_ALLOW_AI_CHANGES))

    @property
    def forecast_hours(self):
        value = _num(self._option(CONF_FORECAST_HOURS))
        return value if value else DEFAULT_FORECAST_HOURS

    # --------------------------------------------------------------------- tilstand

    def set_mode(self, mode, notify=True):
        if mode in HOUSE_MODES and mode != self.mode:
            self.mode = mode
            if notify and mode in (MODE_OCCUPIED, MODE_OFF):
                self.return_at = None    # I er hjemme (eller varmen er slukket): ingen planlagt forvarmning
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

    def set_source(self, source, notify=True):
        if source in OUTDOOR_SOURCES and source != self.source:
            self.source = source
            if notify:
                self.notify_values()

    # ------------------------------------------------------------------ sommerstop

    @property
    def summer_active(self):
        return self.summer.active

    def set_summer_limit(self, value, notify=True):
        self.summer.limit = float(value)
        self.summer.add(self.outdoor_temp(), time.time())
        self.summer.evaluate(time.time())
        if notify:
            self.notify()

    def _update_summer(self, now):
        was = self.summer.active
        self.summer.add(self.outdoor_temp(), now)
        if self.summer.evaluate(now) == was:
            return
        from .notify import notify
        mean = self.summer.mean
        if self.summer.active:
            title = "Gulvvarme: sommerstop"
            text = (f"Det har i gennemsnit været {mean:.1f} °C ude det sidste døgn, så varmen holder pause "
                    f"(grænse {self.summer.limit:g} °C).")
        else:
            title = "Gulvvarme: sommerstop slut"
            text = "Varmen regulerer igen."
        notify(self.hass, "afh_summer", title, text)
        self.notify()

    # ------------------------------------------------------------ ferie og forvarmning

    @staticmethod
    def utcnow():
        return datetime.now(timezone.utc)

    def set_return_at(self, value, notify=True):
        """Planlagt hjemkomst. Et tidspunkt i fortiden annullerer planen."""
        self.return_at = value if value is not None and value > self.utcnow() else None
        if notify:
            self.notify_values()

    def rooms(self):
        return [o for o in self.hass.data.get(DOMAIN, {}).values() if hasattr(o, "preheat_hours")
                and hasattr(o, "_heater_switch")]

    def preheat_needed(self):
        """(timer før hjemkomst varmen skal tændes, rummet der bestemmer det eller None)."""
        if self.preheat_manual_hours > 0:
            return float(self.preheat_manual_hours), None
        slowest, hours = None, 0.0
        for room in self.rooms():
            need = room.preheat_hours()
            if need is not None and need > hours:
                slowest, hours = room.name, need
        return min(PREHEAT_MAX_HOURS, hours + PREHEAT_MARGIN_HOURS), slowest

    def preheat_start(self):
        """Tidspunktet hvor Masteren går tilbage til Beboet, eller None uden en aktiv ferieplan."""
        if self.return_at is None or self.mode not in (MODE_UNOCCUPIED, MODE_FROST):
            return None
        return self.return_at - timedelta(hours=self.preheat_needed()[0])

    def _update_vacation(self):
        start = self.preheat_start()
        if start is None or self.utcnow() < start:
            return
        from .notify import notify
        hours, slowest = self.preheat_needed()
        home = self.return_at.astimezone().strftime("%d-%m kl. %H:%M")
        self.set_mode(MODE_OCCUPIED)
        why = f" Langsomste rum er {slowest}." if slowest else ""
        notify(
            self.hass, "afh_preheat", "Gulvvarme: forvarmning startet",
            f"Huset er sat til Beboet, så det er varmt til hjemkomsten {home} "
            f"(ca. {hours:.0f} timers opvarmning).{why}",
        )

    async def async_tick(self, _now=None):
        self._update_summer(time.time())
        self._update_vacation()
        self.notify_values()

    def notify(self):
        """Giv alle rum besked om, at Masteren er aendret."""
        async_dispatcher_send(self.hass, MASTER_SIGNAL)
        async_dispatcher_send(self.hass, MASTER_VALUES_SIGNAL)

    def notify_values(self):
        """Kun sensorerne paa Masteren opdateres (ude-kilde/prognose aendret)."""
        async_dispatcher_send(self.hass, MASTER_VALUES_SIGNAL)

    def notify_alarms(self):
        async_dispatcher_send(self.hass, ALARM_SIGNAL)

    # -------------------------------------------------------------------- prognose

    async def async_start(self):
        """Hent prognosen nu og derefter jaevnligt, og hold øje med sommerstop og hjemkomst."""
        self._tick_unsub = async_track_time_interval(
            self.hass, self.async_tick, timedelta(minutes=MASTER_TICK_MINUTES)
        )
        if not self.weather_entity:
            return
        self.hass.async_create_background_task(
            self.async_refresh_forecast(), name="afh_forecast_first"
        )
        self._unsub = async_track_time_interval(
            self.hass, self.async_refresh_forecast, timedelta(minutes=FORECAST_REFRESH_MINUTES)
        )

    def async_stop(self):
        if self._tick_unsub:
            self._tick_unsub()
            self._tick_unsub = None
        if self._unsub:
            self._unsub()
            self._unsub = None
        if self._retry_unsub:
            self._retry_unsub()
            self._retry_unsub = None

    def _schedule_retry(self):
        """Vejr-entiteten er ofte ikke klar lige efter en genstart: prøv igen om 2 minutter (højst 6 gange)."""
        if self._retries >= 6 or self._retry_unsub is not None:
            return
        self._retries += 1

        async def _retry(_now=None):
            self._retry_unsub = None
            await self.async_refresh_forecast()

        self._retry_unsub = async_call_later(self.hass, 120, _retry)

    async def async_refresh_forecast(self, _now=None):
        entity = self.weather_entity
        if not entity:
            return
        items, used = [], None
        for ftype in ("hourly", "twice_daily", "daily"):
            try:
                resp = await self.hass.services.async_call(
                    "weather", "get_forecasts", {"entity_id": entity, "type": ftype},
                    blocking=True, return_response=True,
                )
            except Exception as err:  # noqa: BLE001 - typen understoettes ikke af alle vejr-entiteter
                _LOGGER.debug("Prognose %s fra %s: %s", ftype, entity, err)
                continue
            items = ((resp or {}).get(entity) or {}).get("forecast") or []
            if items:
                used = ftype
                break
        if not items:
            _LOGGER.warning("Ingen prognose fra %s - bruger den ikke", entity)
            self._schedule_retry()
            return
        now = datetime.now(timezone.utc)
        temp, cloud = parse_forecast(items, now, self.forecast_hours)
        if temp is None:
            self._schedule_retry()
            return
        self._retries = 0
        self.forecast_temp, self.forecast_cloud = temp, cloud
        self.forecast_at = now
        self.forecast_type = used
        self.notify_values()

    def _forecast_fresh(self):
        if self.forecast_at is None or self.forecast_temp is None:
            return False
        return datetime.now(timezone.utc) - self.forecast_at < timedelta(hours=FORECAST_MAX_AGE_HOURS)

    # ---------------------------------------------------------- ude-temp og sol

    def measured_temp(self):
        sensor = self.outdoor_sensor
        if not sensor:
            return None
        state = self.hass.states.get(sensor)
        return _num(state.state) if state is not None else None

    def forecast_temp_now(self):
        return self.forecast_temp if self._forecast_fresh() else None

    def outdoor_temp(self):
        """Den ude-temperatur rummene bruger, efter den valgte kilde. None hvis den mangler."""
        measured, forecast = self.measured_temp(), self.forecast_temp_now()
        if self.source == SOURCE_MEASURED:
            return measured
        if self.source == SOURCE_FORECAST:
            return forecast
        values = [v for v in (measured, forecast) if v is not None]
        return sum(values) / len(values) if values else None

    def _current_cloud(self):
        entity = self.weather_entity
        state = self.hass.states.get(entity) if entity else None
        if state is None:
            return None
        cloud = _num(state.attributes.get("cloud_coverage"))
        if cloud is None:
            cloud = CONDITION_CLOUD.get(state.state)
        return cloud

    def cloud_cover(self):
        current = self._current_cloud()
        forecast = self.forecast_cloud if self._forecast_fresh() else None
        if self.source == SOURCE_MEASURED:
            return current
        if self.source == SOURCE_FORECAST:
            return forecast if forecast is not None else current
        values = [v for v in (current, forecast) if v is not None]
        return sum(values) / len(values) if values else None

    def sun_elevation(self):
        state = self.hass.states.get("sun.sun")
        return _num(state.attributes.get("elevation")) if state is not None else None

    def solar(self):
        """0..1 (se solar_factor)."""
        return solar_factor(self.sun_elevation(), self.cloud_cover())


def get_master(hass):
    """Returnerer Masteren, hvis den er oprettet."""
    return hass.data.get(DOMAIN, {}).get(MASTER_KEY)

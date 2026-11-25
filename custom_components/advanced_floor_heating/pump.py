"""Pumpegruppe: pumpestyring (som IHC), pumpe-motion og shunt-råd for rum, der deler pumpe og shunt.

Pumpestyringen tænder pumpen, så snart en ventil (telestat) i gruppen åbner, og slukker den et par minutter
efter, at den sidste er lukket. Står pumpen stille for længe, motioneres den. Shunt-rådet kigger på, hvor åbne
ventilerne er, og siger til, når shuntens termostat bør skrues op eller ned.
"""
import logging
import math
import time
from datetime import datetime, timezone

from homeassistant.components import persistent_notification
from homeassistant.const import STATE_ON, STATE_OFF
from homeassistant.helpers.dispatcher import async_dispatcher_send
from homeassistant.helpers.event import (
    async_call_later, async_track_state_change_event, async_track_time_change, async_track_time_interval,
)
from homeassistant.helpers.storage import Store
from datetime import timedelta

from .const import (
    DOMAIN, CONF_GROUP_ROOMS, CONF_PUMP_SWITCHES, CONF_PUMP_FEEDBACK, CONF_SHUNT_SENSOR,
    CONF_PUMP_STOP_MINUTES, DEFAULT_PUMP_STOP_MINUTES, CONF_PUMP_MOTION_DAYS, DEFAULT_PUMP_MOTION_DAYS,
    PUMP_MOTION_MINUTES, PUMP_MOTION_HOUR, ADVICE_UP_HOURS, ADVICE_DOWN_HOURS, ADVICE_COOLDOWN_HOURS,
    ADVICE_OUTPUT_HIGH, ADVICE_OUTPUT_LOW, ADVICE_SHORT, ADVICE_FLOOR_HEADROOM, ADVICE_LOW_SHARE,
    EVENT_SHUNT_ADVICE, PRESET_ROOM_ONLY, PRESET_FLOOR_ONLY, MODE_OFF,
)
from .helpers import pump_signal
from .master import get_master

_LOGGER = logging.getLogger(__name__)

ADVICE_OK = "OK"
ADVICE_UP = "Skru op"
ADVICE_DOWN = "Skru ned"


def _as_list(value):
    if not value:
        return []
    if isinstance(value, str):
        return [value]
    return [v for v in value if v]


def _opt(entry, key, default=None):
    if key in entry.options:
        return entry.options[key]
    return entry.data.get(key, default)


def evaluate_advice(rooms):
    """Shunt-råd ud fra ventilerne i en gruppe. Returnerer (råd, sultne rum, antal rum, middel-udgang).

    "Skru op": mindst 40 % af rummene (og mindst 2) står på næsten 100 % og er under målet, og deres gulv har
    stadig plads til mere varme (ikke ved gulvgrænsen). "Skru ned": mindst 70 % af rummene har næsten
    lukkede ventiler, og ingen mangler varme.
    """
    starved, tot, low, outs = [], 0, 0, []
    for r in rooms:
        if r._attr_hvac_mode == "off" or r.house_mode == MODE_OFF:
            continue
        out = float(r._pid_signal)
        tot += 1
        outs.append(out)
        if out <= ADVICE_OUTPUT_LOW:
            low += 1
        ctrl = r._control_room_temp()
        floor = r._read_temp(r._floor_sensor)
        if floor is None:
            continue
        rs = (r.effective_room_target - ctrl) if ctrl is not None else 0.0
        fs = r.effective_floor_target - floor
        preset = r._attr_preset_mode
        if preset == PRESET_FLOOR_ONLY:
            short = fs
        elif preset == PRESET_ROOM_ONLY:
            short = rs
        else:
            short = max(rs, fs)
        headroom = floor < min(r._max_floor_temp - 1.0, r.effective_floor_target + ADVICE_FLOOR_HEADROOM)
        if out >= ADVICE_OUTPUT_HIGH and short >= ADVICE_SHORT and headroom and not r._frozen and not r.window_open:
            starved.append(r.name)
    need = max(2, math.ceil(0.4 * tot)) if tot else 2
    mean = round(sum(outs) / len(outs)) if outs else None
    if len(starved) >= need:
        return ADVICE_UP, starved, tot, mean
    if tot and not starved and low >= ADVICE_LOW_SHARE * tot:
        return ADVICE_DOWN, starved, tot, mean
    return ADVICE_OK, starved, tot, mean


class PumpGroupController:
    """Styrer pumpen for en gruppe rum og giver shunt-råd."""

    def __init__(self, hass, entry):
        self.hass = hass
        self.entry = entry
        self.entry_id = entry.entry_id
        self.name = entry.data["name"]
        self.enabled = True           # pumpestyring slået til (gendannes af kontakten)
        self.advice_enabled = True    # shunt-besked slået til
        self.motion_active = False
        self._stop_unsub = None
        self._stop_at = None
        self._motion_unsub = None
        self._unsubs = []
        self._tracked = set()
        self._track_unsub = None
        self.advice = ADVICE_OK
        self.advice_rooms = []
        self.mean_output = None
        self.rooms_regulating = 0
        self._advice_since = None
        self._last_notified = None
        self._store = Store(hass, 1, f"{DOMAIN}_pump_{entry.entry_id}")

    # ------------------------------------------------------------------ indstillinger

    def now(self):
        return time.time()

    @property
    def room_ids(self):
        return _as_list(_opt(self.entry, CONF_GROUP_ROOMS))

    @property
    def pump_switches(self):
        return _as_list(_opt(self.entry, CONF_PUMP_SWITCHES))

    @property
    def feedback(self):
        return _opt(self.entry, CONF_PUMP_FEEDBACK) or None

    @property
    def shunt_sensor(self):
        return _opt(self.entry, CONF_SHUNT_SENSOR) or None

    @property
    def stop_minutes(self):
        return float(_opt(self.entry, CONF_PUMP_STOP_MINUTES, DEFAULT_PUMP_STOP_MINUTES) or 0)

    @property
    def motion_days(self):
        return float(_opt(self.entry, CONF_PUMP_MOTION_DAYS, DEFAULT_PUMP_MOTION_DAYS) or 0)

    def rooms(self):
        """Regulatorerne for gruppens rum (kun dem der er indlæst)."""
        wanted = set(self.room_ids)
        return [
            o for o in self.hass.data.get(DOMAIN, {}).values()
            if getattr(o, "entity_id", None) in wanted and hasattr(o, "_heater_switch")
        ]

    def valve_switches(self):
        return [r._heater_switch for r in self.rooms()]

    # ------------------------------------------------------------------- livscyklus

    async def async_start(self):
        data = await self._store.async_load()
        if isinstance(data, dict):
            self._last_notified = data.get("last_notified")
        self._unsubs.append(async_track_time_interval(self.hass, self._async_tick, timedelta(minutes=1)))
        if self.motion_days > 0:
            self._unsubs.append(async_track_time_change(
                self.hass, self._async_motion_daily, hour=PUMP_MOTION_HOUR, minute=0, second=0))
        # Kort pause, så rummene når at blive indlæst, før vi læser ventilerne
        self._unsubs.append(async_call_later(self.hass, 20, self._async_startup))

    def async_stop(self):
        for unsub in self._unsubs:
            unsub()
        self._unsubs = []
        for attr in ("_stop_unsub", "_motion_unsub", "_track_unsub"):
            unsub = getattr(self, attr)
            if unsub:
                unsub()
                setattr(self, attr, None)

    def publish(self):
        async_dispatcher_send(self.hass, pump_signal(self.entry_id))

    # ---------------------------------------------------------------------- tilstand

    def _is_on(self, entity_id):
        state = self.hass.states.get(entity_id)
        return state is not None and state.state == STATE_ON

    def demand(self):
        """Mindst én ventil i gruppen er åben (telestat tændt)."""
        return any(self._is_on(sw) for sw in self.valve_switches())

    def pump_running(self):
        fb = self.feedback
        return self._is_on(fb) if fb else None

    def _pump_switches_on(self):
        return [sw for sw in self.pump_switches if self._is_on(sw)]

    def status(self):
        if not self.enabled:
            return "Styring slået fra"
        if self.motion_active:
            return "Pumpe-motion"
        if self.demand():
            return "Kald – pumpen kører"
        if self._stop_at is not None:
            left = max(0, math.ceil((self._stop_at - self.now()) / 60))
            return f"Efterløb (stopper om {left} min)"
        return "Står stille"

    # ---------------------------------------------------------------- pumpestyring

    async def _async_set_pump(self, on):
        targets = [sw for sw in self.pump_switches if self._is_on(sw) != on]
        if not targets:
            return
        await self.hass.services.async_call(
            "switch", "turn_on" if on else "turn_off", {"entity_id": targets}, blocking=False
        )

    def _cancel_stop(self):
        if self._stop_unsub:
            self._stop_unsub()
            self._stop_unsub = None
        self._stop_at = None

    async def async_update(self, _event=None):
        """Kaldes, når en ventil skifter, og jævnligt: tænd pumpen ved kald, sluk efter efterløb."""
        if self.enabled and not self.motion_active:
            if self.demand():
                self._cancel_stop()
                await self._async_set_pump(True)
            elif self._pump_switches_on() and self._stop_unsub is None:
                delay = self.stop_minutes * 60
                if delay <= 0:
                    await self._async_set_pump(False)
                else:
                    self._stop_at = self.now() + delay
                    self._stop_unsub = async_call_later(self.hass, delay, self._async_stop)
        self.publish()

    async def _async_stop(self, _now=None):
        self._stop_unsub = None
        self._stop_at = None
        if self.enabled and not self.motion_active and not self.demand():
            await self._async_set_pump(False)
        self.publish()

    async def _async_startup(self, _now=None):
        """Efter en genstart: tænd ved kald, ellers sluk straks (som IHC-automationen gjorde)."""
        self._resubscribe()
        if self.enabled:
            if self.demand():
                await self._async_set_pump(True)
            else:
                await self._async_set_pump(False)
        self.publish()

    def _resubscribe(self):
        """Lyt efter skift på gruppens ventiler (listen kan ændre sig, når rum indlæses)."""
        wanted = set(self.valve_switches())
        if wanted == self._tracked:
            return
        if self._track_unsub:
            self._track_unsub()
            self._track_unsub = None
        self._tracked = wanted
        if wanted:
            self._track_unsub = async_track_state_change_event(self.hass, list(wanted), self.async_update)

    async def async_set_enabled(self, enabled):
        self.enabled = bool(enabled)
        if self.enabled:
            await self.async_update()
        else:
            self._cancel_stop()
            self.publish()

    # --------------------------------------------------------------------- motion

    async def _async_motion_daily(self, _now=None):
        await self.async_run_motion(force=False)

    async def async_run_motion(self, force=False):
        """Kør pumpen i 5 minutter, så den ikke sætter sig. Automatisk kun hvis den ikke har kørt i `motion_days`."""
        if not self.enabled or self.motion_active or not self.pump_switches:
            return False
        if not force:
            days = self.motion_days
            fb = self.feedback
            state = self.hass.states.get(fb) if fb else None
            if days <= 0 or state is None or state.state != STATE_OFF:
                return False
            changed = state.last_changed
            age = (datetime.now(timezone.utc) - changed).total_seconds() if changed else 0
            if age <= days * 86400:
                return False
        _LOGGER.info("%s: kører pumpe-motion i %s min", self.name, PUMP_MOTION_MINUTES)
        self.motion_active = True
        self._cancel_stop()
        await self._async_set_pump(True)
        self._motion_unsub = async_call_later(self.hass, PUMP_MOTION_MINUTES * 60, self._async_motion_end)
        self.publish()
        return True

    async def _async_motion_end(self, _now=None):
        self._motion_unsub = None
        self.motion_active = False
        if self.enabled and not self.demand():
            await self._async_set_pump(False)
        self.publish()

    # ------------------------------------------------------------------- shunt-råd

    async def _async_tick(self, _now=None):
        self._resubscribe()
        await self.async_update()
        self.refresh_advice()

    def refresh_advice(self, now=None):
        """Beregn rådet, og send en besked, når det har holdt længe nok (højst én gang i døgnet)."""
        now = self.now() if now is None else now
        advice, starved, tot, mean = evaluate_advice(self.rooms())
        if advice != self.advice or self._advice_since is None:
            self._advice_since = now
        self.advice, self.advice_rooms, self.rooms_regulating, self.mean_output = advice, starved, tot, mean
        sent = False
        if self.advice_enabled and advice in (ADVICE_UP, ADVICE_DOWN):
            hours = ADVICE_UP_HOURS if advice == ADVICE_UP else ADVICE_DOWN_HOURS
            held = now - self._advice_since >= hours * 3600
            cooled = self._last_notified is None or now - self._last_notified >= ADVICE_COOLDOWN_HOURS * 3600
            if held and cooled:
                self._notify(advice, starved, mean)
                self._last_notified = now
                self._store.async_delay_save(lambda: {"last_notified": self._last_notified}, 5)
                sent = True
        self.publish()
        return sent

    def _notify(self, advice, starved, mean):
        shunt = self.shunt_sensor
        state = self.hass.states.get(shunt) if shunt else None
        temp = None
        if state is not None:
            try:
                temp = round(float(state.state), 1)
            except (TypeError, ValueError):
                temp = None
        hub = get_master(self.hass)
        outdoor = hub.outdoor_temp() if hub else None
        extra = (f" Fremløbet er nu {temp} °C." if temp is not None else "") + \
                (f" Ude: {round(outdoor, 1)} °C." if outdoor is not None else "")
        if advice == ADVICE_UP:
            title = f"Skru shunten i {self.name} OP"
            message = (
                f"Ventilerne i **{self.name}** er i snit {mean} % åbne, og rummene kommer ikke op på målet: "
                f"{', '.join(starved)}.\n\n**Drej shuntens termostat op med cirka 2 °C**, og vent et døgn, før du "
                f"vurderer igen.{extra} Vinylgulve stopper selv ved deres gulvgrænse."
            )
        else:
            title = f"Skru shunten i {self.name} NED"
            message = (
                f"Ventilerne i **{self.name}** er i snit kun {mean} % åbne, og rummene har det, de skal.\n\n"
                f"**Du kan skrue shuntens termostat ned med cirka 2 °C** (mildere vejr), så gulvene ikke bliver "
                f"varmere end nødvendigt.{extra}"
            )
        persistent_notification.async_create(
            self.hass, message, title=f"Gulvvarme: {title}", notification_id=f"afh_shunt_{self.entry_id}"
        )
        self.hass.bus.async_fire(EVENT_SHUNT_ADVICE, {"group": self.name, "advice": advice, "rooms": starved})

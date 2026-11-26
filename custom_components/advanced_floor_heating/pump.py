"""Pumpegruppe: pumpestyring (som IHC), pumpe-motion og shunt-råd for rum, der deler pumpe og shunt.

Pumpestyringen tænder pumpen, så snart en ventil (telestat) i gruppen åbner, og slukker den et par minutter
efter, at den sidste er lukket. Står pumpen stille for længe, motioneres den. Shunt-rådet kigger på, hvor åbne
ventilerne er, og siger til, når shuntens termostat bør skrues op eller ned.
"""
import logging
import math
import time
from datetime import datetime, timezone

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
    SUPPLY_MARGIN, SHUNT_BAND, SHUNT_STEP, COLOR_GREEN, COLOR_ORANGE, COLOR_RED, COLOR_GREY,
)
from .helpers import pump_signal
from .master import get_master
from .notify import notify

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
        if r._attr_hvac_mode == "off" or r.house_mode == MODE_OFF or getattr(r, "summer_stopped", False):
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


# ---------------------------------------------------------------- visning: zoner og status fra styringen


def _active(room):
    return not (room._attr_hvac_mode == "off" or room.house_mode == MODE_OFF
                or getattr(room, "summer_stopped", False))


def minimum_supply(rooms):
    """(mindste fremløb der kan varme gulvene, rummet der bestemmer det) eller (None, None)."""
    targets = [(r.effective_floor_target, r.name) for r in rooms if _active(r)]
    if not targets:
        return None, None
    target, name = max(targets)
    return round(target + SUPPLY_MARGIN, 1), name


def shunt_view(temp, minimum, advice, running):
    """Zoner til shuntens måler. Viseren står kun i grønt, når styringen mener, at fremløbet passer."""
    low, high = 15.0, 45.0
    if temp is not None:
        low, high = min(low, math.floor(temp) - 2), max(high, math.ceil(temp) + 3)

    def result(status, color, segments, green=(None, None)):
        return {"status": status, "farve": color, "min": low, "max": high, "segmenter": segments,
                "groen_fra": green[0], "groen_til": green[1]}

    grey = [{"from": low, "color": COLOR_GREY}]
    if temp is None or minimum is None:
        return result("Ingen data" if temp is None else "Ingen rum varmer", COLOR_GREY, grey)
    if not running:
        return result("Pumpen står stille", COLOR_GREY, grey)

    green_from, green_to = minimum, minimum + SHUNT_BAND
    if temp < minimum:
        status, color = "For koldt til at varme gulvet", COLOR_RED
    elif advice == ADVICE_UP:
        status, color = "Bør skrues op", COLOR_ORANGE
        green_from = max(minimum, temp + SHUNT_STEP)
        green_to = max(green_to, green_from + 3)
    elif advice == ADVICE_DOWN and temp - SHUNT_STEP >= minimum:
        status, color = "Bør skrues ned", COLOR_ORANGE
        green_to = max(minimum + 1, temp - SHUNT_STEP)
    elif advice == ADVICE_DOWN and temp < green_to:
        # Et trin ned ville være koldere, end gulvene kan varmes med
        status, color = "Passer · skru ikke lavere", COLOR_GREEN
    elif temp >= green_to:
        status, color = "Højere end nødvendigt", COLOR_ORANGE
    else:
        status, color = "Passer", COLOR_GREEN
    green_from, green_to = round(green_from, 1), round(max(green_to, green_from + 1), 1)
    high = max(high, math.ceil(green_to) + 3)

    segments = [{"from": low, "color": COLOR_RED}]
    if green_from > minimum:
        segments.append({"from": minimum, "color": COLOR_ORANGE})
    segments.append({"from": green_from, "color": COLOR_GREEN})
    segments.append({"from": green_to, "color": COLOR_ORANGE})
    return result(status, color, segments, (green_from, green_to))


def valve_view(advice, starved, regulating):
    """Farve til ventilmåleren: følger styringens råd, ikke faste procenter."""
    if not regulating:
        status, color = "Ingen rum varmer", COLOR_GREY
    elif advice == ADVICE_UP:
        status, color = "Skru op", COLOR_ORANGE
    elif advice == ADVICE_DOWN:
        status, color = "Skru ned", COLOR_ORANGE
    elif starved:
        status, color = f"OK · {len(starved)} mangler varme", COLOR_GREEN
    else:
        status, color = "OK", COLOR_GREEN
    return {"status": status, "farve": color, "segmenter": [{"from": 0, "color": color}]}


def room_report(rooms, starved):
    """Én linje pr. rum: hvad rummet laver, og farven der hører til."""
    out = []
    for r in sorted(rooms, key=lambda x: x.name):
        floor = r._read_temp(r._floor_sensor)
        status_text = getattr(r, "_regulation_status", "") or ""
        output = round(float(r._pid_signal))
        if r.alarms:
            status, color = r.alarms[0], COLOR_RED
        elif r._attr_hvac_mode == "off" or r.house_mode == MODE_OFF:
            status, color = "Slukket", COLOR_GREY
        elif getattr(r, "summer_stopped", False):
            status, color = "Sommerstop", COLOR_GREY
        elif floor is None:
            status, color = "Gulvføler mangler", COLOR_RED
        elif r._frozen:
            status, color = "Vindue åbent", COLOR_GREY
        elif status_text.startswith("Sikkerhedsstop"):
            status, color = "Gulv for varmt (stop)", COLOR_RED
        elif getattr(r, "_floor_limited", False):
            status, color = "Ved gulvgrænsen", COLOR_ORANGE
        elif r.name in starved:
            status, color = "Mangler varme", COLOR_ORANGE
        elif output <= 0:
            status, color = "Har varme nok", COLOR_GREEN
        else:
            status, color = "Varmer", COLOR_GREEN
        out.append({
            "navn": r.name, "status": status, "farve": color, "udgang": output,
            "gulv": None if floor is None else round(floor, 1), "gulv_max": r._max_floor_temp,
        })
    return out


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
        """Pumpens kontakter: de, rummene selv har valgt (pumpekontakt), plus evt. en fast liste på gruppen."""
        out = []
        for sw in [r._pump_switch for r in self.rooms()] + _as_list(_opt(self.entry, CONF_PUMP_SWITCHES)):
            if sw and sw not in out:
                out.append(sw)
        return out

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
            if hasattr(o, "_heater_switch")
            and (getattr(o, "entity_id", None) in wanted or getattr(o, "_pump_group", None) == self.entry_id)
        ]

    def valve_switches(self):
        return [r._heater_switch for r in self.rooms()]

    def supply_temp(self):
        """Shuntens fremløbstemperatur i °C, eller None hvis der ikke er en brugbar føler."""
        shunt = self.shunt_sensor
        state = self.hass.states.get(shunt) if shunt else None
        if state is None:
            return None
        try:
            return float(state.state)
        except (TypeError, ValueError):
            return None

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

    def views(self):
        """Alt, hvad dashboardets målere skal bruge."""
        rooms = self.rooms()
        minimum, deciding = minimum_supply(rooms)
        running = bool(self.demand() or self.motion_active or self._stop_at is not None)
        shunt = shunt_view(self.supply_temp(), minimum, self.advice, running)
        valves = valve_view(self.advice, self.advice_rooms, self.rooms_regulating)
        return {
            "mindste_fremloeb": minimum,
            "styrende_rum": deciding,
            "fremloeb_status": shunt["status"],
            "fremloeb_farve": shunt["farve"],
            "fremloeb_min": shunt["min"],
            "fremloeb_max": shunt["max"],
            "fremloeb_groen_fra": shunt["groen_fra"],
            "fremloeb_groen_til": shunt["groen_til"],
            "fremloeb_segmenter": shunt["segmenter"],
            "ventil_status": valves["status"],
            "ventil_farve": valves["farve"],
            "ventil_segmenter": valves["segmenter"],
            "rum": room_report(rooms, self.advice_rooms),
        }

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
        notify(self.hass, f"afh_shunt_{self.entry_id}", f"Gulvvarme: {title}", message)
        self.hass.bus.async_fire(EVENT_SHUNT_ADVICE, {"group": self.name, "advice": advice, "rooms": starved})

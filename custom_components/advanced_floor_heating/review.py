"""Gennemgang af indstillingerne: målinger, udsving, notifikationer, rapport og forslag.

Idéen: regulatoren måler løbende sin egen opførsel (fire tal pr. rum), foreslår en gennemgang, når der er
data nok, eller når et rum begynder at svinge, og giver en AI (eller dig) en kort rapport. Ændringer til
indstillingerne kommer som *forslag*, som du anvender med en knap - intet ændres uden dit ok.
"""
import logging
import time
from collections import deque
from datetime import datetime, timedelta, timezone

import voluptuous as vol
from homeassistant.components import persistent_notification
from homeassistant.helpers.event import async_track_time_interval
from homeassistant.helpers.storage import Store

from .const import (
    DOMAIN, REVIEW_KEY, DEFAULT_REVIEW_DAYS, REVIEW_REPEAT_DAYS,
    HUNT_WINDOW_HOURS, HUNT_BAND, HUNT_MIN_CROSSINGS, HUNT_MIN_OUTPUT_SWING,
    HUNT_NOTIFY_COOLDOWN_DAYS, HUNT_MIN_RUNNING_DAYS, EVENT_REVIEW,
    PARAM_BOUNDS, PARAM_MAX_FACTOR,
)
from .master import get_master

_LOGGER = logging.getLogger(__name__)

DAY = 86400.0
IN_BAND = 0.3   # grader: "tæt på målet" i rapporten


def _iso(epoch):
    return datetime.fromtimestamp(epoch, tz=timezone.utc).isoformat() if epoch else None


# ------------------------------------------------------------------------ målinger pr. rum

class RoomMetrics:
    """Rullende 24 timers målinger af ét rum (nulstilles ved genstart af HA)."""

    def __init__(self):
        self.samples = deque()    # (t, fejl, regulerings-temp, gulv, udgang, frosset)
        self.crossings = deque()  # tidspunkter hvor rummet skiftede fra for koldt til for varmt (eller omvendt)
        self._side = 0

    def _prune(self, now):
        limit = now - HUNT_WINDOW_HOURS * 3600
        while self.samples and self.samples[0][0] < limit:
            self.samples.popleft()
        while self.crossings and self.crossings[0] < limit:
            self.crossings.popleft()

    def add(self, now, error, ctrl_temp, floor, output, frozen=False):
        self.samples.append((now, error, ctrl_temp, floor, output, bool(frozen)))
        self._prune(now)
        if error > HUNT_BAND:
            side = 1
        elif error < -HUNT_BAND:
            side = -1
        else:
            side = self._side
        if self._side != 0 and side != 0 and side != self._side:
            self.crossings.append(now)
        self._side = side

    def reset_hunt(self):
        """Nyt setpunkt/ny tilstand giver naturlige udsving - de skal ikke tælle som svingning."""
        self.crossings.clear()
        self._side = 0

    def output_swing(self):
        outs = [s[4] for s in self.samples if not s[5]]
        return (max(outs) - min(outs)) if outs else 0.0

    def hunting(self):
        return len(self.crossings) >= HUNT_MIN_CROSSINGS and self.output_swing() >= HUNT_MIN_OUTPUT_SWING

    def summary(self, now):
        self._prune(now)
        n = len(self.samples)
        if not n:
            return {"samples": 0, "note": "ingen målinger endnu (nulstilles ved genstart)"}
        errs = [s[1] for s in self.samples]
        outs = [s[4] for s in self.samples]
        temps = [s[2] for s in self.samples if s[2] is not None]
        floors = [s[3] for s in self.samples if s[3] is not None]
        span = (self.samples[-1][0] - self.samples[0][0]) / 3600.0
        return {
            "samples": n,
            "span_hours": round(span, 1),
            "time_within_0_3_pct": round(100.0 * sum(1 for e in errs if abs(e) <= IN_BAND) / n),
            "time_too_cold_pct": round(100.0 * sum(1 for e in errs if e > IN_BAND) / n),
            "time_too_warm_pct": round(100.0 * sum(1 for e in errs if e < -IN_BAND) / n),
            "mean_output_pct": round(sum(outs) / n, 1),
            "min_output_pct": round(min(outs), 1),
            "max_output_pct": round(max(outs), 1),
            "output_swing": round(self.output_swing(), 1),
            "room_peak_to_peak": round(max(temps) - min(temps), 2) if temps else None,
            "floor_max": round(max(floors), 1) if floors else None,
            "frozen_pct": round(100.0 * sum(1 for s in self.samples if s[5]) / n),
            "crossings": len(self.crossings),
            "hunting": self.hunting(),
        }


# --------------------------------------------------------------- forslag: tjek og beskrivelse

def validate_params(climate, params):
    """Returnerer (accepterede, afviste). Grænser: se PARAM_BOUNDS og PARAM_MAX_FACTOR."""
    current = {
        "kp": climate._kp, "ki": climate._ki, "kd": climate._kd,
        "outdoor_ke": climate._ke, "solar_gain": climate._ks, "link_weight": climate._link_weight,
    }
    ok, rejected = {}, []
    for key, raw in params.items():
        if key not in PARAM_BOUNDS or raw is None:
            continue
        try:
            value = float(raw)
        except (TypeError, ValueError):
            rejected.append(f"{key}: ugyldig værdi")
            continue
        lo, hi = PARAM_BOUNDS[key]
        if not lo <= value <= hi:
            rejected.append(f"{key}: {value:g} ligger uden for {lo:g}-{hi:g}")
            continue
        cur = current[key]
        if key in ("kp", "ki", "kd") and cur > 0 and not (cur / PARAM_MAX_FACTOR <= value <= cur * PARAM_MAX_FACTOR):
            rejected.append(
                f"{key}: {cur:g} -> {value:g} er for stor en ændring på én gang "
                f"(højst faktor {PARAM_MAX_FACTOR:g}). Foreslå et mindre skridt."
            )
            continue
        if abs(value - cur) < 1e-9:
            continue
        ok[key] = value
    return ok, rejected


def describe(climate, params):
    cur = {
        "kp": climate._kp, "ki": climate._ki, "kd": climate._kd,
        "outdoor_ke": climate._ke, "solar_gain": climate._ks, "link_weight": climate._link_weight,
    }
    return ", ".join(f"{k} {cur[k]:g} → {v:g}" for k, v in params.items())


# ----------------------------------------------------------------------------- manageren

class ReviewManager:
    """Husker, hvornår systemet startede, foreslår gennemgange, og holder forslag fra AI."""

    def __init__(self, hass):
        self.hass = hass
        self._store = Store(hass, 1, f"{DOMAIN}_review")
        self.data = {
            "first_run": None, "last_review": None, "last_suggested": None,
            "hunt_notified": {}, "proposals": {}, "changes": [],
        }
        self._unsub = None

    # ------------------------------------------------------------------ livscyklus

    async def async_start(self):
        loaded = await self._store.async_load()
        if isinstance(loaded, dict):
            self.data.update(loaded)
        if not self.data.get("first_run"):
            self.data["first_run"] = time.time()
            await self._store.async_save(self.data)
        self._unsub = async_track_time_interval(self.hass, self._async_tick, timedelta(hours=1))

    def async_stop(self):
        if self._unsub:
            self._unsub()
            self._unsub = None

    def _save(self):
        self._store.async_delay_save(lambda: self.data, 5)

    # --------------------------------------------------------------- indstillinger

    @property
    def review_days(self):
        hub = get_master(self.hass)
        return hub.review_days if hub else DEFAULT_REVIEW_DAYS

    @property
    def allow_ai_changes(self):
        hub = get_master(self.hass)
        return bool(hub and hub.allow_ai_changes)

    def days_running(self, now=None):
        first = self.data.get("first_run")
        return ((now or time.time()) - first) / DAY if first else 0.0

    def rooms(self):
        return [o for o in self.hass.data.get(DOMAIN, {}).values() if hasattr(o, "_metrics")]

    # ------------------------------------------------------------------- notifikationer

    def _notify(self, notification_id, title, message, reason, rooms=None):
        persistent_notification.async_create(
            self.hass, message, title=title, notification_id=notification_id
        )
        self.hass.bus.async_fire(EVENT_REVIEW, {"reason": reason, "rooms": rooms or []})

    def _how_to(self):
        return (
            "\n\n**Sådan gør du:**\n"
            "1. Bed din AI-assistent (fx Claude) kalde servicen `advanced_floor_heating.get_report` "
            "og gennemgå resultatet.\n"
            "2. AI'en kan foreslå ændringer med `advanced_floor_heating.set_parameters`. Forslagene dukker op "
            "som en notifikation, og du bruger dem med knappen **Anvend Forslag** på rummet. "
            "Intet ændres, før du siger ok.\n\n"
            "Gulvgrænsen og vinduesreglen kan ikke ændres af AI."
        )

    async def _async_tick(self, _now=None):
        self.check(time.time())

    def check(self, now):
        """Tjek om en gennemgang bør foreslås. Returnerer listen af årsager (bruges i tests)."""
        reasons = []
        days = self.days_running(now)
        last_review = self.data.get("last_review")
        last_sug = self.data.get("last_suggested")

        if last_review is None and last_sug is None and days >= self.review_days:
            self._notify(
                "afh_review", "Gulvvarme: tid til en gennemgang",
                f"Gulvvarmen har kørt i {days:.0f} dage, så der er data nok til en første gennemgang "
                f"af indstillingerne." + self._how_to(),
                "first",
            )
            self.data["last_suggested"] = now
            reasons.append("first")
        elif last_review is not None and now - last_review >= REVIEW_REPEAT_DAYS * DAY \
                and (last_sug is None or now - last_sug >= REVIEW_REPEAT_DAYS * DAY):
            self._notify(
                "afh_review", "Gulvvarme: tid til en ny gennemgang",
                f"Der er gået {(now - last_review) / DAY:.0f} dage siden sidste gennemgang. "
                f"Vejret og årstiden har ændret sig, så indstillingerne kan trænge til et eftersyn." + self._how_to(),
                "periodic",
            )
            self.data["last_suggested"] = now
            reasons.append("periodic")

        # Rum der svinger
        if days >= HUNT_MIN_RUNNING_DAYS:
            for room in self.rooms():
                key = room.entity_id or room.name
                if not room._metrics.hunting() or getattr(room, "autotune_active", False):
                    continue
                notified = self.data["hunt_notified"].get(key)
                if notified and now - notified < HUNT_NOTIFY_COOLDOWN_DAYS * DAY:
                    continue
                m = room._metrics.summary(now)
                self._notify(
                    f"afh_hunt_{key}", f"Gulvvarme: {room.name} svinger",
                    f"**{room.name}** har de seneste {HUNT_WINDOW_HOURS} timer skiftet {m['crossings']} gange mellem "
                    f"for koldt og for varmt, og udgangen har svinget fra {m['min_output_pct']:.0f} % til "
                    f"{m['max_output_pct']:.0f} %. Det tyder på, at indstillingerne ikke passer helt til rummet.\n\n"
                    f"Forslag: en ny gennemgang af {room.name}." + self._how_to(),
                    "hunting", [key],
                )
                self.data["hunt_notified"][key] = now
                reasons.append(f"hunting:{key}")
        if reasons:
            self._save()
        return reasons

    # ------------------------------------------------------------------------ rapport

    def mark_reviewed(self, now=None):
        self.data["last_review"] = now or time.time()
        self._save()

    def build_report(self, mark_reviewed=True):
        now = time.time()
        hub = get_master(self.hass)
        rooms = []
        for r in self.rooms():
            a = r.extra_state_attributes
            rooms.append({
                "name": r.name,
                "entity_id": r.entity_id,
                "preset": a.get("preset_mode") or r._attr_preset_mode,
                "on": r._attr_hvac_mode != "off",
                "house_mode": a["house_mode"],
                "room_target": a["room_target_temperature"],
                "floor_target": a["floor_target_temperature"],
                "effective_room_target": a["effective_room_target"],
                "effective_floor_target": a["effective_floor_target"],
                "room_temperature": a["room_temperature"],
                "control_room_temperature": a["control_room_temperature"],
                "floor_temperature": a["floor_temperature"],
                "max_floor_temperature": a["max_floor_temperature"],
                "output_pct": a["control_output"],
                "regulation_status": a["regulation_status"],
                "pid": {"kp": a["kp"], "ki": a["ki"], "kd": a["kd"], "interval_s": a["pid_interval"],
                        "pwm_cycle_s": a["pwm_cycle_time"]},
                "feed_forward": {"outdoor_ke": a["outdoor_ke"], "solar_gain_ks": a["solar_gain"],
                                 "current_pct": a["pid_ff"]},
                "linked_rooms": a["linked_rooms"], "link_weight": a["link_weight"],
                "alarms": a["alarms"],
                "runtime_today_hours": r.runtime_today_hours,
                "window_open": a["window_open"],
                "last_24h": r._metrics.summary(now),
                "pending_proposal": self.data["proposals"].get(r.entity_id),
            })
        report = {
            "generated": _iso(now),
            "days_running": round(self.days_running(now), 1),
            "note": ("last_24h dækker de seneste 24 timer og nulstilles ved genstart af HA. "
                     "Længere historik ligger i HA's historik (recorder)."),
            "house": {
                "mode": hub.mode if hub else None,
                "outdoor_source": hub.source if hub else None,
                "outdoor_temperature": hub.outdoor_temp() if hub else None,
                "solar_pct": round(hub.solar() * 100) if hub else None,
                "unoccupied_temp": hub.unoccupied_temp if hub else None,
                "frost_temp": hub.frost_temp if hub else None,
            },
            "limits": {
                "can_change": sorted(PARAM_BOUNDS),
                "bounds": {k: list(v) for k, v in PARAM_BOUNDS.items()},
                "max_factor_per_proposal_for_pid": PARAM_MAX_FACTOR,
                "cannot_change": ["max floor temperature", "window rule", "valve exercise"],
                "direct_changes_allowed": self.allow_ai_changes,
            },
            "rooms": rooms,
            "recent_changes": self.data["changes"][-10:],
        }
        if mark_reviewed:
            self.mark_reviewed(now)
        return report

    # ---------------------------------------------------------------------- forslag

    def get_proposal(self, entity_id):
        return self.data["proposals"].get(entity_id)

    async def async_propose(self, climate, params, reason="", apply=False, source="AI"):
        """Gem et forslag (eller anvend det direkte, hvis Masteren tillader AI-ændringer)."""
        ok, rejected = validate_params(climate, params)
        result = {"entity_id": climate.entity_id, "rejected": rejected, "changes": ok}
        if not ok:
            result["status"] = "ingen gyldige ændringer"
            return result
        if apply and self.allow_ai_changes:
            await self._async_apply(climate, ok, reason, source)
            result["status"] = "anvendt"
            return result
        self.data["proposals"][climate.entity_id] = {
            "params": ok, "reason": reason, "source": source, "created": _iso(time.time()),
        }
        self._save()
        self.hass.bus.async_fire("advanced_floor_heating_proposal", {"entity_id": climate.entity_id, "params": ok})
        persistent_notification.async_create(
            self.hass,
            f"**{climate.name}:** {describe(climate, ok)}\n\n"
            + (f"Begrundelse: {reason}\n\n" if reason else "")
            + "Tryk **Anvend Forslag** på rummet for at bruge det, eller ignorér det. Intet er ændret endnu.",
            title=f"Gulvvarme: forslag til {climate.name}",
            notification_id=f"afh_proposal_{climate.entity_id}",
        )
        climate._publish()
        result["status"] = "foreslået (afventer dit ok)"
        if apply and not self.allow_ai_changes:
            result["note"] = "Direkte ændringer er slået fra på Masteren; forslaget venter på, at du trykker Anvend Forslag."
        return result

    async def async_apply_proposal(self, climate):
        prop = self.data["proposals"].get(climate.entity_id)
        if not prop:
            return False
        ok, rejected = validate_params(climate, prop["params"])
        if not ok:
            self.data["proposals"].pop(climate.entity_id, None)
            self._save()
            return False
        await self._async_apply(climate, ok, prop.get("reason", ""), prop.get("source", "AI"))
        return True

    async def async_discard_proposal(self, climate):
        if self.data["proposals"].pop(climate.entity_id, None) is not None:
            persistent_notification.async_dismiss(self.hass, f"afh_proposal_{climate.entity_id}")
            self._save()
            climate._publish()

    async def _async_apply(self, climate, params, reason, source):
        old = {
            "kp": climate._kp, "ki": climate._ki, "kd": climate._kd,
            "outdoor_ke": climate._ke, "solar_gain": climate._ks, "link_weight": climate._link_weight,
        }
        entry = {"time": _iso(time.time()), "room": climate.name, "entity_id": climate.entity_id,
                 "source": source, "reason": reason,
                 "old": {k: old[k] for k in params}, "new": dict(params)}
        self.data["changes"] = (self.data["changes"] + [entry])[-50:]
        self.data["proposals"].pop(climate.entity_id, None)
        self._save()
        _LOGGER.info("%s: indstillinger ændret (%s): %s", climate.name, source, describe(climate, params))
        persistent_notification.async_dismiss(self.hass, f"afh_proposal_{climate.entity_id}")
        await climate.async_apply_params(params)


# ----------------------------------------------------------------------------- services

def _find_climate(hass, entity_id):
    for obj in hass.data.get(DOMAIN, {}).values():
        if hasattr(obj, "_metrics") and obj.entity_id == entity_id:
            return obj
    return None


def async_register_services(hass):
    """Registrér get_report, set_parameters og discard_proposal (kun én gang)."""
    from homeassistant.core import SupportsResponse

    def manager():
        return hass.data[DOMAIN][REVIEW_KEY]

    async def handle_report(call):
        return manager().build_report(call.data.get("mark_reviewed", True))

    async def handle_set(call):
        data = call.data
        climate = _find_climate(hass, data["entity_id"])
        if climate is None:
            return {"status": "ukendt rum", "entity_id": data["entity_id"]}
        params = {k: data[k] for k in PARAM_BOUNDS if k in data}
        return await manager().async_propose(
            climate, params, reason=data.get("reason", ""), apply=data.get("apply", False)
        )

    async def handle_discard(call):
        climate = _find_climate(hass, call.data["entity_id"])
        if climate is not None:
            await manager().async_discard_proposal(climate)

    if hass.services.has_service(DOMAIN, "get_report"):
        return
    num = vol.Coerce(float)
    hass.services.async_register(
        DOMAIN, "get_report", handle_report,
        schema=vol.Schema({vol.Optional("mark_reviewed", default=True): bool}),
        supports_response=SupportsResponse.ONLY,
    )
    hass.services.async_register(
        DOMAIN, "set_parameters", handle_set,
        schema=vol.Schema({
            vol.Required("entity_id"): str,
            vol.Optional("kp"): num, vol.Optional("ki"): num, vol.Optional("kd"): num,
            vol.Optional("outdoor_ke"): num, vol.Optional("solar_gain"): num, vol.Optional("link_weight"): num,
            vol.Optional("reason", default=""): str,
            vol.Optional("apply", default=False): bool,
        }),
        supports_response=SupportsResponse.OPTIONAL,
    )
    hass.services.async_register(
        DOMAIN, "discard_proposal", handle_discard,
        schema=vol.Schema({vol.Required("entity_id"): str}),
    )

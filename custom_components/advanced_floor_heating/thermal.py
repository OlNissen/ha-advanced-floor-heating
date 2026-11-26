"""Lært varmemodel pr. rum: hvor hurtigt rummet varmer op, bruges til forvarmning før hjemkomst.

Modellen er  dT/dt = a * u(t - forsinkelse) - b * (T - ude)
hvor u er ventilens åbning (0..1), a er opvarmningen i °C pr. time ved fuld åbning, og b er varmetabet.
Den fittes med mindste kvadrater på 30-minutters vinduer. Den styrer IKKE reguleringen (PID'en er uændret).
"""
from .const import (
    THERMAL_WINDOW_MINUTES, THERMAL_MAX_WINDOWS, THERMAL_MAX_DELAY_WINDOWS, THERMAL_MIN_WINDOWS,
    THERMAL_MIN_HEATING, THERMAL_MIN_IDLE, THERMAL_FALLBACK_RATE, PREHEAT_MAX_HOURS,
)

WINDOW_S = THERMAL_WINDOW_MINUTES * 60
WINDOW_H = THERMAL_WINDOW_MINUTES / 60.0


class ThermalModel:
    def __init__(self):
        self.windows = []    # [start_epoch, u_middel, t_start, t_slut, ude_middel eller None]
        self._open = None
        self._fit = None
        self._dirty = True

    # ------------------------------------------------------------ indsamling

    def interrupt(self):
        """Smid det igangværende vindue væk (vindue åbent, føler mangler, autotune ...)."""
        self._open = None

    def add(self, now, output, temp, outdoor):
        """Et målepunkt. Returnerer True, når et helt vindue netop er blevet gemt."""
        if temp is None:
            self.interrupt()
            return False
        cur = self._open
        if cur is not None and now - cur["last"] > WINDOW_S / 2:
            cur = self._open = None    # hul i målingerne
        if cur is None:
            self._open = {"start": now, "last": now, "t0": temp, "u": 0.0, "dur": 0.0, "out": 0.0, "outdur": 0.0,
                          "prev_u": output, "prev_out": outdoor}
            return False
        dt = now - cur["last"]
        # Udgangen siden sidste punkt var den, der blev målt dér
        cur["u"] += cur["prev_u"] * dt
        cur["dur"] += dt
        if cur["prev_out"] is not None:
            cur["out"] += cur["prev_out"] * dt
            cur["outdur"] += dt
        cur["last"], cur["prev_u"], cur["prev_out"] = now, output, outdoor
        if now - cur["start"] < WINDOW_S:
            return False
        mean_u = max(0.0, min(1.0, cur["u"] / cur["dur"] / 100.0))
        mean_out = cur["out"] / cur["outdur"] if cur["outdur"] > 0 else None
        hours = (now - cur["start"]) / 3600.0
        # Normaliser ændringen til præcis en vindueslængde
        t_end = cur["t0"] + (temp - cur["t0"]) * WINDOW_H / hours
        self.windows.append([round(cur["start"]), round(mean_u, 3), round(cur["t0"], 3), round(t_end, 3),
                             None if mean_out is None else round(mean_out, 2)])
        del self.windows[:-THERMAL_MAX_WINDOWS]
        self._open = {"start": now, "last": now, "t0": temp, "u": 0.0, "dur": 0.0, "out": 0.0, "outdur": 0.0,
                      "prev_u": output, "prev_out": outdoor}
        self._dirty = True
        return True

    # ------------------------------------------------------------ fit

    def _rows(self, delay):
        rows = []
        w = self.windows
        for k in range(delay, len(w)):
            now_w, past = w[k], w[k - delay]
            # Der må ikke være hul mellem det forsinkede vindue og dette
            if now_w[0] - past[0] > delay * WINDOW_S * 1.2 + WINDOW_S * 0.2:
                continue
            if now_w[4] is None:
                continue
            y = (now_w[3] - now_w[2]) / WINDOW_H
            loss = (now_w[2] + now_w[3]) / 2 - now_w[4]
            rows.append((past[1], -loss, y))
        return rows

    @staticmethod
    def _solve(rows):
        s11 = sum(r[0] * r[0] for r in rows)
        s22 = sum(r[1] * r[1] for r in rows)
        s12 = sum(r[0] * r[1] for r in rows)
        s1y = sum(r[0] * r[2] for r in rows)
        s2y = sum(r[1] * r[2] for r in rows)
        det = s11 * s22 - s12 * s12
        if s11 <= 0:
            return None
        if det > 1e-9:
            a = (s1y * s22 - s2y * s12) / det
            b = (s2y * s11 - s1y * s12) / det
        else:
            a, b = s1y / s11, 0.0
        if b < 0:    # negativt varmetab giver ingen mening
            a, b = s1y / s11, 0.0
        sse = sum((r[2] - a * r[0] - b * r[1]) ** 2 for r in rows) / len(rows)
        return a, b, sse

    def fit(self):
        """dict(gain, loss, delay_h, windows) eller None, så længe der ikke er data nok."""
        if not self._dirty:
            return self._fit
        self._dirty = False
        best = None
        for delay in range(0, THERMAL_MAX_DELAY_WINDOWS + 1):
            rows = self._rows(delay)
            if len(rows) < THERMAL_MIN_WINDOWS:
                continue
            if sum(1 for r in rows if r[0] >= 0.5) < THERMAL_MIN_HEATING:
                continue
            if sum(1 for r in rows if r[0] <= 0.1) < THERMAL_MIN_IDLE:
                continue
            solved = self._solve(rows)
            if solved is None or not 0.02 <= solved[0] <= 5.0:
                continue
            if best is None or solved[2] < best[0]:
                best = (solved[2], solved[0], solved[1], delay, len(rows))
        self._fit = None if best is None else {
            "gain": round(best[1], 3), "loss": round(best[2], 4),
            "delay_h": round(best[3] * WINDOW_H, 1), "windows": best[4],
        }
        return self._fit

    # ------------------------------------------------------------ forvarmning

    def preheat_hours(self, temp, target, outdoor):
        """Timer med fuld varme fra `temp` til `target`. Uden lært model bruges en forsigtig fast hastighed."""
        if temp is None or target is None or target - temp <= 0.2:
            return 0.0
        model = self.fit()
        if model is None or outdoor is None:
            return min(PREHEAT_MAX_HOURS, (target - temp) / THERMAL_FALLBACK_RATE)
        value, hours = temp, 0.0
        while hours < PREHEAT_MAX_HOURS:
            heat = model["gain"] if hours >= model["delay_h"] else 0.0
            value += WINDOW_H * (heat - model["loss"] * (value - outdoor))
            hours += WINDOW_H
            if value >= target - 0.2:
                return hours
        return float(PREHEAT_MAX_HOURS)

    # ------------------------------------------------------------ lagring

    def as_dict(self):
        return {"windows": self.windows}

    def restore(self, data):
        windows = (data or {}).get("windows") or []
        self.windows = [list(w) for w in windows if isinstance(w, (list, tuple)) and len(w) == 5]
        del self.windows[:-THERMAL_MAX_WINDOWS]
        self._dirty = True

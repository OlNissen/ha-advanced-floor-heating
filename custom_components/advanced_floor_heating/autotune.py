"""Autotune af PID via relæ-feedback (Åström-Hägglund).

Ingen Home Assistant-afhængigheder, så modulet kan testes alene.

Princip: i stedet for PID'en skifter udgangen mellem et højt og et lavt niveau
(bias +/- d), alt efter om temperaturen er under eller over setpunktet (med et
støjbånd/hysterese). Temperaturen begynder så at svinge. Af svingningens
amplitude (a) og periode (Pu) beregnes processens ultimative forstærkning
Ku = 4d / (pi * a), og PI-parametre findes med en tuning-regel.

Gulvvarme er meget træg, så en kørsel varer typisk mange timer.
"""
import math

# (faktor på Ku for Kp, faktor på Pu for Ti)
RULES = {
    # Standard. I simulering af gulvvarme: lille overshoot og rolig indsvingning.
    "ziegler-nichols": (0.45, 1.0 / 1.2),
    # Mere forsigtig (langsommere integral) - vælg den, hvis gulvet bliver for varmt.
    "tyreus-luyben": (1.0 / 3.2, 2.2),
}
DEFAULT_RULE = "ziegler-nichols"

# Skal passe til konstanterne i climate.py (PID-formlen i integrationen)
I_TIME = 9000.0


def pid_params_from(ku, pu, rule=DEFAULT_RULE):
    """Omregn Ku/Pu (sekunder) til integrationens Kp og Ki (Kd = 0, ren PI).

    Integrationens I-led: I = Ki * sum(e * dt / 9000)  =>  Ti = 9000 * Kp / Ki.
    """
    kp_f, ti_f = RULES[rule]
    kp = ku * kp_f
    ti = pu * ti_f
    ti = max(600.0, min(40000.0, ti))
    kp = max(1.0, min(500.0, kp))
    ki = max(0.01, min(1000.0, I_TIME * kp / ti))
    return round(kp, 1), round(ki, 2), 0.0, round(ti)


class RelayAutoTuner:
    """Relæ-autotuner. Kald update(pv, t) med faste intervaller; den returnerer udgangen i %."""

    STATE_HEAT = "heat"
    STATE_COOL = "cool"

    def __init__(self, setpoint, bias, step=30.0, noiseband=0.2,
                 rule=DEFAULT_RULE, min_cycles=3, max_seconds=24 * 3600,
                 stuck_seconds=5 * 3600):
        if rule not in RULES:
            raise ValueError(f"Ukendt regel: {rule}")
        self.setpoint = float(setpoint)
        self.noiseband = float(noiseband)
        self.rule = rule
        self.min_cycles = int(min_cycles)
        self.max_seconds = float(max_seconds)
        self.stuck_seconds = float(stuck_seconds)

        bias = max(15.0, min(85.0, float(bias)))
        d = max(5.0, min(float(step), bias, 100.0 - bias))
        self.bias = bias
        self.d = d
        self.out_hi = bias + d
        self.out_lo = bias - d

        self.state = None
        self.output = self.out_lo
        self.started = None
        self.finished = False
        self.failed = None
        self.result = None

        self._extreme = None
        self._state_since = None
        self._peaks = []     # (tid, værdi)
        self._troughs = []
        self._heat_starts = []  # tidspunkter hvor vi skifter til varme
        self.cycles = 0

    # ------------------------------------------------------------------ status
    @property
    def active(self):
        return not self.finished and self.failed is None

    def progress_text(self):
        if self.failed:
            return f"Autotune fejlede: {self.failed}"
        if self.finished:
            r = self.result
            return (f"Autotune færdig: Kp {r['kp']}, Ki {r['ki']} "
                    f"(Ku {r['ku']}, periode {r['period_min']} min, amplitude {r['amplitude']} °C)")
        fase = "varmer" if self.state == self.STATE_HEAT else "køler"
        return f"Autotune: {fase} (svingning {len(self._peaks)}/{self.min_cycles + 1})"

    # ------------------------------------------------------------------ kerne
    def update(self, pv, t):
        """Behandl en måling (pv i °C, t i sekunder). Returnerer udgang i %."""
        if not self.active:
            return self.output
        if self.started is None:
            self.started = t
        if t - self.started > self.max_seconds:
            self.failed = "tidsgrænsen blev nået uden stabil svingning"
            return self.output

        sp, nb = self.setpoint, self.noiseband

        if self.state is None:
            self.state = self.STATE_HEAT if pv < sp else self.STATE_COOL
            self._extreme = pv
            self._state_since = t
            if self.state == self.STATE_HEAT:
                self._heat_starts.append(t)

        # Sidder fast i samme tilstand: bias passer ikke -> flyt udgangsniveauerne
        if t - self._state_since > self.stuck_seconds:
            if not self._shift_bias(up=(self.state == self.STATE_HEAT)):
                return self.output
            self._state_since = t

        if self.state == self.STATE_HEAT:
            self._extreme = min(self._extreme, pv)  # bund-kandidat
            if pv > sp + nb:
                self._troughs.append((t, self._extreme))
                self.state = self.STATE_COOL
                self._state_since = t
                self._extreme = pv
        else:
            self._extreme = max(self._extreme, pv)  # top-kandidat
            if pv < sp - nb:
                self._peaks.append((t, self._extreme))
                self.state = self.STATE_HEAT
                self._state_since = t
                self._extreme = pv
                self._heat_starts.append(t)
                self._evaluate()

        self.output = self.out_hi if self.state == self.STATE_HEAT else self.out_lo
        return self.output

    def _shift_bias(self, up):
        """Flyt begge udgangsniveauer op/ned. Returnerer False hvis det ikke kan lade sig gøre."""
        if up:
            if self.out_hi >= 99.9:
                self.failed = "setpunktet nås ikke, selv med fuld effekt"
                return False
            shift = min(self.d, 100.0 - self.out_hi)
        else:
            if self.out_lo <= 0.1:
                self.failed = "temperaturen er over setpunktet, selv uden varme"
                return False
            shift = -min(self.d, self.out_lo)
        self.bias += shift
        self.out_hi += shift
        self.out_lo += shift
        # Processen er ikke kendt endnu - start målingen forfra
        self._peaks, self._troughs, self._heat_starts = [], [], []
        return True

    def _evaluate(self):
        """Tjek om svingningen er stabil nok til at beregne parametre."""
        # Første svingning er opstart og kasseres
        peaks = [p[1] for p in self._peaks[1:]]
        troughs = [x[1] for x in self._troughs[1:]]
        starts = self._heat_starts[1:]
        n = self.min_cycles
        if len(peaks) < n or len(troughs) < n or len(starts) < n + 1:
            return
        peaks, troughs, starts = peaks[-n:], troughs[-n:], starts[-(n + 1):]
        periods = [starts[i + 1] - starts[i] for i in range(n)]
        amps = [(p - x) / 2.0 for p, x in zip(peaks, troughs[:len(peaks)])]

        def stabil(vals, tol=0.2):
            m = sum(vals) / len(vals)
            return m > 0 and all(abs(v - m) <= tol * m for v in vals)

        if not (stabil(periods) and stabil(amps)):
            return

        a = sum(amps) / len(amps)
        pu = sum(periods) / len(periods)
        if a <= self.noiseband * 1.05:
            self.failed = "svingningen er for lille i forhold til støjbåndet (øg udgangstrin)"
            return
        ku = 4.0 * self.d / (math.pi * a)
        kp, ki, kd, ti = pid_params_from(ku, pu, self.rule)
        self.cycles = n
        self.result = {
            "kp": kp, "ki": ki, "kd": kd, "ti_sek": ti,
            "ku": round(ku, 1), "period_min": round(pu / 60.0),
            "amplitude": round(a, 2), "bias": round(self.bias, 1),
            "rule": self.rule,
        }
        self.finished = True

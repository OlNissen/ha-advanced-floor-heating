# Hvad kan vi lære af andre gulvvarmeløsninger?

Undersøgt natten til 25. nov. 2026. Kilderne er læst af hjælpe-agenter og opsummeret; tal og påstande er ikke efterprøvet af os, medmindre det står. Danfoss Ally (403) og Thermozona kunne ikke læses. Skriv, hvis du har en direkte adresse.

## 1. smart-gulvvarme.dk

**Hvad det er:** Hardware + skytjeneste + app, der **erstatter** gulvvarmestyringen. Trådløse rumsensorer (luft + fugt, 299 kr.), en styreboks med 16 telestat-udgange og et pumperelæ (1.999 kr.), abonnement 348 kr./år (6 mdr. gratis). Telestater og shunt beholdes.

**Styringen:** Ingen PID. En AI-model pr. rum lærer af rummets målinger, udetemperatur, skydække, sol og vind samt vejrudsigten og fordeler varmen som *minutter pr. time* ("effekt i procent"). Første model efter ca. 4 uger, stabil efter 6–8 uger. Uden abonnement er det en almindelig reaktiv rumstyring. Beregningen sker i skyen.

**Hvad de har, som vi har:** ventilmotion (automatisk), pumpen kun ved behov, telestater styret i tid (puls), frostsikring som nødfunktion.

**Hvad de ikke har (men vi har):** gulvtemperaturgrænse (de måler kun luft!), vindues-/dørkontakter, lokal styring uden internet, setpunkter pr. zone, autotune, åben tilstand/API til alt.

**Åbent API:** REST (`api.smart-gulvvarme.dk/v1`) med API-nøgle; felterne ligner HA's `climate`. Ikke relevant for os, medmindre vi købte deres boks.

**Det værd at tage med:** (a) *forudsigende* forvarmning efter vejrudsigten, (b) at vise effekt som "minutter pr. time", (c) offline-/batterialarmer. Resten er et andet produkt end vores.

## 2. Andre løsninger til Home Assistant

| Projekt | Det særlige |
|---|---|
| [lnagel/hass-ufh-controller](https://github.com/lnagel/hass-ufh-controller) (HACS, HA 2026.3+) | Bygget til vandbåren gulvvarme. Tidsbudget pr. zone i 2-timers perioder (ingen hurtig PWM), modelleret ventilåbning (~210 s), minimum kørselstid (540 s), varmekald kun fra åbne zoner, pumpelås, varmekurve efter udetemperatur, sommer-/flush-tilstand, degradering ved sensorfejl, simuleringstests. **Mangler:** gulvgrænse, ventilmotion, frostsikring, autotune. |
| [vindaalex/multizone-thermostat](https://github.com/vindaalex/multizone-thermostat) (YAML) | PID + vejrkurve, master/satellit-zoner, passiv ventilmotion (kl. 02:00), vindue via temperaturfald. Ingen autotune. |
| alex-military/multizone-thermostat v3 (forum) | 100 % UI. Presets (Eco/Comfort/Sleep/Away), geofencing, frostvagt, primær/sekundær zone (kun primære kalder pumpe/kedel), anti-seize om sommeren, *stuck-valve-alarm* (45 min uden temperaturfald), kortcykling-alarm (>5 cyklusser/t), selvlærende varmetab. |
| [ScratMan/HASmartThermostat](https://github.com/ScratMan/HASmartThermostat) | Samme PID-formler som vores. Autotune med 7 regler (vi har 2), udekompensation `ke`, `sensor_stall` (død føler → fast lavt output), min. til/fra-tider, kaskade rum→gulv. README siger selv, at autotune ikke altid virker. |
| Homey-app "Smart Gulvvarme" | Cloud, vejrudsigtsbaseret, boost med gendannelse, manuel effekt, sensor-helbred. |

## 3. Hvad vi allerede er bedre til

Gulvtemperaturgrænse (kun vi og ScratMan-kaskaden har noget lignende), vindues-/dørkontakter med frossen udgang, ventilmotion som IHC (3×10 min), autotune (relæ), pumpestyring i grupper, lokal drift uden sky, kort med graf og popup, og fire driftstilstande (rum/gulv/1/begge).

## 4. Forslag til os, i rækkefølge

| # | Forslag | Hvorfor | Indsats |
|---|---|---|---|
| 1 | **PWM tilpasset termomotorer:** cyklus 30 min (som IHC), minimum tændetid ca. 5–9 min, spring små pulser over, og forskyd rummenes cyklusser | Telestater bruger ~3–4 min på at åbne/lukke. Vores 30 sekunders cyklus når aldrig at åbne ventilen helt. IHC kørte 30 min. hass-ufh bruger min. 540 s. | lille |
| 2 | **Frostsikring og sensor-fallback:** min. temperatur (IHC: 16 °C) også når et rum er slukket; "gammel" føler (ingen opdatering i X timer) → sikkert lavt output i stedet for at holde eller slukke | Sikkerhed. IHC havde det, vi har det ikke. | lille |
| 3 | **Hus-tilstande Beboet / Ubeboet / Slukket** (+ Ferie) som i IHC, med setpunkt pr. tilstand, drevet af de eksisterende `input_select`-vælgere | Det du brugte før, og det der gør "Ubeboet 19 °C" muligt uden at røre 11 rum | mellem |
| 4 | **Udekompensation (feed-forward):** `ke · (mål − ude)` oven på PID, med `sensor.ude_temp_temperature`; evt. varmekurve til shunten | Aflaster integralet, mindre pendling. Kræver at vi ved, hvem der styrer shunten i dag. | mellem |
| 5 | **Diagnostik/alarmer:** stuck-valve (ingen temperaturstigning efter 45 min ved fuld effekt), kortcykling, dagens driftstid pr. rum, "føler gammel" | Opdager fejl, før du gør | lille–mellem |
| 6 | **Lastfordeling:** begræns samtidigt åbne kredse / forskyd faser, så 11 kredse ikke sulter fremløbet | Hjælper shunt og pumper | mellem |
| 7 | **Forudsigende forvarmning** efter vejrudsigt + lært opvarmningstid pr. rum | Størst komfortgevinst på sigt (smart-gulvvarme.dk's kerne), men kræver ugers data | stor |
| 8 | **Simuleringstests i repoet** (som hass-ufh): vores rum-simulering fra autotunen gøres til faste tests | Tryghed ved ændringer | lille |

**Ikke værd at kopiere:** skybaseret AI og abonnement, tidsplaner/natsænkning (gulvet er for træg), vindue via temperaturfald (vi har kontakter).

## 5. Anbefaling

Start med **1 og 2** (sikkerhed og det, der passer bedst til termomotorer). Derefter **3** (så Ubeboet/Slukket virker igen), så **4** og **5**. **7** venter, til vi har ugers data.

## Kilder

- [smart-gulvvarme.dk](https://smart-gulvvarme.dk/), [Sådan virker det](https://smart-gulvvarme.dk/saadan-virker-gulvvarmestyring), [API](https://smart-gulvvarme.dk/api-docs), [FAQ](https://smart-gulvvarme.dk/ofte-stillede-sporgsmal)
- [Homey: Smart Gulvvarme](https://homey.app/da-dk/app/dk.smartgulvvarme/)
- [lnagel/hass-ufh-controller](https://github.com/lnagel/hass-ufh-controller), [forumtråd](https://community.home-assistant.io/t/underfloor-heating-controller/977236)
- [vindaalex/multizone-thermostat](https://github.com/vindaalex/multizone-thermostat), [Multizone Thermostat v3 (forum)](https://community.home-assistant.io/t/multizone-thermostat-v3-smart-pid-pwm-geofencing-100-ui-no-yaml/1018712)
- [ScratMan/HASmartThermostat](https://github.com/ScratMan/HASmartThermostat)

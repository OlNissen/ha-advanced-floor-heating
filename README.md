# Advanced Floor Heating til Home Assistant ♨️

PID-baseret varmestyring til **gulvvarme** (træge systemer, f.eks. IHC med termomotorer/telestater). Hvert rum får sin egen regulator, der styrer efter **rumtemperatur og/eller gulvtemperatur**, så gulvet aldrig bliver for varmt.

## ✨ Funktioner

- **Ét rum = én regulator.** Tilføj integrationen igen for hvert rum – der skal ikke kopieres kode.
- **Rum- og gulvføler i samme regulator** med 4 driftstilstande (preset):
  - `Room Only` – regulerer kun på rumtemperaturen
  - `Floor Only` – regulerer kun på gulvtemperaturen
  - `Room & Floor (1 Met)` – stopper, når det første mål er nået (komfort)
  - `Room & Floor (Both Met)` – stopper først, når begge mål er nået
- **PID med anti-windup** og **PWM-udgang** (kontakten tændes/slukkes i cyklusser).
- **Vinduesregel (valgfri):** er vinduet åbent, **fryses udgangen**, så der ikke reguleres efter den (kolde) rumtemperatur. Se [Vinduesregel](#-vinduesregel).
- **Maks. gulvtemperatur** pr. rum – varmen slukkes automatisk over grænsen.
- **Gendanner tilstand** efter genstart af Home Assistant (måltemperaturer, preset, PID-integral og udgang).
- **Dashboard til alle rum** i én visning ([se nedenfor](#-dashboard-til-alle-rum)).

> Der er med vilje **ingen tidsplan/dagstimere**: gulvvarme er så træg, at skift mellem dag/nat-temperatur ikke giver mening. Vil du ændre temperaturen, så ændr måltemperaturen – eller lav en almindelig HA-automation, der kalder `set_room_temperature`.

---

## 🚀 Installation

### Via HACS (anbefalet)
1. Åbn **HACS** i Home Assistant.
2. Tryk på de tre prikker øverst til højre → **Brugerdefinerede repositories**.
3. Indsæt repo-URL'en `https://github.com/OlNissen/ha-advanced-floor-heating`, vælg kategori **Integration**.
4. Hent integrationen og **genstart Home Assistant**.

### Manuelt
1. Kopiér mappen `custom_components/advanced_floor_heating` til `config/custom_components/` i din Home Assistant (så der ligger `config/custom_components/advanced_floor_heating/manifest.json`).
2. **Genstart Home Assistant.**

### Opgradering fra 1.0.x
Du behøver ikke gøre noget ved dine eksisterende rum – entity-id'er, måltemperaturer og indstillinger bevares. Opdatér, genstart, og åbn evt. rummets indstillinger (se nedenfor) for at tilføje vinduessensor. Entiteterne samles nu under én *enhed* pr. rum.

---

## ⚙️ Opsæt et rum

**Indstillinger → Enheder & tjenester → Tilføj integration → "Advanced Floor Heating".**
Gentag for hvert rum.

Det skal du selv angive for hvert rum:

| Felt | Hvad | Eksempel |
|---|---|---|
| Rumnavn | Navnet på rummet. Bestemmer entity-id'erne (`climate.stue`). | `Stue` |
| Rumtemperatur-sensor | `sensor` med device class *temperature* | `sensor.stue_temperatur` |
| Gulvtemperatur-sensor | `sensor` med device class *temperature* | `sensor.stue_gulv_temperatur` |
| Kontakt til varmen | `switch` der åbner/lukker for varmen (termomotor/relæ) | `switch.stue_varme` |
| Vindues-sensor *(valgfri)* | `binary_sensor` – `on` = vindue åbent | `binary_sensor.stue_vindue` |

Har et rum flere vinduer, så lav en samlet sensor først (Indstillinger → Enheder & tjenester → Hjælpere → *Gruppe* → *Binær sensorgruppe*, med "vindue" som type) og vælg den.

> **Tip:** Rumnavnet bliver til entity-id'et. Ændrer du navnet bagefter, ændres entity-id'et ikke automatisk – og dashboardet peger på entity-id'er.

### Ret indstillinger senere
**Indstillinger → Enheder & tjenester → Advanced Floor Heating → (rummet) → Konfigurer.**

| Indstilling | Standard | Forklaring |
|---|---|---|
| Vindues-sensor | tom | Tom = ingen vinduesregel for rummet |
| Maks. gulvtemperatur | 32 °C | Varmen slukkes, når gulvet når denne temperatur |
| Kp / Ki / Kd | 10 / 2 / 1 | PID-parametre |
| PID-interval | 30 sek | Hvor ofte regulatoren regner |
| PWM-cyklus | 30 sek | Længden på tænd/sluk-cyklussen. For termomotorer (telestater) er **ca. 900–1800 sek** typisk fornuftigt – 30 sek er kun en startværdi |

Når du gemmer, genindlæses rummet automatisk.

---

## 🪟 Vinduesregel

Hvis rummet har en vindues-sensor, og vinduet er åbent:

- Regulatoren **regulerer ikke efter rumtemperaturen** (den falder jo bare, fordi der er åbent).
- I stedet **fryses udgangen** (varmeeffekten i %) på den værdi, den havde. PID'ens integral og fejl ændres ikke, mens vinduet er åbent.
- Når vinduet lukkes igen, fortsætter reguleringen **uden spring** (D-leddet nulstilles).
- **`Floor Only`** regulerer kun på gulvet og påvirkes derfor ikke af vinduet.
- **Gulv-sikkerheden gælder altid:** når gulvet når maks. gulvtemperatur, slukkes varmen – også mens udgangen er frosset.
- Mangler eller er vindues-sensoren `unavailable`, tæller vinduet som *lukket* – så en defekt sensor aldrig holder varmen frosset for evigt.

Status ses i rummets attributter (`window_open`, `output_frozen`) og i status-sensoren (`Window open - output frozen at 40%`).

---

## 📊 Dashboard til alle rum

Dashboardet viser for hvert rum: termostat (aktuel + ønsket rumtemperatur, til/fra, driftstilstand), gulvtemperatur, ønsket gulvtemperatur (slider), varmeeffekt i %, status og vindue. Øverst er et **overblik** med alle rum og knapper til **Alle til / Alle fra**. Dashboardet bruger kun Home Assistants indbyggede kort – ingen ekstra kort fra HACS.

Kræver **Home Assistant 2024.8 eller nyere**.

### 1. Find dine entity-id'er
Gå til **Indstillinger → Enheder & tjenester → Entiteter** og søg efter rummets navn. For rummet "Stue" bruges:

| Entity | Hvad |
|---|---|
| `climate.stue` | Selve regulatoren |
| `number.stue_floor_setpoint` | Ønsket gulvtemperatur |
| `sensor.stue_pid_signal` | Varmeeffekt (%) |
| `sensor.stue_regulation_status` | Status-tekst |

Står dine entity-id'er anderledes (f.eks. `climate.stue_2`), så brug dem i næste trin.

### 2. Lav YAML'en til dine rum
Filen [`dashboard/varmestyring.yaml`](dashboard/varmestyring.yaml) er et færdigt eksempel med rummene `stue`, `kontor` og `bad`. Lav din egen med scriptet (kræver Python 3, ingen ekstra pakker):

```powershell
python tools/generer_dashboard.py "stue=Stue" "sovevaerelse=Soveværelse" "bad=Bad" > dashboard/mit-dashboard.yaml
```

Hvert argument er `entity-id-navn=Pænt navn` (entity-id-navnet er det, der står efter `climate.`). Vil du ikke bruge Python, kan du åbne eksempelfilen og i hånden rette `stue`, `kontor` og `bad` til dine egne rum – eller kopiere/slette hele `# ---------- Rum ----------`-blokke.

### 3. Importér i Home Assistant
1. **Indstillinger → Dashboards → Tilføj dashboard → Nyt dashboard fra bunden**, giv det navnet *Varmestyring*.
2. Åbn dashboardet → blyanten (**Rediger dashboard**) → de tre prikker → **Rå konfigurationseditor**.
3. Slet alt indhold, indsæt indholdet af din YAML-fil og tryk **Gem**.

*(Bruger du YAML-tilstand for dashboards, kan filen i stedet lægges i `config/` og refereres fra `configuration.yaml` under `lovelace: dashboards:`.)*

### Sådan bruges det
- **Ønsket rumtemperatur:** stilles på termostat-kortet. I tilstanden `Floor Only` ændrer termostaten i stedet gulvets måltemperatur.
- **Ønsket gulvtemperatur:** slideren i rum-kortet.
- **Til/fra:** knapperne `heat` / `off` på termostat-kortet. `off` sætter udgangen til 0 % og slukker for kontakten.
- **Driftstilstand:** drop-down'en på termostat-kortet (de fire presets).
- Vises preset-valget ikke på termostat-kortet i din HA-version, kan du ændre det via kortets "mere info"-dialog (klik på rummets navn).

---

## 🛠 Services

Til automatiseringer:

- `advanced_floor_heating.set_room_temperature` – sæt rummets måltemperatur
- `advanced_floor_heating.set_floor_temperature` – sæt gulvets måltemperatur

```yaml
action: advanced_floor_heating.set_room_temperature
target:
  entity_id: climate.stue
data:
  temperature: 21.5
```

## 🛡 Sikkerhed

- Gulvføleren er **påkrævet**: mangler den (`unavailable`/ugyldig værdi), slukkes varmen. Mangler rumføleren, og tilstanden bruger rummet, slukkes varmen også.
- Når et rum genindlæses eller fjernes, stoppes de gamle regulerings-løkker og kontakten slukkes (før blev løkkerne liggende og kæmpede mod de nye).

## 📈 Diagnostik

Al PID-data ligger som attributter på `climate`-entiteten: `control_output`, `pid_p`, `pid_i`, `pid_d`, `pid_e`, `room_temperature`, `floor_temperature`, `max_floor_temperature`, `window_open`, `output_frozen` m.fl.

## 🧩 Ændringer i 1.1.0

- Vinduesregel (frys udgang) og maks. gulvtemperatur som indstilling pr. rum
- Dashboard + dashboard-generator
- Dansk og engelsk oversættelse af opsætningsskærmene
- Rettet: gulv-skyderen (`number`) ændrede også rummets måltemperatur
- Rettet: genindlæsning efterlod gamle løkker kørende; kontakten slukkes nu ved fjernelse
- Rettet: ugyldige sensorværdier kunne vælte regulatoren; manglende føler giver nu sikkert 0 % i stedet for at holde sidste værdi
- Rettet: valgt driftstilstand (preset) gendannes efter genstart
- Rettet: `servies.yaml` → `services.yaml` (servicebeskrivelserne blev ikke indlæst)
- Sensorer og slider opdateres med det samme og samles under én enhed pr. rum

## 🤝 Bidrag & support
Fejl eller ønsker? Opret et Issue eller en Pull Request.

Frontend-kort (valgfrit): [lovelace-advanced-floor-heating-card](https://github.com/OlNissen/lovelace-advanced-floor-heating-card)

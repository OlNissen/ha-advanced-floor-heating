# Advanced Floor Heating til Home Assistant ♨️

PID-baseret varmestyring til **gulvvarme** (træge systemer, f.eks. IHC med termomotorer/telestater). Hvert rum får sin egen regulator, der styrer efter **rumtemperatur og/eller gulvtemperatur**, så gulvet aldrig bliver for varmt.

## ✨ Funktioner

- **Ét rum = én regulator.** Tilføj integrationen igen for hvert rum – der skal ikke kopieres kode.
- **Rum- og gulvføler i samme regulator** med 4 driftstilstande (preset):
  - `Kun Rum` – regulerer kun på rumtemperaturen
  - `Kun Gulv` – regulerer kun på gulvtemperaturen
  - `Rum & Gulv (1 Opfyldt)` – stopper, når det første mål er nået (komfort)
  - `Rum & Gulv (Begge Opfyldt)` – stopper først, når begge mål er nået
- **PID med anti-windup** og **PWM-udgang** (kontakten tændes/slukkes i cyklusser).
- **Vinduesregel (valgfri):** er vinduet åbent, **fryses udgangen**, så der ikke reguleres efter den (kolde) rumtemperatur. Se [Vinduesregel](#-vinduesregel).
- **Master (som i IHC):** én tilstand for hele huset – `Beboet`, `Ubeboet`, `Frostsikker` eller `Slukket` – som sendes ud til alle rum. Hvert rum kan overstyre den. Se [Master](#-master-og-husets-tilstand).
- **Alarmer** pr. rum og samlet for huset: føler mangler/er gammel, og ventil der ikke varmer. Se [Alarmer](#-alarmer-og-driftstid).
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

> Der er nu et valg først: **Tilføj et rum** eller **Tilføj Master** (se [Master](#-master-og-husets-tilstand)).

Det skal du selv angive for hvert rum:

| Felt | Hvad | Eksempel |
|---|---|---|
| Rumnavn | Navnet på rummet. Bestemmer entity-id'erne (`climate.stue`). | `Stue` |
| Rumtemperatur-sensor | `sensor` med device class *temperature* | `sensor.stue_temperatur` |
| Gulvtemperatur-sensor | `sensor` med device class *temperature* | `sensor.stue_gulv_temperatur` |
| Kontakt til varmen | `switch` der åbner/lukker for varmen (termomotor/relæ) | `switch.stue_varme` |
| Vindues- og dørkontakter *(valgfri)* | Én eller flere `binary_sensor` – `on` = åben. Rum med både dør og vindue kan have begge. | `binary_sensor.stue_vindue`, `binary_sensor.stue_dor` |

Har et rum flere vinduer og døre, så vælg dem alle – rummet regnes som åbent, så snart **en** af dem er åben (du behøver ikke lave en gruppe først).

> **Tip:** Rumnavnet bliver til entity-id'et. Ændrer du navnet bagefter, ændres entity-id'et ikke automatisk – og dashboardet peger på entity-id'er.

### Ret indstillinger senere
**Indstillinger → Enheder & tjenester → Advanced Floor Heating → (rummet) → Konfigurer.**

| Indstilling | Standard | Forklaring |
|---|---|---|
| Vindues- og dørkontakter | tom | Tom = ingen vinduesregel for rummet. Flere kan vælges |
| Maks. gulvtemperatur | 32 °C | Varmen slukkes, når gulvet når denne temperatur |
| Ventilmotion (dage) | 7 | Har ventilen ikke været åben i så mange dage, motioneres den: 3 cyklusser med 10 min åben og 10 min lukket (som i IHC-programmet), så termomotoren ikke sætter sig. 0 = slået fra. Virker også, mens rummet er slukket |
| Føler uden opdatering (timer) | 0 (fra) | Står en føler stille i så mange timer, regnes den som *mangler* (varmen slukkes, og der kommer en alarm). Vær forsigtig: føleren skal opdatere ofte nok, ellers får du falske alarmer |
| Udekompensation ke | 0 (fra) | Lægger `ke × (rummål − udetemp)` procent oven på PID-udgangen. Bruger Masterens `Ude Kilde` (måling, prognose eller begge). Start lavt (0,3–1,0), og lad I-leddet tage resten |
| Sol-fradrag ks | 0 (fra) | Trækker `ks × sol` procent fra udgangen, når solen varmer (se [Udekompensation, prognose og sol](#-udekompensation-prognose-og-sol)) |
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
- **`Kun Gulv`** regulerer kun på gulvet og påvirkes derfor ikke af vinduet.
- **Gulv-sikkerheden gælder altid:** når gulvet når maks. gulvtemperatur, slukkes varmen – også mens udgangen er frosset.
- Mangler eller er vindues-sensoren `unavailable`, tæller vinduet som *lukket* – så en defekt sensor aldrig holder varmen frosset for evigt.

Status ses i rummets attributter (`window_open`, `output_frozen`) og i status-sensoren (`Vindue åbent - udgang frosset ved 40%`).

---

## 🏠 Master og husets tilstand

Ligesom i IHC kan hele huset få sin tilstand sat ét sted. **Tilføj integration → Advanced Floor Heating → Tilføj Master** (der kan kun være én). Masteren giver:

| Entity | Hvad |
|---|---|
| `select.gulvvarme_master` | Husets tilstand: `Beboet`, `Ubeboet`, `Frostsikker`, `Slukket` |
| `number.gulvvarme_master_ubeboet_temperatur` | Hvad et rum holder i *Ubeboet* (standard 19 °C) |
| `number.gulvvarme_master_frost_temperatur` | Hvad et rum holder i *Frostsikker* (standard 16 °C) |
| `binary_sensor.gulvvarme_master_alarm` | Tændt, hvis et rum har en alarm (attributten `rum` viser hvilke) |
| `select.gulvvarme_master_ude_kilde` | Hvad udekompensationen bruger: `Måling`, `Prognose` eller `Begge` (se [Udekompensation og sol](#-udekompensation-prognose-og-sol)) |
| `sensor.gulvvarme_master_ude_temperatur_brugt` | Den ude-temperatur rummene bruger lige nu (attributter: måling, prognose, kilde) |
| `sensor.gulvvarme_master_sol` | Sol 0–100 % (solhøjde × klar himmel) |

Hvad tilstandene gør:

- **Beboet** – hvert rum regulerer efter sine egne setpunkter (som før).
- **Ubeboet** / **Frostsikker** – rummets setpunkter **sænkes**, så rummet holder Masterens temperatur. Sænkningen er `rum-setpunkt − Masterens temperatur`, og samme antal grader trækkes fra gulv-setpunktet. Rummets *egne* setpunkter ændres ikke og vender tilbage, når huset er Beboet igen. Gulvgrænsen og vinduesreglen gælder som altid.
- **Slukket** – udgangen er 0 %. Ventilmotion kører stadig, så termomotorerne ikke sætter sig.

Hvert rum har også en `select.<rum>_husstilstand` med `Fælles` (følger Masteren, standard) eller en af de fire tilstande. Den bruges til de rum, der ikke skal følge resten – f.eks. et værelse, der er i brug, mens huset ellers er Ubeboet. Valget kan også ændres i kortets indstillinger.

Autotune kan kun køre, mens rummet er `Beboet`; skifter tilstanden undervejs, afbrydes testen. PID-parametre og cyklustider påvirkes ikke af tilstandene.

## 🔗 Koblede rum

Hører to rum til **samme luftrum** (f.eks. køkken og stue med et niveauspring imellem), kan de kobles. Hvert rum beholder sin egen gulvføler, gulvgrænse, ventil, shunt og PID, men:

- **Fælles rumtemperatur:** regulatoren regner med det **vægtede middel** af de koblede rums rumfølere. Begge rum ser så samme rumtemperatur og modarbejder ikke hinanden. Rummets egen måling vises stadig på kortet (`room_temperature`); den fælles står i `control_room_temperature`.
- **Vægt:** hvert rum har en vægt (f.eks. rummets m²). Er stuen 30 m² og køkkenet 10 m², tæller stuens føler 3 gange så meget. Lige vægt (1) giver et almindeligt middel.
- **Fælles rum-setpunkt:** ændrer du rum-setpunktet i det ene rum, følger det andet med. Gulv-setpunkter er hvert rums egne, for rummene har hver sin shunt og gulv.
- **Manglende føler:** mangler det ene rums rumføler, bruges de øvrige i stedet for at slukke varmen (uden kobling slukkes den som før).
- Vinduer og døre er stadig pr. rum: vælg de samme kontakter i begge rum, så fryser begge udgange.

Sådan kobler du: **Konfigurer** på hvert af rummene → *Koblede rum* → vælg det andet rum, og sæt *Vægt*. Gør det i **begge** rum (kobles kun det ene, følger kun det ene med). Er et rum sat til `Kun Gulv`, bruges dets rumføler ikke til regulering, men setpunktet synkroniseres stadig.

Autotune bruger også den fælles rumtemperatur. De koblede rum påvirker hinanden, så tun ét rum ad gangen og sæt det andet til `Slukket` under testen (rummets *Husstilstand*).

## 🔔 Notifikationer (fælles, på Masteren)

Alle beskeder fra integrationen (første/ny gennemgang, rum der svinger, forslag fra en AI, alarmer og shunt-råd) sendes samme sted fra. Under Masterens *Konfigurer* vælger du:

- **Vis beskeder som notifikation i HA** (standard: ja). Slå den fra, hvis du kun vil have push.
- **Send også beskeder som push til disse mobiler.** Listen viser de mobiler, der har HA-appen (`notify.mobile_app_…`). Vælg dem, der skal have beskeden, og lad resten stå.

Knappen **Send Testbesked** på Masteren afprøver det. Alarmer kommer, når de opstår (ikke igen, så længe de varer), og HA-notifikationen fjernes, når alarmen forsvinder. Push-beskeder kan ikke tilbagekaldes og viser ren tekst uden fed skrift.

Uden Master sendes kun HA-notifikationer.

## 🤖 Gennemgang af indstillingerne (til dig og en AI)

Regulatoren måler selv, hvordan hvert rum opfører sig, og kan give en AI-assistent (fx Claude via Assist/MCP i HA, eller en automation) et overblik, så den kan foreslå bedre indstillinger. **Intet ændres uden dit ok.**

**Notifikationer** (som HA-notifikationer, og som events, du kan sende videre til din telefon):

- **Første gennemgang:** efter 14 dages drift (kan ændres på Masteren: *Foreslå første gennemgang efter … dage*) kommer en besked om, at der nu er data nok. Den forklarer, hvad du skal gøre.
- **Ny gennemgang:** 30 dage efter den sidste.
- **Et rum svinger (hakker):** skifter et rum mindst 6 gange på 24 timer mellem for koldt og for varmt (±0,2 °C), og udgangen svinger mindst 40 procentpoint, foreslås en ny gennemgang af netop det rum. Ikke de første 2 dage, ikke under autotune, og højst én gang pr. rum om ugen. Et nyt setpunkt eller en ny tilstand nulstiller tælleren, så naturlige skift ikke tæller.

Events (til egne automationer): `advanced_floor_heating_review_suggested` (med `reason`: `first`, `periodic` eller `hunting`) og `advanced_floor_heating_proposal`.

**Services til en AI-assistent:**

| Service | Hvad |
|---|---|
| `advanced_floor_heating.get_report` | Returnerer en kort rapport pr. rum: mål og temperaturer, PID, tillæg, vægt, alarmer og de seneste 24 timer (tid inden for 0,3 °C, tid for koldt/varmt, udgang min/max/middel, udsving, antal skift). Markerer en gennemgang som udført |
| `advanced_floor_heating.set_parameters` | **Foreslår** nye værdier for et rum: `kp`, `ki`, `kd`, `outdoor_ke`, `solar_gain`, `link_weight` (+ `reason`). Tjekkes mod grænser; Kp/Ki/Kd må højst ændres med en faktor 4 ad gangen |
| `advanced_floor_heating.discard_proposal` | Kasserer et forslag |

Et forslag vises som notifikation og som attributten `pending_proposal` på rummet. Du bruger det med knappen **`Anvend Forslag`** (`button.<rum>_anvend_forslag`), og det kasseres ved at ignorere det. Hver anvendt ændring logges (gammel og ny værdi, hvem, hvorfor) og står i `recent_changes` i rapporten.

**Hvad en AI ikke kan:** ændre gulvgrænsen, vinduesreglen eller ventilmotionen. Den kan heller ikke anvende et forslag selv, medmindre du slår *Tillad at en AI ændrer indstillinger direkte* til på Masteren (standard: nej). Vil du være sikker på, at en AI ikke selv kan trykke på knappen, så lad være at give Assist adgang til `button.*_anvend_forslag`.

`last_24h` dækker de seneste 24 timer og nulstilles ved genstart af HA. Til længere analyser ligger historikken i HA's recorder. Giv den mindst 30 dage (`recorder: purge_keep_days: 45` i `configuration.yaml`; standard er 10).

## 🌦 Udekompensation, prognose og sol

To valgfrie tillæg oven på PID-udgangen. Begge er **slået fra som standard** (`ke` = 0 og `ks` = 0 pr. rum), så regulatoren opfører sig som før, indtil du selv slår dem til.

**Masteren** (Konfigurer) kan have en *udetemperatur-føler* og/eller en *vejr-entitet* (`weather.*`). Vejr-entiteten bruges til prognose (middeltemperatur de næste 1–12 timer, standard 4; hentes hvert 30. minut) og til skydække. Time-prognose bruges, hvis vejr-entiteten har den; ellers 2×dagligt eller dagsprognose. Er prognosen ældre end 3 timer, bruges den ikke.

**`Ude Kilde`** vælger, hvad rummene regner med:

| Kilde | Ude-temperatur | Skydække |
|---|---|---|
| `Måling` | udeføleren lige nu | vejr-entitetens nuværende skydække |
| `Prognose` | prognosens middel over de næste timer | prognosens skydække |
| `Begge` | middel af måling og prognose | middel af begge |

Mangler den valgte kilde, er tillægget 0 (der er ingen stille omskiftning til en anden kilde, bortset fra `Begge`, som bruger det, der findes).

**Pr. rum** (Konfigurer):

- **`ke` (udekompensation):** lægger `ke × (rummål − ude)` procent til udgangen. Start lavt (0,3–0,5).
- **`ks` (sol-fradrag):** trækker `ks × sol` procent fra udgangen, når solen varmer (sol = solhøjde/30° begrænset til 0–1, ganget med klar himmel). Brug det til rum mod syd. Solhøjden er den nuværende, ikke den kommende.

Tillæggene er med i anti-windup, og I-leddet tilpasser sig dem. Kortets `pid_ff`-attribut viser tillægget lige nu. Hvor meget det betyder, er en gætteøvelse, indtil du har set det i nogle dage: ændr ét rum ad gangen.

## 🚨 Alarmer og driftstid

Hvert rum har `binary_sensor.<rum>_alarm` (type *problem*) med attributten `alarmer`. En alarm kommer, når:

- en føler har manglet (eller været gammel) i mere end **15 minutter**, eller
- udgangen har været **90 % eller mere i 90 minutter**, uden at gulvet er steget mindst 0,5 °C, og gulvet stadig er mere end 1 °C under sit mål – en mulig **fastsiddende ventil**.

Kortet viser den første alarm i statuslinjen med rød tekst. `sensor.<rum>_driftstid_i_dag` viser, hvor mange timer ventilen har været åben i dag (nulstilles ved midnat). Brug alarmerne i en almindelig HA-automation til at få en notifikation.

## 📊 Dashboard til alle rum

Dashboardet viser for hvert rum: termostat (aktuel + ønsket rumtemperatur, til/fra, driftstilstand), gulvtemperatur, ønsket gulvtemperatur (slider), varmeeffekt i %, status og vindue. Øverst er et **overblik** med alle rum og knapper til **Alle til / Alle fra**. Dashboardet bruger kun Home Assistants indbyggede kort – ingen ekstra kort fra HACS.

Kræver **Home Assistant 2024.8 eller nyere**.

### 1. Find dine entity-id'er
Gå til **Indstillinger → Enheder & tjenester → Entiteter** og søg efter rummets navn. For rummet "Stue" bruges:

| Entity | Hvad |
|---|---|
| `climate.stue` | Selve regulatoren |
| `number.stue_rum_setpunkt` | Ønsket rumtemperatur (rum-setpunkt) – kan både ses og ændres |
| `number.stue_gulv_setpunkt` | Ønsket gulvtemperatur |
| `sensor.stue_pid_signal` | Varmeeffekt (%) |
| `sensor.stue_reguleringsstatus` | Status-tekst |
| `switch.stue_autotune` | Start/stop autotune af PID |
| `button.stue_anvend_autotune` | Anvend autotune-resultatet |

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
- **Ønsket rumtemperatur (rum-setpunkt):** slideren `Rum Setpunkt` i rum-kortet viser og ændrer den. Termostat-kortet ændrer den også, undtagen i `Kun Gulv`, hvor termostaten i stedet ændrer gulvets måltemperatur.
- **Ønsket gulvtemperatur:** slideren `Gulv Setpunkt` i rum-kortet.
- **Til/fra:** knapperne `heat` / `off` på termostat-kortet. `off` sætter udgangen til 0 % og slukker for kontakten.
- **Driftstilstand:** drop-down'en på termostat-kortet (de fire driftstilstande).
- Vises preset-valget ikke på termostat-kortet i din HA-version, kan du ændre det via kortets "mere info"-dialog (klik på rummets navn).

---

## 🛠 Services

Til automatiseringer:

- `advanced_floor_heating.set_room_temperature` – sæt rummets måltemperatur
- `advanced_floor_heating.set_floor_temperature` – sæt gulvets måltemperatur
- `advanced_floor_heating.start_autotune` / `stop_autotune` / `apply_autotune` – se [Autotune af PID](#-autotune-af-pid)

```yaml
action: advanced_floor_heating.set_room_temperature
target:
  entity_id: climate.stue
data:
  temperature: 21.5
```

## 🃏 Lovelace-kort (`custom:advanced-floor-heating-card`)

Filen [`lovelace/advanced-floor-heating-card.js`](lovelace/advanced-floor-heating-card.js) er et samlet kort pr. rum:

- **Dial** med rum (øverst) og gulv (nederst). Træk i dial'en for at ændre måltemperatur. Kortet er med vilje enkelt og stille.
- **Én lille linje** under dial'en fortæller, hvad rummet regulerer efter (`Regulerer efter rum`, `Regulerer kun efter gulv`, `Mål nået`, `Slukket`). Ved åbent vindue står der `Vindue åbent – udgang holdes`, og under autotune `Autotune kører`.
- **Graf-knap** (kurve-ikonet ved tandhjulet): åbner historik for rum, gulv, rum-/gulv-setpunkt, effekt og ventil. Vælg 6 timer, 24 timer, 3 dage eller 7 dage.
- **Små ikoner øverst til venstre** (kun når de er relevante): et åbent vindue/en åben dør (hold musen over for at se hvilken) og en pulserende lilla tryllestav, mens autotune kører.
- **Tandhjul**: åbner indstillingerne i en popup (samme stil som grafen) med til/fra, driftstilstand, ventil, autotune og PID-data (her står også effekt og den fulde status). Kortet selv forbliver småt og stille.

Installation: kopiér filen til `config/www/`, og tilføj den som ressource (**Indstillinger → Dashboards → ⋮ → Ressourcer → Tilføj**): URL `/local/advanced-floor-heating-card.js`, type *JavaScript-modul*. Ændrer du filen, så hæv `?v=…` på URL'en for at tvinge browseren til at hente den igen.

```yaml
type: custom:advanced-floor-heating-card
entity: climate.stue
switch_entity: switch.stue_telestat   # valgfri: viser om ventilen er åben
name: Stue
show_status: true    # false = skjul den lille tilstandslinje i bunden
dim_markers: true    # false = knapperne er altid fulde (ingen dæmpning/slukning)
```

**Setpunkt-knapperne følger tilstanden** (med `dim_markers: true`, som er standard):

| Knap | Når den er |
|---|---|
| Fuld | zonen skal opfyldes: begge i `Rum & Gulv (Begge Opfyldt)`, kun den zone, der er tættest på sit mål (og dermed afgør), i `Rum & Gulv (1 Opfyldt)` |
| Dæmpet | den anden zone i `Rum & Gulv (1 Opfyldt)`, når kun den ene afgør, eller rummet, mens et vindue/en dør er åben |
| Næsten slukket og grå | regulatoren er slukket |

Rum står altid øverst og gulv nederst. I tilstanden `Kun Gulv` er rum-justeringen skjult helt (knap og træk), fordi rummet ikke bruges, og i `Kun Rum` er gulv-justeringen skjult på samme måde. Begge valg findes også i kortets editor.

## 🎛 Autotune af PID

Autotune finder selv Kp og Ki til et rum. Den bruger **relæ-metoden** (Åström-Hägglund, samme princip som `smart_thermostat`):

1. I stedet for PID'en lader den udgangen skifte mellem et højt og et lavt niveau omkring det udgangsniveau, regulatoren selv har fundet (I-leddet). Går temperaturen over setpunktet (+ støjbånd), går udgangen ned. Går den under, går udgangen op.
2. Temperaturen begynder at svinge. Af svingningens **amplitude** og **periode** beregnes processens ultimative forstærkning (`Ku = 4·d / (π·amplitude)`).
3. Når tre svingninger er ens (±20 %), regnes **Kp** og **Ki** ud med en tuning-regel (`ziegler-nichols` som standard, `tyreus-luyben` er mere forsigtig). **Kd bliver 0** (ren PI), som til gulvvarme er det sikreste.

**Sådan bruges det**
1. Sæt rummet til det setpunkt, du vil tune på, og lad rummet være ret roligt (vinduer lukkede, ingen sol/ovn der forstyrrer).
2. Tænd kontakten `switch.<rum>_autotune` i rum-kortet. Status ses i attributten `autotune_status` og i regulatorens status.
3. **Gulvvarme er træg – en kørsel tager typisk 10-25 timer**, og temperaturen svinger ca. ±0,5-1 °C om setpunktet undervejs. I simulering af en typisk gulvvarme tog det 12-23 timer.
4. Når den er færdig, står resultatet i attributten `autotune_result` og i status-teksten. Tryk på knappen `button.<rum>_anvend_autotune`, så gemmes Kp/Ki/Kd i rummets indstillinger (rummet genindlæses). Intet ændres, før du trykker.

**Hvad der tunes på:** i tilstande der bruger rummet (alle undtagen `Kun Gulv`) tunes på **rumtemperaturen**, ellers på **gulvtemperaturen**. Vil du bestemme det selv, så kald servicen `advanced_floor_heating.start_autotune` med `target: room` eller `floor`.

**Sikkerhed:** Autotunen afbrydes (og udgangen sættes til 0 %), hvis vinduet åbnes (rum-tuning), gulvet kommer inden for 0,5 °C af maks. gulvtemperatur, en føler mangler, regulatoren slukkes, eller den ikke finder en stabil svingning inden for tidsgrænsen (24 t). Maks. gulvtemperatur gælder hele tiden – sæt den passende lavt, før du starter. Tidsgrænse, udgangstrin, støjbånd og regel kan ændres via servicen:

```yaml
action: advanced_floor_heating.start_autotune
target:
  entity_id: climate.stue
data:
  target: room          # room eller floor
  output_step: 30       # % op/ned om bias-niveauet (mindre = mindre temperaturudsving)
  noiseband: 0.2        # °C hysterese; skal være større end følerens støj
  rule: ziegler-nichols # eller tyreus-luyben
  max_hours: 24
```

Tun gerne ét rum ad gangen. Genstartes HA midt i en test, afbrydes den, og den starter ikke af sig selv igen.

## 🔧 Pumpegrupper: pumpestyring og shunt-råd

I et IHC-anlæg styres cirkulationspumpen ofte af en funktionsblok, som får et **kald fra hvert rums varmestyring** ("Udgang til pumpestyring"). Slukker du IHC's varmefunktioner, forsvinder kaldene, og pumperne står stille. En **pumpegruppe** overtager det: den samler de rum, der deler pumpe og shunt.

**Tilføj (to trin, og du vælger aldrig det samme to gange):**

1. *Tilføj integration → Advanced Floor Heating → Tilføj en pumpegruppe.* Lav én gruppe pr. pumpe/shunt (fx *Teknikrum* og *Kælder*). Du angiver kun et navn og, hvis du vil, pumpens tilbagemelding (`binary_sensor`, bruges til motion) og shuntens fremløbsføler (temperaturføler, bruges til visning og i beskeden).
2. **På hvert rum** (*Konfigurer*) vælger du *Pumpegruppe* fra en liste og *Pumpekontakt for rummet* (IHC's "pumpestyring"-ressource som `switch`, se [`ihc/telestat-switches.yaml`](ihc/telestat-switches.yaml)). Hedder rummets telestat `switch.stue_telestat`, foreslås `switch.stue_pumpestyring` automatisk.

Gruppen finder selv sine rum, ventiler og pumpekontakter ud fra rummene. Flytter du et rum til en anden gruppe, følger pumpestyringen med. (Under gruppens *Konfigurer* kan man stadig angive faste lister over rum og kontakter, men det er kun til særlige tilfælde.) Samme sted kan du ændre efterløbet (standard 5 min) og dage uden kørsel før motion (standard 7; 0 = fra).

**Pumpestyring:**

- Pumpens kontakter tændes, så snart en ventil (rummets kontakt) i gruppen åbner.
- De slukkes *efterløbet* efter, at den sidste er lukket. Åbner en ventil igen i mellemtiden, fortsætter pumpen.
- Efter en genstart af HA tændes pumpen ved kald, ellers slukkes den.
- **Motion:** står pumpen stille i 7 dage, tændes den kl. 03:00 i 5 minutter (kræver tilbagemeldingen). Knappen *Pumpemotion nu* kører den med det samme.
- Kontakten *Pumpestyring aktiv* slår det hele fra, så HA ikke rører pumpens kontakter.

**Shunt-råd:** en termostat på shunten holder en fast fremløbstemperatur og kender ikke vejret. Rådet kigger på ventilerne:

- **Skru op**, når mindst 40 % af rummene (og mindst 2) står på næsten 100 %, er mere end 0,3 °C under målet, og deres gulv har plads til mere varme (ikke ved gulvgrænsen, og ikke langt over gulvmålet). Rummet skal have holdt i **3 timer**.
- **Skru ned**, når mindst 70 % af rummene har næsten lukkede ventiler, og ingen mangler varme. Skal have holdt i **6 timer**.
- Beskeden kommer som en HA-notifikation (og som event `advanced_floor_heating_shunt_advice`) og højst én gang i døgnet. Kontakten *Shunt-alarm aktiv* slår den fra.

**Entiteter pr. gruppe:** `Varmekald`, `Pumpe kører`, `Pumpestatus`, `Ventiler åbne` (%), `Shunt Råd`, `Shunt Fremløb`, kontakterne `Pumpestyring aktiv` og `Shunt-alarm aktiv`, og knappen `Pumpemotion nu`.

## 🛡 Sikkerhed

- Gulvføleren er **påkrævet**: mangler den (`unavailable`/ugyldig værdi), slukkes varmen. Mangler rumføleren, og tilstanden bruger rummet, slukkes varmen også.
- Når et rum genindlæses eller fjernes, stoppes de gamle regulerings-løkker og kontakten slukkes (før blev løkkerne liggende og kæmpede mod de nye).

## 📈 Diagnostik

Al PID-data ligger som attributter på `climate`-entiteten: `control_output`, `pid_p`, `pid_i`, `pid_d`, `pid_e`, `room_temperature`, `floor_temperature`, `max_floor_temperature`, `window_open`, `output_frozen` m.fl.

## 🧩 Ændringer i 1.9.1, 1.9.0, 1.8.0, 1.7.0, 1.6.0, 1.5.0 og 1.4.0

- Ny (1.9.1): alarmen "Ventil sidder muligvis fast" udløses ikke, når shuntens fremløb er for koldt til at varme gulvet (mindre end 3 °C over gulvmålet). Så er det shunten, ikke ventilen, og rådet om at skrue op tager sig af det
- Ny (1.9.0): **fælles notifikationer på Masteren** (HA og/eller push til valgte mobiler, testknap), **alarmer sendes som besked**, og **rummene vælger selv pumpegruppe og pumpekontakt**, så en pumpegruppe kun skal have et navn

- Ny (1.8.0): **pumpegrupper** – pumpestyring (kald, efterløb, motion), `Ventiler åbne` og **shunt-råd** med besked om at skrue shuntens termostat op eller ned

- Ny (1.7.0): **gennemgang med AI** – måling af udsving pr. rum, notifikationer om første/ny gennemgang og om rum der svinger, services `get_report`/`set_parameters`/`discard_proposal`, forslag der kræver tryk på `Anvend Forslag`, og ændringslog

- Ny (1.6.0): **koblede rum** med vægtet fælles rumtemperatur, fælles rum-setpunkt og fallback ved manglende føler

- Ny: **Master** med husets tilstand (Beboet/Ubeboet/Frostsikker/Slukket), temperaturer for Ubeboet og Frostsikker, og en tilstand pr. rum, der kan overstyre
- Ny: alarmer (føler mangler/gammel, mulig fastsiddende ventil) og `Driftstid i dag`
- Ny: valgfri udekompensation (`ke`) med valg af kilde (udeføler, vejrprognose eller begge) og valgfrit sol-fradrag (`ks`), og valgfri "føler uden opdatering"-grænse
- Kortet viser husets tilstand og alarmer i den stille statuslinje, og rummets husstilstand kan vælges i indstillingerne
- Uændret: PID-formler, PWM-cyklus og alle standardindstillinger

## 🧩 Ændringer i 1.1.0

- Vinduesregel (frys udgang) og maks. gulvtemperatur som indstilling pr. rum
- Dashboard + dashboard-generator
- Danske tekster (driftstilstande, status, navne) er nu også i GitHub-koden – samme som den version, der kørte i HA – plus PWM anti-micro-switching
- Dansk og engelsk oversættelse af opsætningsskærmene
- Rettet: gulv-skyderen (`number`) ændrede også rummets måltemperatur
- Rettet: genindlæsning efterlod gamle løkker kørende; kontakten slukkes nu ved fjernelse
- Rettet: ugyldige sensorværdier kunne vælte regulatoren; manglende føler giver nu sikkert 0 % i stedet for at holde sidste værdi
- Rettet: valgt driftstilstand (preset) gendannes efter genstart
- Rettet: `servies.yaml` → `services.yaml` (servicebeskrivelserne blev ikke indlæst)
- Sensorer og slider opdateres med det samme og samles under én enhed pr. rum
- Ny: `Rum Setpunkt` (number) – rummets måltemperatur kan ses og ændres som en slider
- Ny: autotune af PID (relæ-metode) med kontakt, knap og tre services
- `integration_type: hub`, så rummene vises under Integrationer (ikke Hjælpere)

## 🤝 Bidrag & support
Fejl eller ønsker? Opret et Issue eller en Pull Request.

Frontend-kort (valgfrit): [lovelace-advanced-floor-heating-card](https://github.com/OlNissen/lovelace-advanced-floor-heating-card)

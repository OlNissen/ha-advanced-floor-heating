"""Constants for the Advanced Floor Heating integration."""

DOMAIN = "advanced_floor_heating"

# Configuration Keys
CONF_ROOM_SENSOR = "room_sensor"
CONF_FLOOR_SENSOR = "floor_sensor"
CONF_HEATER_SWITCH = "heater_switch"
CONF_PUMP_SWITCH = "pump_switch"
CONF_MAX_FLOOR_TEMP = "max_floor_temp"
CONF_WINDOW_SENSOR = "window_sensor"

# Defaults
DEFAULT_MAX_FLOOR_TEMP = 32.0

# Ventilmotion: åbn ventilen kort, hvis den ikke har været åben i så mange dage (0 = slået fra)
CONF_VALVE_EXERCISE_DAYS = "valve_exercise_days"
DEFAULT_VALVE_EXERCISE_DAYS = 7
# Samme som IHC-programmet: 3 cyklusser, hver 10 min åben og 10 min lukket
VALVE_EXERCISE_CYCLES = 3
VALVE_EXERCISE_PHASE_SECONDS = 600

# Operating Modes (Presets)
# Note: These must match the strings used in climate.py exactly
PRESET_ROOM_ONLY = "Kun Rum"
PRESET_FLOOR_ONLY = "Kun Gulv"
PRESET_BOTH_1_MET = "Rum & Gulv (1 Opfyldt)"
PRESET_BOTH_BOTH_MET = "Rum & Gulv (Begge Opfyldt)"

# Attributes
ATTR_PID_SIGNAL = "pid_signal"
ATTR_CURRENT_PRIORITY = "current_priority_sensor"

# ---------------------------------------------------------------- Master (som i IHC)
# Et config-entry kan vaere et rum (standard) eller husets Master. Masteren sender
# husets tilstand ud til alle rum; hvert rum kan overstyre den med sin egen "Tilstand".
CONF_ENTRY_TYPE = "entry_type"
TYPE_ROOM = "room"
TYPE_MASTER = "master"
MASTER_KEY = "master"  # noegle i hass.data[DOMAIN]
DEFAULT_MASTER_NAME = "Gulvvarme Master"

MODE_OCCUPIED = "Beboet"       # rummet regulerer efter sine egne setpunkter
MODE_UNOCCUPIED = "Ubeboet"    # rum- og gulv-setpunkt saenkes, saa rummet holder "Ubeboet temperatur"
MODE_FROST = "Frostsikker"     # som Ubeboet, men holder kun "Frost temperatur"
MODE_OFF = "Slukket"           # ingen varme (ventilmotion koerer stadig)
HOUSE_MODES = [MODE_OCCUPIED, MODE_UNOCCUPIED, MODE_FROST, MODE_OFF]
MODE_FOLLOW = "Fælles"         # kun for rum: foelg Masteren
ROOM_MODE_OPTIONS = [MODE_FOLLOW] + HOUSE_MODES

DEFAULT_UNOCCUPIED_TEMP = 19.0
DEFAULT_FROST_TEMP = 16.0

# Udekompensation (valgfri; ke = 0 -> slaaet fra) og gamle foelere
CONF_OUTDOOR_SENSOR = "outdoor_sensor"   # sat paa Masteren
CONF_OUTDOOR_KE = "outdoor_ke"           # sat paa hvert rum, % udgang pr. grad (maal - ude)
CONF_STALE_HOURS = "stale_hours"         # foeler uden opdatering i saa mange timer -> mangler (0 = fra)
DEFAULT_STALE_HOURS = 0

# Alarmer
# Blød gulvgrænse: nær maks. gulvtemperatur regulerer PID'en efter gulvet i stedet for at slå fra og til
FLOOR_LIMIT_MARGIN = 0.3      # gulvet holdes så mange grader under maks.; det hårde stop ved maks. gælder stadig
STATUS_FLOOR_LIMIT = "Gulvgrænse"

STUCK_VALVE_MINUTES = 90      # fuld udgang saa laenge uden at gulvet stiger ...
STUCK_VALVE_MIN_RISE = 0.5    # ... mindst saa mange grader
SUPPLY_MARGIN = 3.0           # shuntens fremloeb skal vaere mindst saa mange grader over gulvmaalet, ellers ingen "ventil fast"-alarm
SENSOR_ALARM_MINUTES = 15     # foeler (eller telestat) maa mangle saa laenge, foer det er en alarm
BATTERY_LOW = 15.0            # % - alarm under denne ...
BATTERY_OK = 20.0             # ... og i orden igen fra denne

# Kontrol af kommandoer til telestaten (PWM-tiderne er uaendrede)
VERIFY_DELAY_SECONDS = 5      # saa laenge faar kontakten til at melde den nye tilstand (3 tjek = 15 s, saa det naas inden for en kort PWM-fase)
VERIFY_RETRIES = 2            # saa mange gensendelser, foer det er en alarm

# Sommerstop (graensen saettes paa Masteren; 0 = fra)
SUMMER_TAU_HOURS = 24.0       # udetemperaturen midles over ca. et doegn
SUMMER_MIN_AGE_HOURS = 6.0    # saa meget historik kraeves, foer varmen kan stoppes
SUMMER_HYSTERESIS = 1.0       # varmen taendes igen, naar middelet er saa mange grader under graensen
CONF_SUMMER_APPLIES = "summer_stop"   # paa et rum: gaelder sommerstop for rummet (standard ja)
STATUS_SUMMER = "Sommerstop (Slukket)"

# Ferie: forvarmning foer hjemkomst
PREHEAT_MARGIN_HOURS = 1.0    # laegges oven i det beregnede
PREHEAT_MAX_HOURS = 72
MASTER_TICK_MINUTES = 5

# Laert varmemodel
THERMAL_WINDOW_MINUTES = 30
THERMAL_MAX_WINDOWS = 1000          # ca. 20 doegn
THERMAL_MAX_DELAY_WINDOWS = 24      # op til 12 timers forsinkelse i gulvet
THERMAL_MIN_WINDOWS = 48
THERMAL_MIN_HEATING = 8             # vinduer med ventilen mest aaben
THERMAL_MIN_IDLE = 8                # vinduer med ventilen mest lukket
THERMAL_FALLBACK_RATE = 0.25        # °C pr. time, indtil modellen er laert
THERMAL_SAVE_DELAY = 600

# Skimmelrisiko (kraever en fugtfoeler valgt paa rummet)
CONF_HUMIDITY_SENSOR = "humidity_sensor"
MOLD_FRSI = 0.7               # DIN 4108-2: temperaturfaktor for den koldeste vaeg
MOLD_ALARM_RH = 80.0
MOLD_CLEAR_RH = 75.0
MOLD_HOLD_MINUTES = 60

# ---------------------------------------------------------------- Ude-kilde, prognose og sol
CONF_WEATHER_ENTITY = "weather_entity"     # sat paa Masteren (weather.*)
CONF_FORECAST_HOURS = "forecast_hours"     # hvor mange timer frem prognosen midles over
DEFAULT_FORECAST_HOURS = 4
CONF_SOLAR_GAIN = "solar_gain"             # sat paa hvert rum: % udgang fratrukket ved fuld sol (ks)

SOURCE_MEASURED = "Måling"
SOURCE_FORECAST = "Prognose"
SOURCE_BOTH = "Begge"
OUTDOOR_SOURCES = [SOURCE_MEASURED, SOURCE_FORECAST, SOURCE_BOTH]
DEFAULT_OUTDOOR_SOURCE = SOURCE_MEASURED

FORECAST_REFRESH_MINUTES = 30
FORECAST_MAX_AGE_HOURS = 3       # aeldre prognose bruges ikke
SOLAR_FULL_ELEVATION = 30.0      # solhoejde (grader), hvor solen regnes for "fuld"

# ---------------------------------------------------------------- Koblede rum
CONF_LINKED_ROOMS = "linked_rooms"     # climate-entiteter i samme luftrum (hvert rum vælger selv)
CONF_LINK_WEIGHT = "link_weight"       # rummets vægt i det fælles middel (f.eks. m2)
DEFAULT_LINK_WEIGHT = 1.0

# ---------------------------------------------------------------- Gennemgang, udsving og AI
REVIEW_KEY = "review"                       # noegle i hass.data[DOMAIN]
CONF_REVIEW_DAYS = "review_days"            # paa Masteren: foreslaa foerste gennemgang efter saa mange dages drift
DEFAULT_REVIEW_DAYS = 14
CONF_ALLOW_AI_CHANGES = "allow_ai_changes"  # paa Masteren: maa en AI aendre indstillinger direkte (standard nej)
REVIEW_REPEAT_DAYS = 30                     # ny gennemgang foreslaas, naar den sidste er saa gammel
HUNT_WINDOW_HOURS = 24
HUNT_BAND = 0.2                             # graders hysterese om setpunktet
HUNT_MIN_CROSSINGS = 6                      # skift mellem for koldt/for varmt i vinduet
HUNT_MIN_OUTPUT_SWING = 40.0                # procentpoint mellem laveste og hoejeste udgang
HUNT_NOTIFY_COOLDOWN_DAYS = 7
HUNT_MIN_RUNNING_DAYS = 2                   # ingen udsvings-besked de foerste dage
EVENT_REVIEW = "advanced_floor_heating_review_suggested"
# Graenser for AI-forslag (mindre aendringer ad gangen)
PARAM_BOUNDS = {
    "kp": (0.0, 200.0), "ki": (0.0, 200.0), "kd": (0.0, 200.0),
    "outdoor_ke": (0.0, 5.0), "solar_gain": (0.0, 100.0), "link_weight": (0.1, 1000.0),
}
PARAM_MAX_FACTOR = 4.0   # kp/ki/kd maa hoejst ganges/divideres med dette pr. forslag

# ---------------------------------------------------------------- Pumpegruppe (pumpestyring + shunt-raad)
TYPE_PUMP = "pump_group"
CONF_GROUP_ROOMS = "group_rooms"            # climate-entiteter i gruppen
CONF_PUMP_SWITCHES = "pump_switches"        # switches der taender pumpen (IHC "pumpestyring")
CONF_PUMP_FEEDBACK = "pump_feedback"        # binary_sensor: koerer pumpen? (valgfri, bruges til motion)
CONF_SHUNT_SENSOR = "shunt_sensor"          # sensor: shuntens fremloeb (valgfri, kun til visning/besked)
CONF_PUMP_STOP_MINUTES = "pump_stop_minutes"
DEFAULT_PUMP_STOP_MINUTES = 5               # som IHC: pumpen staar 5 min efter sidste ventil lukkede
CONF_PUMP_MOTION_DAYS = "pump_motion_days"
DEFAULT_PUMP_MOTION_DAYS = 7                # motion, hvis pumpen ikke har koert i saa mange dage (0 = fra)
PUMP_MOTION_MINUTES = 5
PUMP_MOTION_HOUR = 3
ADVICE_UP_HOURS = 3                         # "Skru op" skal have holdt saa laenge foer der gives besked
ADVICE_DOWN_HOURS = 6
ADVICE_COOLDOWN_HOURS = 24
ADVICE_OUTPUT_HIGH = 95.0                   # ventilen regnes for "helt aaben"
ADVICE_OUTPUT_LOW = 25.0
ADVICE_SHORT = 0.3                          # grader under maal
ADVICE_FLOOR_HEADROOM = 3.0                 # gulvet maa hoejst vaere saa mange grader over sit maal
ADVICE_LOW_SHARE = 0.7
EVENT_SHUNT_ADVICE = "advanced_floor_heating_shunt_advice"

# ---------------------------------------------------------------- Notifikationer (paa Masteren) og pumpegruppe pr. rum
CONF_NOTIFY_IN_HA = "notify_in_ha"          # vis beskeder som HA-notifikation (standard ja)
CONF_NOTIFY_MOBILES = "notify_mobiles"      # notify-services (mobile_app_...) der faar en push
CONF_PUMP_GROUP = "pump_group"              # paa et rum: hvilken pumpegruppe (entry_id) det hoerer til
CONF_ROOM_PUMP_SWITCH = "pump_switch"       # paa et rum: kontakten der taender pumpen for dette rum

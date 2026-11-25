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
STUCK_VALVE_MINUTES = 90      # fuld udgang saa laenge uden at gulvet stiger ...
STUCK_VALVE_MIN_RISE = 0.5    # ... mindst saa mange grader
SENSOR_ALARM_MINUTES = 15     # foeler maa mangle saa laenge, foer det er en alarm

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

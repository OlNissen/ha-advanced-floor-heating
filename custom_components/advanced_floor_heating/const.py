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

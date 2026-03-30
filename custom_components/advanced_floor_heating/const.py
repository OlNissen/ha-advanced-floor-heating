"""Constants for the Advanced Floor Heating integration."""

DOMAIN = "advanced_floor_heating"

# Configuration Keys
CONF_ROOM_SENSOR = "room_sensor"
CONF_FLOOR_SENSOR = "floor_sensor"
CONF_HEATER_SWITCH = "heater_switch"
CONF_PUMP_SWITCH = "pump_switch"
CONF_MAX_FLOOR_TEMP = "max_floor_temp"

# Operating Modes (Presets)
# Note: These must match the strings used in climate.py exactly
PRESET_ROOM_ONLY = "Room Only"
PRESET_FLOOR_ONLY = "Floor Only"
PRESET_BOTH_1_MET = "Room & Floor (1 Met)"
PRESET_BOTH_BOTH_MET = "Room & Floor (Both Met)"

# Attributes
ATTR_PID_SIGNAL = "pid_signal"
ATTR_CURRENT_PRIORITY = "current_priority_sensor"
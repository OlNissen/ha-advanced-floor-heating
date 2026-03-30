Advanced Floor Heating for Home Assistant ♨️
Advanced Floor Heating is a high-performance PID-based climate controller for Home Assistant, specifically designed for high-inertia heating systems like underfloor heating (e.g., IHC systems). This integration simultaneously manages both room and floor temperatures to ensure maximum comfort while protecting your floors from overheating.

✨ Key Features
Dual-Zone Regulation: Simultaneous control based on both ambient room sensors and floor sensors within a single entity.

Industrial PID Logic: Intelligent control with built-in Anti-Windup (Clamping) to prevent temperature overshoot.

PWM Output (Pulse Width Modulation): Converts the PID percentage output into timed ON/OFF cycles for your thermal actuators (telestats) or relays.

Restore State on Restart: Automatically restores your setpoints and the PID integral sum after a Home Assistant restart—crucial for slow-reacting systems.

4 Intelligent Preset Modes:

Room Only: Regulates based solely on air temperature.

Floor Only: Regulates based solely on floor temperature.

Room & Floor (1 Met): Prioritizes comfort (stops when the first target is reached).

Room & Floor (Both Met): Ensures both zones reach target (stops only when both targets are reached).

📸 Screenshots
(Insert your beautiful dashboard screenshots here)
![Dashboard Preview](https://raw.githubusercontent.com/OlNissen/ha-advanced-floor-heating/main/screenshots/panel_preview.png)

🚀 Installation
Via HACS (Recommended)
Open HACS in Home Assistant.

Click the three dots in the top right corner and select Custom repositories.

Paste the URL of this repository and select Integration as the category.

Restart Home Assistant.

Go to Settings -> Devices & Services -> Add Integration and search for "Advanced Floor Heating".

⚙️ Configuration
The integration is configured via the User Interface (Config Flow). You will need:

Room Sensor (sensor entity).

Floor Sensor (sensor entity).

Heater Switch (switch entity for the thermal actuator).

PID Parameters (Defaults)
Kp: 10.0 (Proportional gain)

Ki: 2.0 (Integral gain)

Kd: 1.0 (Derivative gain)

PWM Cycle: 1800s (30 minutes is recommended for floor heating).

🛠 Services
This integration provides specialized services to control the two temperature zones independently (perfect for automations or the Advanced Floor Heating Card):

advanced_floor_heating.set_room_temperature

advanced_floor_heating.set_floor_temperature

📊 Diagnostics
All PID data is exposed as attributes on your climate entity, allowing you to monitor the "brain" of your system live:

control_output: Current heating demand in %.

pid_p, pid_i, pid_d: Individual contributions from the PID terms.

pid_e: Current temperature error.

🤝 Contributing & Support
Found a bug or have a feature request? Please open an Issue or a Pull Request.

Frontend Card: Find the matching Lovelace card here: lovelace-advanced-floor-heating-card
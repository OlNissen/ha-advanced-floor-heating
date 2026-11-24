/*
 * Advanced Floor Heating Card
 * - Rum- og gulvtemperatur med træk-for-at-ændre-måltemperatur
 * - Én lille, stille linje under dial'en: hvad rummet regulerer efter
 * - Graf-knap (kurve-ikonet): historik for rum, gulv, setpunkter og effekt (6 t / 24 t / 3 d / 7 d)
 * - Pro-skuffe (tandhjulet): til/fra, tilstand, ventil og PID-data
 */
class AdvancedFloorHeatingCard extends HTMLElement {
  constructor() {
    super();
    this._isDraggingRoom = false;
    this._isDraggingFloor = false;
    this._dragRoomTemp = null;
    this._dragFloorTemp = null;
    this._timeoutRoom = null;
    this._timeoutFloor = null;
    this._showPro = false;
    this._overlay = null;
    this._graphCards = [];
    this._graphHours = 24;
    this._onKeyDown = this._onKeyDown.bind(this);
  }

  static getConfigElement() {
    return document.createElement("advanced-floor-heating-card-editor");
  }

  static getStubConfig() {
    return {
      entity: "",
      switch_entity: "",
      show_name: true,
      primary_info: "current"
    };
  }

  setConfig(config) {
    this.config = config;
  }

  disconnectedCallback() {
    this._closeGraph();
  }

  set hass(hass) {
    this._hass = hass;
    const entityId = this.config?.entity;
    const switchId = this.config?.switch_entity;

    if (!entityId || !hass.states[entityId]) {
      this.innerHTML = `
        <ha-card style="padding: 20px; text-align: center; background: var(--card-background-color); border-radius: var(--ha-card-border-radius, 12px);">
          <div style="color: var(--secondary-text-color); font-size: 16px;">Vælg venligst en klimastyring i indstillingerne.</div>
        </ha-card>`;
      this.content = false;
      return;
    }

    const state = hass.states[entityId];
    const switchState = switchId ? hass.states[switchId] : null;

    if (!this.content) {
      this.innerHTML = `
        <ha-card style="padding: 20px; background: var(--card-background-color); border-radius: var(--ha-card-border-radius, 12px); box-shadow: var(--ha-card-box-shadow, none); display: flex; flex-direction: column; align-items: center; transition: all 0.3s ease-in-out; position: relative; overflow: hidden;">

          <ha-icon icon="mdi:cog" id="btn-cog" style="position: absolute; top: 16px; right: 16px; cursor: pointer; color: var(--secondary-text-color); transition: color 0.3s;"></ha-icon>
          <ha-icon icon="mdi:chart-line" id="btn-graph" title="Vis graf" style="position: absolute; top: 16px; right: 48px; cursor: pointer; color: var(--secondary-text-color); transition: color 0.3s;"></ha-icon>

          <div id="card-title" style="font-size: 1.2rem; font-weight: 500; color: var(--primary-text-color); margin-bottom: 10px;">Gulvvarme</div>

          <div id="thermostat-wrapper" style="position: relative; width: 260px; height: 260px; transition: height 0.3s ease-in-out; overflow: hidden;">
            <div style="position: absolute; top: 0; left: 0; width: 260px; height: 260px;">
              <svg id="thermostat-svg" width="260" height="260" viewBox="0 0 260 260" style="transform: rotate(0deg); overflow: visible; touch-action: none; cursor: pointer; position: absolute; top: 0; left: 0;">
                <path id="bg-arc-room" d="M 31.5,112.6 A 100,100 0 0,1 228.5,112.6" fill="none" stroke="rgba(244, 67, 54, 0.15)" stroke-width="14" stroke-linecap="round" />
                <path id="arc-room" d="M 31.5,112.6 A 100,100 0 0,1 228.5,112.6" fill="none" stroke="#f44336" stroke-width="14" stroke-linecap="round" style="transition: stroke-dashoffset 0.3s ease-out;" stroke-dasharray="279" stroke-dashoffset="279" />
                <path id="bg-arc-floor" d="M 31.5,147.4 A 100,100 0 0,0 228.5,147.4" fill="none" stroke="rgba(255, 152, 0, 0.15)" stroke-width="14" stroke-linecap="round" />
                <path id="arc-floor" d="M 31.5,147.4 A 100,100 0 0,0 228.5,147.4" fill="none" stroke="#ff9800" stroke-width="14" stroke-linecap="round" style="transition: stroke-dashoffset 0.3s ease-out;" stroke-dasharray="279" stroke-dashoffset="279" />
                <circle id="marker-room" cx="31.5" cy="112.6" r="10" fill="#ffffff" stroke="#f44336" stroke-width="3" style="transition: cx 0.1s, cy 0.1s; filter: drop-shadow(0px 2px 4px rgba(0,0,0,0.5));" />
                <circle id="marker-floor" cx="31.5" cy="147.4" r="10" fill="#ffffff" stroke="#ff9800" stroke-width="3" style="transition: cx 0.1s, cy 0.1s; filter: drop-shadow(0px 2px 4px rgba(0,0,0,0.5));" />
              </svg>
              <div style="position: absolute; top: 0; left: 0; width: 100%; height: 100%; pointer-events: none;">
                <div id="label-top" style="position: absolute; bottom: 185px; width: 100%; text-align: center; font-size: 11px; font-weight: 600; text-transform: uppercase; letter-spacing: 1.5px; color: var(--secondary-text-color); transition: color 0.3s;">RUM</div>
                <div id="temp-top-val" style="position: absolute; bottom: 143px; width: 100%; text-align: center; font-size: 44px; font-weight: 400; color: var(--primary-text-color); line-height: 0.75;">--°</div>
                <div id="label-bottom" style="position: absolute; top: 185px; width: 100%; text-align: center; font-size: 11px; font-weight: 600; text-transform: uppercase; letter-spacing: 1.5px; color: var(--secondary-text-color); transition: color 0.3s;">GULV</div>
                <div id="temp-bottom-val" style="position: absolute; top: 141px; width: 100%; text-align: center; font-size: 44px; font-weight: 400; color: var(--primary-text-color); line-height: 0.75;">--°</div>
              </div>
            </div>
          </div>

          <div id="mode-line" style="width: 100%; text-align: center; margin-top: 4px; font-size: 11px; letter-spacing: 0.3px; color: var(--secondary-text-color); opacity: 0.8;"></div>

          <div id="pro-panel" style="display: none; width: 100%; border-top: 1px solid var(--divider-color); padding-top: 16px; margin-top: 16px;">
            <div style="display: flex; justify-content: space-between; align-items: center; border-bottom: 1px solid var(--divider-color); padding-bottom: 12px; margin-bottom: 12px; width: 100%;">
              <div style="display: flex; align-items: center; gap: 8px;">
                <ha-icon icon="mdi:power" id="btn-power" style="cursor: pointer; padding: 8px; border-radius: 50%; background: var(--secondary-background-color); transition: all 0.3s;"></ha-icon>
                <div style="display: flex; flex-direction: column;">
                  <span style="font-weight: bold; font-size: 14px; color: var(--primary-text-color);">Status</span>
                  <span id="reg-status" style="font-size: 12px; color: var(--secondary-text-color);">Læser...</span>
                </div>
              </div>

              <div id="switch-status-container" style="display: flex; flex-direction: column; align-items: flex-end;">
                <span style="font-weight: bold; font-size: 14px; color: var(--primary-text-color);">Ventil</span>
                <div style="display: flex; align-items: center; gap: 4px;">
                  <div id="switch-dot" style="width: 10px; height: 10px; border-radius: 50%; background: grey; transition: all 0.3s;"></div>
                  <span id="switch-text" style="font-size: 12px; color: var(--secondary-text-color);">Ukendt</span>
                </div>
              </div>
            </div>

            <div style="display: flex; flex-direction: column; margin-bottom: 16px; width: 100%;">
              <label style="font-size: 12px; color: var(--secondary-text-color); margin-bottom: 4px;">Tilstand</label>
              <select id="preset-select" style="padding: 8px; border-radius: 4px; border: 1px solid var(--divider-color); background: var(--card-background-color); color: var(--primary-text-color); cursor: pointer; width: 100%;">
              </select>
            </div>

            <div id="autotune-row" style="display: none; width: 100%; margin-bottom: 16px;">
              <div style="display: flex; align-items: center; justify-content: space-between; gap: 8px;">
                <span style="font-size: 12px; color: var(--secondary-text-color);">Autotune PID</span>
                <span style="display: flex; gap: 6px;">
                  <button id="at-toggle" style="padding: 4px 10px; border-radius: 6px; border: 1px solid var(--divider-color); background: var(--card-background-color); color: var(--primary-text-color); cursor: pointer; font-size: 12px;">Start</button>
                  <button id="at-apply" style="padding: 4px 10px; border-radius: 6px; border: 1px solid var(--divider-color); background: var(--card-background-color); color: var(--primary-text-color); cursor: pointer; font-size: 12px;">Anvend</button>
                </span>
              </div>
              <div id="at-status" style="font-size: 11px; color: var(--secondary-text-color); margin-top: 4px;"></div>
            </div>

            <div style="background: var(--secondary-background-color); padding: 12px; border-radius: 8px; width: 100%; box-sizing: border-box;">
              <div style="font-size: 11px; font-weight: bold; text-transform: uppercase; color: var(--secondary-text-color); margin-bottom: 8px;">PID Data</div>
              <div style="display: grid; grid-template-columns: repeat(5, 1fr); gap: 4px; text-align: center;">
                <div style="display: flex; flex-direction: column;"><span style="font-size: 10px; color: var(--secondary-text-color);">KALD</span><span id="val-out" style="font-weight: bold; color: #ff9800; font-size: 12px;">--%</span></div>
                <div style="display: flex; flex-direction: column;"><span style="font-size: 10px; color: var(--secondary-text-color);">e</span><span id="val-e" style="font-weight: bold; color: var(--primary-text-color); font-size: 12px;">--</span></div>
                <div style="display: flex; flex-direction: column;"><span style="font-size: 10px; color: var(--secondary-text-color);">P</span><span id="val-p" style="font-weight: bold; color: var(--primary-text-color); font-size: 12px;">--</span></div>
                <div style="display: flex; flex-direction: column;"><span style="font-size: 10px; color: var(--secondary-text-color);">I</span><span id="val-i" style="font-weight: bold; color: var(--primary-text-color); font-size: 12px;">--</span></div>
                <div style="display: flex; flex-direction: column;"><span style="font-size: 10px; color: var(--secondary-text-color);">D</span><span id="val-d" style="font-weight: bold; color: var(--primary-text-color); font-size: 12px;">--</span></div>
              </div>
            </div>
          </div>
        </ha-card>
      `;
      this.content = true;

      const svg = this.querySelector('#thermostat-svg');
      svg.addEventListener('pointerdown', this._onPointerDown.bind(this));
      document.addEventListener('pointermove', this._onPointerMove.bind(this));
      document.addEventListener('pointerup', this._onPointerUp.bind(this));

      this.querySelector('#btn-cog').addEventListener('click', () => {
        this._showPro = !this._showPro;
        this.querySelector('#pro-panel').style.display = this._showPro ? 'block' : 'none';
        this.querySelector('#btn-cog').style.color = this._showPro ? 'var(--primary-color)' : 'var(--secondary-text-color)';
      });

      this.querySelector('#btn-graph').addEventListener('click', () => this._openGraph());

      this.querySelector('#btn-power').addEventListener('click', () => {
        const currentMode = hass.states[entityId].state;
        const newMode = currentMode === 'off' ? 'heat' : 'off';
        hass.callService('climate', 'set_hvac_mode', { entity_id: entityId, hvac_mode: newMode });
      });

      this.querySelector('#at-toggle').addEventListener('click', () => {
        const sw = this._siblingId(/^switch\..*_autotune$/);
        if (!sw) return;
        const on = this._hass.states[sw].state === 'on';
        this._hass.callService('switch', on ? 'turn_off' : 'turn_on', { entity_id: sw });
      });
      this.querySelector('#at-apply').addEventListener('click', () => {
        const btn = this._siblingId(/^button\..*_anvend_autotune$/);
        if (btn) this._hass.callService('button', 'press', { entity_id: btn });
      });

      this.querySelector('#preset-select').addEventListener('change', (e) => {
        hass.callService('climate', 'set_preset_mode', { entity_id: entityId, preset_mode: e.target.value });
      });
    }

    const attr = state.attributes;
    const titleEl = this.querySelector('#card-title');
    if (this.config.show_name === false) {
      titleEl.style.display = 'none';
    } else {
      titleEl.style.display = 'block';
      titleEl.innerText = this.config.name || attr.friendly_name || "Gulvvarme";
    }

    // --- PRO SKUFFE OPDATERINGER ---
    const powerBtn = this.querySelector('#btn-power');
    if (state.state === 'heat') {
      powerBtn.style.color = '#f44336';
      powerBtn.style.backgroundColor = 'rgba(244, 67, 54, 0.1)';
    } else {
      powerBtn.style.color = 'var(--secondary-text-color)';
      powerBtn.style.backgroundColor = 'var(--secondary-background-color)';
    }

    this.querySelector('#reg-status').innerText = attr.regulation_status || state.state;

    if (switchId && switchState) {
      this.querySelector('#switch-status-container').style.display = 'flex';
      const s_state = switchState.state;
      this.querySelector('#switch-text').innerText = s_state === 'on' ? 'Åben (Varmer)' : 'Lukket';
      this.querySelector('#switch-dot').style.backgroundColor = s_state === 'on' ? '#f44336' : 'grey';
      this.querySelector('#switch-dot').style.boxShadow = s_state === 'on' ? '0 0 5px #f44336' : 'none';
    } else {
      this.querySelector('#switch-status-container').style.display = 'none';
    }

    const selectEl = this.querySelector('#preset-select');
    if (selectEl.children.length === 0 && attr.preset_modes) {
      attr.preset_modes.forEach(mode => {
        const option = document.createElement('option');
        option.value = mode;
        option.text = mode;
        selectEl.appendChild(option);
      });
    }
    if (attr.preset_mode && selectEl.value !== attr.preset_mode) {
      selectEl.value = attr.preset_mode;
    }

    // --- Autotune (kun i Pro-skuffen, og kun for rum med autotune-entiteter) ---
    const atSwitch = this._siblingId(/^switch\..*_autotune$/);
    const atRow = this.querySelector('#autotune-row');
    atRow.style.display = atSwitch ? 'block' : 'none';
    if (atSwitch) {
      const running = hass.states[atSwitch].state === 'on';
      this.querySelector('#at-toggle').innerText = running ? 'Stop' : 'Start';
      this.querySelector('#at-status').innerText = attr.autotune_status || '';
    }

    // --- Aflæs og afrund PID Data ---
    this.querySelector('#val-out').innerText = `${attr.control_output !== undefined ? Math.round(attr.control_output) : '--'}%`;
    this.querySelector('#val-e').innerText = `${attr.pid_e !== undefined ? Math.round(attr.pid_e) : '--'}`;
    this.querySelector('#val-p').innerText = `${attr.pid_p !== undefined ? Math.round(attr.pid_p) : '--'}`;
    this.querySelector('#val-i').innerText = `${attr.pid_i !== undefined ? Math.round(attr.pid_i) : '--'}`;
    this.querySelector('#val-d').innerText = `${attr.pid_d !== undefined ? Math.round(attr.pid_d) : '--'}`;

    // --- STANDARD TERMOSTAT OPDATERINGER ---
    const hasFloorSensor = attr.floor_temperature !== undefined || attr["Gulv_Er"] !== undefined;
    this._hasFloorSensor = hasFloorSensor;

    // Tal-sikker aflæsning: null/undefined/NaN giver 0 i stedet for at vælte kortet
    const num = (v) => (typeof v === 'number' && isFinite(v)) ? v : 0;

    const room_er = num(attr.room_temperature !== undefined ? attr.room_temperature : (attr.current_temperature || 0));
    const room_bor = num(attr.room_target_temperature !== undefined ? attr.room_target_temperature : (attr.temperature || 0));
    const floor_er = num(attr.floor_temperature !== undefined ? attr.floor_temperature : (attr["Gulv_Er"] || 0));
    const floor_bor = num(attr.floor_target_temperature !== undefined ? attr.floor_target_temperature : (attr["Gulv_Bør"] || 0));
    const reg_status = attr.regulation_status || attr["Regulerer efter"] || "";

    const showTarget = (this.config.primary_info === "target");

    let temp_top = showTarget ? room_bor : room_er;
    let temp_bottom = showTarget ? floor_bor : floor_er;
    let text_top = "RUM";
    let text_bottom = "GULV";

    if (reg_status === "Kun Gulv" || reg_status === "Floor Only" || attr.preset_mode === "Kun Gulv") {
      temp_top = showTarget ? floor_bor : floor_er;
      temp_bottom = showTarget ? room_bor : room_er;
      text_top = "GULV";
      text_bottom = "RUM";
    }

    if (!this._isDraggingRoom && !this._timeoutRoom) {
      this.querySelector('#temp-top-val').innerText = `${temp_top.toFixed(1)}°`;
      this.querySelector('#label-top').innerText = text_top;
      this.querySelector('#label-top').style.color = "var(--secondary-text-color)";
    }

    if (!hasFloorSensor) {
      this.querySelector('#bg-arc-floor').style.display = 'none';
      this.querySelector('#arc-floor').style.display = 'none';
      this.querySelector('#marker-floor').style.display = 'none';
      this.querySelector('#temp-bottom-val').style.display = 'none';
      this.querySelector('#label-bottom').style.display = 'none';
      this.querySelector('#thermostat-wrapper').style.height = '135px';
    } else {
      this.querySelector('#bg-arc-floor').style.display = 'block';
      this.querySelector('#arc-floor').style.display = 'block';
      this.querySelector('#marker-floor').style.display = 'block';
      this.querySelector('#temp-bottom-val').style.display = 'block';
      this.querySelector('#label-bottom').style.display = 'block';
      this.querySelector('#thermostat-wrapper').style.height = '260px';

      if (!this._isDraggingFloor && !this._timeoutFloor) {
        this.querySelector('#temp-bottom-val').innerText = `${temp_bottom.toFixed(1)}°`;
        this.querySelector('#label-bottom').innerText = text_bottom;
        this.querySelector('#label-bottom').style.color = "var(--secondary-text-color)";
      }
    }

    // --- TILSTAND: én lille, stille linje om hvad rummet regulerer efter ---
    const modeEl = this.querySelector('#mode-line');
    let mode = '';
    if (state.state === 'off') {
      mode = 'Slukket';
    } else if (attr.output_frozen) {
      mode = 'Vindue åbent – udgang holdes';
    } else if (attr.autotune_active) {
      mode = 'Autotune kører';
    } else if (/^Sikkerhedsstop/.test(reg_status)) {
      mode = 'Sikkerhedsstop – gulv for varmt';
    } else if (/mangler/i.test(reg_status)) {
      mode = reg_status.replace(/\s*\(.*\)\s*$/, '');
    } else if (/^Kun Rum$/.test(reg_status) || /^Kun Gulv$/.test(reg_status)) {
      mode = `Regulerer kun efter ${reg_status.slice(4).toLowerCase()}`;
    } else if (/^(Rum|Gulv)( |$)/.test(reg_status)) {
      mode = `Regulerer efter ${reg_status.split(' ')[0].toLowerCase()}`;
    } else if (/^Mål nået/.test(reg_status)) {
      mode = 'Mål nået';
    }
    modeEl.innerText = mode;
    modeEl.style.display = mode ? 'block' : 'none';
    modeEl.style.color = (attr.output_frozen || attr.autotune_active) ? 'var(--primary-color)' : 'var(--secondary-text-color)';

    const minT = 15;
    const maxT = 30;
    const range = maxT - minT;
    const arcLength = 279;

    let roomPercent = (Math.max(minT, Math.min(maxT, room_er)) - minT) / range;
    this.querySelector('#arc-room').style.strokeDashoffset = arcLength - (roomPercent * arcLength);

    if (!this._isDraggingRoom) {
      let roomBorPercent = (Math.max(minT, Math.min(maxT, room_bor)) - minT) / range;
      let roomMarkerAngle = 190 + (roomBorPercent * 160);
      let roomMarkerRad = roomMarkerAngle * Math.PI / 180;
      this.querySelector('#marker-room').setAttribute('cx', 130 + 100 * Math.cos(roomMarkerRad));
      this.querySelector('#marker-room').setAttribute('cy', 130 + 100 * Math.sin(roomMarkerRad));
    }

    if (hasFloorSensor) {
      let floorPercent = (Math.max(minT, Math.min(maxT, floor_er)) - minT) / range;
      this.querySelector('#arc-floor').style.strokeDashoffset = arcLength - (floorPercent * arcLength);

      if (!this._isDraggingFloor) {
        let floorBorPercent = (Math.max(minT, Math.min(maxT, floor_bor)) - minT) / range;
        let floorMarkerAngle = 170 - (floorBorPercent * 160);
        let floorMarkerRad = floorMarkerAngle * Math.PI / 180;
        this.querySelector('#marker-floor').setAttribute('cx', 130 + 100 * Math.cos(floorMarkerRad));
        this.querySelector('#marker-floor').setAttribute('cy', 130 + 100 * Math.sin(floorMarkerRad));
      }
    }

    // Hold graferne (hvis de er åbne) opdateret
    this._graphCards.forEach(c => { c.hass = hass; });
  }

  // Find en søster-entitet (samme enhed/rum) ud fra et navnemønster
  _siblingId(re) {
    const hass = this._hass;
    const reg = hass && hass.entities;
    const dev = reg && reg[this.config.entity] ? reg[this.config.entity].device_id : null;
    if (!dev) return null;
    return Object.keys(reg).find(id => reg[id].device_id === dev && re.test(id) && hass.states[id]) || null;
  }

  // ------------------------------------------------------------------ GRAF

  _graphEntities() {
    const hass = this._hass;
    const entityId = this.config.entity;
    const attr = hass.states[entityId].attributes;
    const registry = hass.entities || {};
    const deviceId = registry[entityId] ? registry[entityId].device_id : null;
    const siblings = deviceId ? Object.keys(registry).filter(id => registry[id].device_id === deviceId) : [];
    const find = (re) => siblings.find(id => re.test(id) && hass.states[id]);
    const ok = (id) => id && hass.states[id];

    const temps = [];
    const add = (list, id, name) => { if (ok(id) && !list.some(x => x.entity === id)) list.push({ entity: id, name }); };

    add(temps, attr.room_sensor, 'Rum');
    add(temps, attr.floor_sensor, 'Gulv');
    add(temps, find(/^number\..*_rum_setpunkt$/), 'Rum setpunkt');
    add(temps, find(/^number\..*_gulv_setpunkt$/), 'Gulv setpunkt');
    // Ældre/andre klimastyringer uden sensor-attributter: selve klima-entiteten viser aktuel + ønsket
    if (temps.length === 0) add(temps, entityId, this.config.name || attr.friendly_name || 'Temperatur');

    const power = [];
    add(power, find(/^sensor\..*_pid_signal$/), 'Effekt');
    add(power, this.config.switch_entity || attr.heater_switch, 'Ventil');
    return { temps, power };
  }

  async _openGraph() {
    if (this._overlay || !this._hass) return;
    const overlay = document.createElement('div');
    overlay.style.cssText = 'position:fixed;top:0;left:0;right:0;bottom:0;z-index:9999;background:rgba(0,0,0,0.6);display:flex;align-items:center;justify-content:center;padding:12px;box-sizing:border-box;';
    overlay.innerHTML = `
      <div style="background:var(--card-background-color,#1c1c1c);color:var(--primary-text-color,#fff);border-radius:12px;width:100%;max-width:780px;max-height:92vh;overflow:auto;padding:12px 16px 16px;box-sizing:border-box;box-shadow:0 8px 30px rgba(0,0,0,0.5);">
        <div style="display:flex;align-items:center;justify-content:space-between;gap:8px;margin-bottom:8px;flex-wrap:wrap;">
          <div id="g-title" style="font-size:1.1rem;font-weight:500;"></div>
          <div id="g-ranges" style="display:flex;gap:6px;flex-wrap:wrap;"></div>
          <ha-icon icon="mdi:close" id="g-close" style="cursor:pointer;"></ha-icon>
        </div>
        <div id="g-body"></div>
      </div>`;
    // Skal ligge inde i HA's komponent-træ (ikke i document.body), ellers mangler graf-kortene
    // oversættelser/kontekst og tegner ikke noget.
    this.appendChild(overlay);
    this._overlay = overlay;

    const attr = this._hass.states[this.config.entity].attributes;
    overlay.querySelector('#g-title').innerText = `${this.config.name || attr.friendly_name || 'Gulvvarme'} – temperaturer`;
    overlay.querySelector('#g-close').addEventListener('click', () => this._closeGraph());
    overlay.addEventListener('click', (e) => { if (e.target === overlay) this._closeGraph(); });
    document.addEventListener('keydown', this._onKeyDown);

    const ranges = [[6, '6 t'], [24, '24 t'], [72, '3 d'], [168, '7 d']];
    const box = overlay.querySelector('#g-ranges');
    ranges.forEach(([h, label]) => {
      const b = document.createElement('button');
      b.dataset.hours = h;
      b.innerText = label;
      b.style.cssText = 'padding:4px 10px;border-radius:14px;border:1px solid var(--divider-color);cursor:pointer;font-size:12px;';
      b.addEventListener('click', () => { this._graphHours = h; this._renderGraph(); });
      box.appendChild(b);
    });
    await this._renderGraph();
  }

  async _renderGraph() {
    if (!this._overlay) return;
    const body = this._overlay.querySelector('#g-body');
    body.innerHTML = '';
    this._graphCards = [];

    this._overlay.querySelectorAll('#g-ranges button').forEach(b => {
      const active = Number(b.dataset.hours) === this._graphHours;
      b.style.background = active ? 'var(--primary-color)' : 'var(--secondary-background-color)';
      b.style.color = active ? 'var(--text-primary-color, #fff)' : 'var(--primary-text-color)';
    });

    const { temps, power } = this._graphEntities();
    const helpers = await window.loadCardHelpers();
    const make = async (title, entities) => {
      if (!entities.length) return;
      const card = await helpers.createCardElement({
        type: 'history-graph',
        title,
        hours_to_show: this._graphHours,
        entities
      });
      card.hass = this._hass;
      card.style.display = 'block';
      card.style.marginBottom = '8px';
      body.appendChild(card);
      this._graphCards.push(card);
    };
    await make('Temperaturer', temps);
    await make('Effekt og ventil', power);
  }

  _onKeyDown(e) {
    if (e.key === 'Escape') this._closeGraph();
  }

  _closeGraph() {
    document.removeEventListener('keydown', this._onKeyDown);
    if (this._overlay) {
      this._overlay.remove();
      this._overlay = null;
    }
    this._graphCards = [];
  }

  // ------------------------------------------------------------------ TRÆK

  _onPointerDown(e) {
    const svg = this.querySelector('#thermostat-svg');
    const rect = svg.getBoundingClientRect();
    const x = e.clientX - rect.left - 130;
    const y = e.clientY - rect.top - 130;

    const distance = Math.sqrt(x*x + y*y);
    if (distance > 70 && distance < 130) {
      svg.setPointerCapture(e.pointerId);
      if (y < 0) {
        this._isDraggingRoom = true;
        clearTimeout(this._timeoutRoom);
        this._timeoutRoom = null;
      } else if (this._hasFloorSensor) {
        this._isDraggingFloor = true;
        clearTimeout(this._timeoutFloor);
        this._timeoutFloor = null;
      }
      this._onPointerMove(e);
    }
  }

  _onPointerMove(e) {
    if (!this._isDraggingRoom && !this._isDraggingFloor) return;

    const svg = this.querySelector('#thermostat-svg');
    const rect = svg.getBoundingClientRect();
    const x = e.clientX - rect.left - 130;
    const y = e.clientY - rect.top - 130;

    let angle = Math.atan2(y, x) * (180 / Math.PI);
    const minT = 15;
    const maxT = 30;

    if (this._isDraggingRoom) {
      if (angle > 0) angle -= 360;
      if (angle < -170) angle = -170;
      if (angle > -10) angle = -10;

      let percent = (angle - (-170)) / 160;
      let temp = minT + percent * (maxT - minT);
      temp = Math.round(temp * 2) / 2;
      this._dragRoomTemp = temp;

      let rad = angle * (Math.PI / 180);
      this.querySelector('#marker-room').setAttribute('cx', 130 + 100 * Math.cos(rad));
      this.querySelector('#marker-room').setAttribute('cy', 130 + 100 * Math.sin(rad));

      this.querySelector('#temp-top-val').innerText = `${temp.toFixed(1)}°`;
      this.querySelector('#label-top').innerText = "BØR";
      this.querySelector('#label-top').style.color = "#f44336";
    }

    if (this._isDraggingFloor) {
      if (angle < 0 && angle > -90) angle = 10;
      if (angle < 0 && angle <= -90) angle = 170;
      if (angle > 170) angle = 170;
      if (angle < 10) angle = 10;

      let percent = (170 - angle) / 160;
      let temp = minT + percent * (maxT - minT);
      temp = Math.round(temp * 2) / 2;
      this._dragFloorTemp = temp;

      let rad = angle * (Math.PI / 180);
      this.querySelector('#marker-floor').setAttribute('cx', 130 + 100 * Math.cos(rad));
      this.querySelector('#marker-floor').setAttribute('cy', 130 + 100 * Math.sin(rad));

      this.querySelector('#temp-bottom-val').innerText = `${temp.toFixed(1)}°`;
      this.querySelector('#label-bottom').innerText = "BØR";
      this.querySelector('#label-bottom').style.color = "#ff9800";
    }
  }

  _onPointerUp(e) {
    if (this._isDraggingRoom) {
      this._isDraggingRoom = false;

      if (this._hasFloorSensor) {
          this._hass.callService("advanced_floor_heating", "set_room_temperature", {
            entity_id: this.config.entity,
            temperature: this._dragRoomTemp
          });
      } else {
          this._hass.callService("climate", "set_temperature", {
            entity_id: this.config.entity,
            temperature: this._dragRoomTemp
          });
      }

      this._timeoutRoom = setTimeout(() => {
        this._timeoutRoom = null;
        if (this._hass) this.hass = this._hass;
      }, 2000);
    }

    if (this._isDraggingFloor) {
      this._isDraggingFloor = false;

      this._hass.callService("advanced_floor_heating", "set_floor_temperature", {
        entity_id: this.config.entity,
        temperature: this._dragFloorTemp
      });

      this._timeoutFloor = setTimeout(() => {
        this._timeoutFloor = null;
        if (this._hass) this.hass = this._hass;
      }, 2000);
    }
  }
}

// Sikkerheds-tjek mod genindlæsnings-crashes
if (!customElements.get("advanced-floor-heating-card")) {
  customElements.define("advanced-floor-heating-card", AdvancedFloorHeatingCard);
}

class AdvancedFloorHeatingCardEditor extends HTMLElement {
  constructor() {
    super();
    this._config = {};
    this._rendered = false;
  }

  setConfig(config) {
    this._config = { ...config };
    if (!this._rendered) {
      this.renderForm();
    }
  }

  set hass(hass) {
    this._hass = hass;
    if (!this._rendered) {
      this.renderForm();
    }
  }

  renderForm() {
    if (!this._hass || !this._config || this._config.entity === undefined) return;
    this._rendered = true;

    const climateEntities = Object.keys(this._hass.states).filter(eid => eid.startsWith('climate.'));
    const switchEntities = Object.keys(this._hass.states).filter(eid => eid.startsWith('switch.'));

    let climateOptions = `<option value="" disabled ${!this._config.entity ? 'selected' : ''}>Vælg en klimastyring...</option>`;
    climateEntities.forEach(eid => {
      const name = this._hass.states[eid].attributes.friendly_name || eid;
      const isSelected = (this._config.entity === eid) ? 'selected' : '';
      climateOptions += `<option value="${eid}" ${isSelected}>${name} (${eid})</option>`;
    });

    let switchOptions = `<option value="" ${!this._config.switch_entity ? 'selected' : ''}>Ingen Udgang Valgt (Skjuler lys)</option>`;
    switchEntities.forEach(eid => {
      const name = this._hass.states[eid].attributes.friendly_name || eid;
      const isSelected = (this._config.switch_entity === eid) ? 'selected' : '';
      switchOptions += `<option value="${eid}" ${isSelected}>${name} (${eid})</option>`;
    });

    this.innerHTML = `
      <div class="card-config" style="display: flex; flex-direction: column; gap: 16px;">
        <div style="display: flex; flex-direction: column;">
          <label style="font-size: 14px; margin-bottom: 4px; color: var(--secondary-text-color);">Entity (Klima)</label>
          <select id="entity" style="padding: 8px; border: 1px solid var(--divider-color); border-radius: 4px; background: var(--card-background-color); color: var(--primary-text-color);">
            ${climateOptions}
          </select>
        </div>

        <div style="display: flex; flex-direction: column;">
          <label style="font-size: 14px; margin-bottom: 4px; color: var(--secondary-text-color);">Udgang / Telestat (Viser om den varmer i Pro-menuen)</label>
          <select id="switch_entity" style="padding: 8px; border: 1px solid var(--divider-color); border-radius: 4px; background: var(--card-background-color); color: var(--primary-text-color);">
            ${switchOptions}
          </select>
        </div>

        <div style="display: flex; flex-direction: column;">
          <label style="font-size: 14px; margin-bottom: 4px; color: var(--secondary-text-color);">Titel / Overskrift (Valgfri)</label>
          <input type="text" id="name" placeholder="F.eks. Kontor Gulvvarme" value="${this._config.name || ''}" style="padding: 8px; border: 1px solid var(--divider-color); border-radius: 4px; background: var(--card-background-color); color: var(--primary-text-color);">
        </div>
        <div style="display: flex; align-items: center;">
          <input type="checkbox" id="show_name" ${this._config.show_name !== false ? 'checked' : ''} style="margin-right: 8px; width: 16px; height: 16px;">
          <label for="show_name" style="font-size: 14px; color: var(--primary-text-color);">Vis Titel på kortet</label>
        </div>
        <div style="display: flex; flex-direction: column;">
          <label style="font-size: 14px; margin-bottom: 4px; color: var(--secondary-text-color);">Standardvisning i midten</label>
          <select id="primary_info" style="padding: 8px; border: 1px solid var(--divider-color); border-radius: 4px; background: var(--card-background-color); color: var(--primary-text-color);">
            <option value="current" ${this._config.primary_info !== 'target' ? 'selected' : ''}>Vis Aktuel Temperatur (Er)</option>
            <option value="target" ${this._config.primary_info === 'target' ? 'selected' : ''}>Vis Ønsket Temperatur (Bør)</option>
          </select>
        </div>
      </div>
    `;

    this.querySelector('#entity').addEventListener('change', this._valueChanged.bind(this));
    this.querySelector('#switch_entity').addEventListener('change', this._valueChanged.bind(this));
    this.querySelector('#name').addEventListener('input', this._valueChanged.bind(this));
    this.querySelector('#show_name').addEventListener('change', this._valueChanged.bind(this));
    this.querySelector('#primary_info').addEventListener('change', this._valueChanged.bind(this));
  }

  _valueChanged(ev) {
    if (!this._config || !this._hass) return;
    const target = ev.target;
    let value = target.type === 'checkbox' ? target.checked : target.value;
    if (this._config[target.id] === value) return;
    this._config = { ...this._config, [target.id]: value };

    const event = new CustomEvent("config-changed", {
      detail: { config: this._config },
      bubbles: true,
      composed: true,
    });
    this.dispatchEvent(event);
  }
}

if (!customElements.get("advanced-floor-heating-card-editor")) {
  customElements.define("advanced-floor-heating-card-editor", AdvancedFloorHeatingCardEditor);
}

window.customCards = window.customCards || [];
if (!window.customCards.some(card => card.type === "advanced-floor-heating-card")) {
  window.customCards.push({
    type: "advanced-floor-heating-card",
    name: "Advanced Floor Heating",
    description: "Alt-i-ét termostatkort med graf, tilstandsvisning og Pro-Skuffe."
  });
}

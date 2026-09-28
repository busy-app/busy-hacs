/*
 * The bar on a dashboard: its screen, and everything on the device that
 * can be pressed, in the order the device has them.
 *
 * Plain DOM on purpose. A card is loaded into somebody else's frontend,
 * whose version we do not choose; the only things depended on here are
 * `hass`, `callService`, and the CSS variables every theme defines.
 */

const KEYS = [
  ["scroll_left", "chevron-left", "Scroll left"],
  ["back", "arrow-left", "Back"],
  ["ok", "check", "OK"],
  ["start", "play", "Start"],
  ["scroll_right", "chevron-right", "Scroll right"],
];

const SESSIONS = [
  ["session_busy", "BUSY"],
  ["session_custom", "CUSTOM"],
  ["session_infinite", "Quick ∞"],
  ["session_simple", "Quick timer"],
  ["session_interval", "Quick interval"],
];

const POSITIONS = ["busy", "custom", "off", "apps", "settings"];

class BusyBarCard extends HTMLElement {
  setConfig(config) {
    if (!config.device_id) {
      throw new Error("Pick a bar: set device_id");
    }
    this._config = config;
    this._built = false;
  }

  static getStubConfig(hass) {
    const entity = Object.values(hass.entities || {}).find(
      (candidate) => candidate.platform === "busy",
    );
    return { device_id: entity ? entity.device_id : "" };
  }

  getCardSize() {
    return 8;
  }

  set hass(hass) {
    this._hass = hass;
    if (!this._built) {
      this._build();
    }
    this._render();
  }

  connectedCallback() {
    // The screen is a camera, so it is fetched rather than pushed: the
    // picture is only redrawn while somebody is looking at it, which is
    // the whole reason the bar's panel is a camera and not an image.
    this._timer = window.setInterval(() => this._refreshScreen(), 1000);
  }

  disconnectedCallback() {
    window.clearInterval(this._timer);
  }

  /**
   * Every entity of this bar, by translation key - "brightness",
   * "session_busy" - which is what the rest of this card asks for.
   *
   * The translation key and not the unique id: the frontend's registry
   * is the display one, which carries the key an entity's name comes
   * from and never the unique id. Entity ids are no good either - they
   * carry the bar's name, which its owner can change.
   */
  _entities() {
    const hass = this._hass;
    const mine = {};
    for (const entry of Object.values(hass.entities || {})) {
      if (entry.device_id !== this._config.device_id) continue;
      if (!entry.translation_key) continue;
      if (!hass.states[entry.entity_id]) continue;
      mine[entry.translation_key] = entry.entity_id;
    }
    return mine;
  }

  _call(domain, service, data) {
    this._hass.callService(domain, service, data);
  }

  _build() {
    this.innerHTML = `
      <ha-card>
        <div class="screen"><img alt="" /></div>
        <div class="row positions"></div>
        <div class="row sessions"></div>
        <div class="running"></div>
        <div class="sliders"></div>
        <div class="row keys"></div>
      </ha-card>
      <style>
        ha-card { padding: 12px; }
        .screen {
          background: #000;
          border-radius: 8px;
          display: flex;
          justify-content: center;
          margin-bottom: 12px;
          overflow: hidden;
        }
        .screen img {
          height: 128px;
          image-rendering: pixelated;
          width: 128px;
        }
        .row { display: flex; flex-wrap: wrap; gap: 6px; margin-bottom: 10px; }
        button {
          background: var(--card-background-color, #fff);
          border: 1px solid var(--divider-color, #ddd);
          border-radius: 18px;
          color: var(--primary-text-color);
          cursor: pointer;
          flex: 1 1 auto;
          font: inherit;
          min-height: 36px;
          padding: 6px 12px;
        }
        button:hover { border-color: var(--primary-color); }
        button[aria-pressed="true"] {
          background: var(--primary-color);
          border-color: var(--primary-color);
          color: var(--text-primary-color, #fff);
        }
        .running {
          color: var(--secondary-text-color);
          margin-bottom: 10px;
          min-height: 20px;
        }
        .sliders label {
          align-items: center;
          display: flex;
          gap: 10px;
          margin-bottom: 8px;
        }
        .sliders span { color: var(--secondary-text-color); width: 84px; }
        .sliders input { flex: 1; }
        .keys button { flex: 1 1 60px; }
      </style>
    `;
    this._built = true;
  }

  _refreshScreen() {
    const image = this.querySelector(".screen img");
    if (!image || !this._hass) return;
    const camera = this._entities().screen;
    const state = camera && this._hass.states[camera];
    const picture = state && state.attributes.entity_picture;
    if (picture) {
      image.src = `${picture}&_=${Date.now()}`;
    }
  }

  _render() {
    const hass = this._hass;
    const mine = this._entities();
    const state = (key) => (mine[key] ? hass.states[mine[key]] : undefined);

    const positions = this.querySelector(".positions");
    const at = state("switch_position");
    positions.innerHTML = "";
    for (const position of POSITIONS) {
      const button = document.createElement("button");
      button.textContent = position.toUpperCase();
      button.setAttribute("aria-pressed", String(at && at.state === position));
      button.onclick = () =>
        this._call("select", "select_option", {
          entity_id: mine.switch_position,
          option: position,
        });
      positions.append(button);
    }

    const sessions = this.querySelector(".sessions");
    sessions.innerHTML = "";
    for (const [key, label] of SESSIONS) {
      if (!mine[key]) continue;
      const on = state(key) && state(key).state === "on";
      const button = document.createElement("button");
      button.textContent = label;
      button.setAttribute("aria-pressed", String(on));
      button.onclick = () =>
        this._call("switch", on ? "turn_off" : "turn_on", {
          entity_id: mine[key],
        });
      sessions.append(button);
    }

    this._renderRunning(mine, state);

    const sliders = this.querySelector(".sliders");
    if (!sliders.dataset.ready) {
      sliders.innerHTML = "";
      for (const [key, label] of [
        ["brightness", "Brightness"],
        ["volume", "Volume"],
      ]) {
        if (!mine[key]) continue;
        const row = document.createElement("label");
        row.innerHTML = `<span>${label}</span><input type="range" min="0" max="100" />`;
        const input = row.querySelector("input");
        input.dataset.key = key;
        input.onchange = () =>
          this._call("number", "set_value", {
            entity_id: mine[key],
            value: Number(input.value),
          });
        sliders.append(row);
      }
      sliders.dataset.ready = "1";
    }
    for (const input of sliders.querySelectorAll("input")) {
      const value = state(input.dataset.key);
      // Not while it is being dragged: writing the old value back under
      // a thumb somebody is holding is how a slider fights its owner.
      if (value && document.activeElement !== input) {
        input.value = value.state;
      }
    }

    const keys = this.querySelector(".keys");
    keys.innerHTML = "";
    for (const [key, , label] of KEYS) {
      if (!mine[key]) continue;
      const button = document.createElement("button");
      button.textContent = label;
      button.onclick = () =>
        this._call("button", "press", { entity_id: mine[key] });
      keys.append(button);
    }
  }

  _renderRunning(mine, state) {
    const running = this.querySelector(".running");
    const live = state("session_running");
    if (!live || live.state !== "on") {
      running.textContent = "No session running";
      return;
    }
    const type = state("session_type");
    const phase = state("session_phase");
    const ends = state("session_phase_ends");
    const parts = [];
    if (type && type.state !== "unknown") parts.push(type.state);
    if (phase && phase.state !== "unknown") parts.push(phase.state);
    if (ends && ends.state !== "unknown" && ends.state !== "unavailable") {
      const at = new Date(ends.state);
      if (!Number.isNaN(at.valueOf())) {
        parts.push(
          `until ${at.toLocaleTimeString([], {
            hour: "2-digit",
            minute: "2-digit",
          })}`,
        );
      }
    }
    running.textContent = parts.join(" · ");
  }
}

customElements.define("busy-bar-card", BusyBarCard);

window.customCards = window.customCards || [];
window.customCards.push({
  type: "busy-bar-card",
  name: "BUSY Bar",
  description: "The bar's screen and every control it has",
});

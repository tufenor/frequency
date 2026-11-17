/* Compatibility layer for older Android browsers such as Galaxy Tab 3. */
(function () {
  // Modern browsers keep using the complete monitor controller.
  if (window.fetch && window.Promise && window.URLSearchParams) return;

  var keyName = "frequency.monitor_key";
  var sessionName = "frequency.monitor_session";
  var monitorKey = "";
  var monitorSession = "";
  var lastEventId = 0;
  var timer = null;
  var connected = false;

  function byId(id) { return document.getElementById(id); }
  function language() {
    var select = byId("monitor-language");
    return select && select.value === "es-BO" ? "es" : "pt";
  }
  function text(pt, es) { return language() === "es" ? es : pt; }
  function show(id, value) { var node = byId(id); if (node) node.textContent = value; }
  function visible(id, value) { var node = byId(id); if (node) node.hidden = !value; }
  function setConnection(value) {
    connected = value;
    var dot = document.querySelector(".connection-indicator");
    if (dot) dot.className = "connection-indicator" + (value ? " online" : "");
    show("connection-label", value ? text("Monitor conectado", "Monitor conectado") : text("Aguardando conexão", "Esperando conexión"));
    if (!value) {
      show("screen-error", text("Sem conexão com o sistema. Verifique a rede.", "Sin conexión con el sistema. Revisa la red."));
      visible("screen-error", true);
    } else visible("screen-error", false);
  }
  function headers(xhr) {
    xhr.setRequestHeader("X-Monitor-Key", monitorKey);
    xhr.setRequestHeader("X-Monitor-Session", monitorSession);
    xhr.setRequestHeader("Accept", "application/json");
  }
  function request(method, url, callback) {
    var xhr = new XMLHttpRequest();
    try {
      xhr.open(method, url, true);
      headers(xhr);
      xhr.onreadystatechange = function () {
        if (xhr.readyState !== 4) return;
        var data = null;
        try { data = xhr.responseText ? JSON.parse(xhr.responseText) : {}; } catch (ignore) { data = {}; }
        callback(xhr.status, data);
      };
      xhr.onerror = function () { callback(0, {}); };
      xhr.send(null);
    } catch (error) { callback(0, {}); }
  }
  function normalize(value) { return String(value || "").replace(/[\s-]+/g, "").toUpperCase(); }
  function connect(value) {
    monitorKey = normalize(value);
    if (!monitorKey) return;
    try { sessionStorage.setItem(keyName, monitorKey); sessionStorage.setItem(sessionName, monitorSession); } catch (ignore) {}
    request("GET", "/monitor/estado", function (status, data) {
      if (status === 200) {
        show("academy-name", data.academia || "Frequency Gym");
        show("monitor-label", (data.monitor_nome || "Monitor") + " · " + (data.monitor_numero || "1"));
        visible("monitor-label", true);
        visible("key-dialog", false);
        setConnection(true);
        lastEventId = Number(data.ultimo_evento || 0);
        poll();
      } else if (status === 401) {
        show("key-error", text("Código inválido. Confira com o dono da academia.", "Código inválido. Consulta al propietario del gimnasio."));
        visible("key-error", true);
        setConnection(false);
      } else {
        show("key-error", text("Sem conexão com o sistema. Verifique a rede.", "Sin conexión con el sistema. Revisa la red."));
        visible("key-error", true);
        setConnection(false);
      }
    });
  }
  function poll() {
    if (!monitorKey) return;
    request("GET", "/monitor/eventos?depois=" + encodeURIComponent(lastEventId), function (status, data) {
      if (status === 200) {
        setConnection(true);
        if (data && data.length) {
          var event = data[data.length - 1];
          lastEventId = Number(event.id || lastEventId);
          var card = byId("access-card");
          if (card) card.className = "access-card " + (event.liberado ? "allowed" : "denied");
          show("access-title", event.liberado ? text("Entrada liberada", "Acceso autorizado") : text("Acesso não liberado", "Acceso no autorizado"));
          show("access-message", event.nome ? (text("Olá, ", "Hola, ") + event.nome) : text("Procure a recepção.", "Acércate a recepción."));
        }
      } else if (status === 401) {
        visible("key-dialog", true);
        show("key-error", text("Código inválido. Confira com o dono da academia.", "Código inválido. Consulta al propietario del gimnasio."));
        visible("key-error", true);
        monitorKey = "";
      } else setConnection(false);
      if (monitorKey) timer = window.setTimeout(poll, 1200);
    });
  }
  function release() {
    if (!monitorKey) return;
    try {
      var xhr = new XMLHttpRequest();
      xhr.open("DELETE", "/monitor/sessao", false);
      headers(xhr);
      xhr.send(null);
    } catch (ignore) {}
  }
  function init() {
    monitorSession = String(new Date().getTime()) + "-legacy-" + String(Math.random()).slice(2);
    try { monitorKey = sessionStorage.getItem(keyName) || ""; } catch (ignore) { monitorKey = ""; }
    var form = byId("key-form");
    if (form) form.onsubmit = function (event) { if (event && event.preventDefault) event.preventDefault(); connect(byId("monitor-key").value); return false; };
    window.onpagehide = release;
    window.onbeforeunload = release;
    if (monitorKey) connect(monitorKey);
  }
  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", init); else init();
}());

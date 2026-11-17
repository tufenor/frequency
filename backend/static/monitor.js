const $ = (selector) => document.querySelector(selector);
const keyStorage = "frequency.monitor_key";
const languageStorage = "frequency.monitor_language";
let monitorKey = sessionStorage.getItem(keyStorage) || "";
let language = localStorage.getItem(languageStorage) ||
  (navigator.language?.toLowerCase().startsWith("es") ? "es-BO" : "pt-BR");
let lastEventId = 0;
let pollTimer = null;
let clearTimer = null;
let soundContext = null;
let soundEnabled = false;
let logoUrl = null;
let photoUrl = null;

const text = {
  "pt-BR": {
    title: "Tela de entrada", greeting: "BEM-VINDO À", kicker: "FREQUENCY · ACESSO",
    idleTitle: "Aproxime sua digital", idleMessage: "A catraca mostrará o resultado da sua entrada aqui.",
    hint: "Sua informação aparece por alguns segundos e depois é removida.", signature: "Acesso protegido por",
    activate: "Ativar som", soundOn: "Som ativo", online: "Monitor conectado", waiting: "Aguardando conexão",
    granted: "Entrada liberada", hello: (name) => `Olá, ${name}`, overdue: "Há uma pendência na mensalidade. Procure a recepção.",
    denied: "Acesso não liberado. Procure a recepção.", unknown: "Cadastro não encontrado", language: "Idioma",
    connect: "Conectar esta tela", keyInfo: "Cole o código criado pelo dono da academia. Este código só mostra resultados de novas entradas.",
    keyLabel: "Código de conexão", connectButton: "Conectar monitor", wrongKey: "Código inválido. Confira com o dono da academia.",
    networkError: "Sem conexão com o sistema. Verifique a rede.", time: (date) => new Intl.DateTimeFormat(language, { hour: "2-digit", minute: "2-digit" }).format(new Date(date)),
  },
  "es-BO": {
    title: "Pantalla de acceso", greeting: "TE DAMOS LA BIENVENIDA A", kicker: "FREQUENCY · ACCESO",
    idleTitle: "Acerca tu huella", idleMessage: "El torniquete mostrará aquí el resultado de tu acceso.",
    hint: "Tu información aparecerá unos segundos y luego se borrará.", signature: "Acceso protegido por",
    activate: "Activar sonido", soundOn: "Sonido activo", online: "Monitor conectado", waiting: "Esperando conexión",
    granted: "Acceso autorizado", hello: (name) => `Hola, ${name}`, overdue: "Hay una mensualidad pendiente. Acércate a recepción.",
    denied: "Acceso no autorizado. Acércate a recepción.", unknown: "No encontramos tu registro", language: "Idioma",
    connect: "Conectar esta pantalla", keyInfo: "Pega el código creado por el propietario. Este código solo muestra resultados de nuevos accesos.",
    keyLabel: "Código de conexión", connectButton: "Conectar monitor", wrongKey: "Código inválido. Consulta al propietario del gimnasio.",
    networkError: "Sin conexión con el sistema. Revisa la red.", time: (date) => new Intl.DateTimeFormat(language, { hour: "2-digit", minute: "2-digit" }).format(new Date(date)),
  },
  en: {
    title: "Entry screen", greeting: "WELCOME TO", kicker: "FREQUENCY · ENTRY",
    idleTitle: "Scan your fingerprint", idleMessage: "The turnstile will show your entry result here.",
    hint: "Your information appears for a few seconds, then clears.", signature: "Access protected by",
    activate: "Enable sound", soundOn: "Sound on", online: "Monitor connected", waiting: "Waiting for connection",
    granted: "Entry approved", hello: (name) => `Hello, ${name}`, overdue: "There is an outstanding membership payment. Please see reception.",
    denied: "Entry not approved. Please see reception.", unknown: "We couldn't find your record", language: "Language",
    connect: "Connect this screen", keyInfo: "Paste the code created by the gym owner. This code only shows results for new entries.",
    keyLabel: "Connection code", connectButton: "Connect monitor", wrongKey: "Invalid code. Please check with the gym owner.",
    networkError: "No connection to the system. Check the network.", time: (date) => new Intl.DateTimeFormat(language, { hour: "2-digit", minute: "2-digit" }).format(new Date(date)),
  },
  "zh-CN": {
    title: "入场屏幕", greeting: "欢迎来到", kicker: "FREQUENCY · 入场",
    idleTitle: "请扫描指纹", idleMessage: "闸机将在这里显示您的入场结果。", hint: "您的信息显示几秒后将自动清除。",
    signature: "入场系统由", activate: "开启声音", soundOn: "声音已开启", online: "屏幕已连接", waiting: "等待连接",
    granted: "允许入场", hello: (name) => `您好，${name}`, overdue: "会员费用尚未结清，请联系前台。", denied: "未获准入场，请联系前台。",
    unknown: "未找到您的记录", language: "语言", connect: "连接此屏幕", keyInfo: "请输入健身房负责人创建的代码。此代码仅显示新的入场结果。",
    keyLabel: "连接代码", connectButton: "连接屏幕", wrongKey: "代码无效，请联系健身房负责人。", networkError: "系统连接中断，请检查网络。",
    time: (date) => new Intl.DateTimeFormat(language, { hour: "2-digit", minute: "2-digit" }).format(new Date(date)),
  },
  "hi-IN": {
    title: "प्रवेश स्क्रीन", greeting: "आपका स्वागत है", kicker: "FREQUENCY · प्रवेश",
    idleTitle: "अपनी उंगली स्कैन करें", idleMessage: "टर्नस्टाइल यहाँ आपके प्रवेश का परिणाम दिखाएगा।",
    hint: "आपकी जानकारी कुछ सेकंड दिखेगी और फिर हट जाएगी।", signature: "सुरक्षित प्रवेश",
    activate: "आवाज़ चालू करें", soundOn: "आवाज़ चालू", online: "मॉनिटर जुड़ा है", waiting: "कनेक्शन की प्रतीक्षा",
    granted: "प्रवेश की अनुमति है", hello: (name) => `नमस्ते, ${name}`, overdue: "सदस्यता भुगतान बाकी है। कृपया रिसेप्शन से संपर्क करें।",
    denied: "प्रवेश की अनुमति नहीं है। रिसेप्शन से संपर्क करें।", unknown: "आपका रिकॉर्ड नहीं मिला", language: "भाषा",
    connect: "इस स्क्रीन को जोड़ें", keyInfo: "जिम मालिक द्वारा बनाया गया कोड दर्ज करें। यह कोड केवल नई प्रविष्टियों का परिणाम दिखाता है।",
    keyLabel: "कनेक्शन कोड", connectButton: "मॉनिटर जोड़ें", wrongKey: "कोड गलत है। जिम मालिक से संपर्क करें।", networkError: "सिस्टम से कनेक्शन नहीं है। नेटवर्क जांचें।",
    time: (date) => new Intl.DateTimeFormat(language, { hour: "2-digit", minute: "2-digit" }).format(new Date(date)),
  },
};
if (!text[language]) language = "pt-BR";
const tr = (key) => text[language][key];

function applyLanguage() {
  document.documentElement.lang = language;
  document.title = tr("title");
  $("#monitor-language").value = language;
  $("#brand-greeting").textContent = tr("greeting");
  $("#access-kicker").textContent = tr("kicker");
  $("#monitor-footer-hint").textContent = tr("hint");
  $("#frequency-signature").replaceChildren(document.createTextNode(`${tr("signature")} `), Object.assign(document.createElement("strong"), { textContent: "Frequency" }));
  $("#sound-button").textContent = soundEnabled ? tr("soundOn") : tr("activate");
  $("#connection-label").textContent = monitorKey ? tr("online") : tr("waiting");
  $("#language-label").textContent = tr("language");
  $("#key-title").textContent = tr("connect");
  $("#key-description").textContent = tr("keyInfo");
  $("#key-label").textContent = tr("keyLabel");
  $("#connect-button").textContent = tr("connectButton");
  if ($("#access-card").classList.contains("idle")) {
    $("#access-title").textContent = tr("idleTitle");
    $("#access-message").textContent = tr("idleMessage");
  } else {
    showCurrentEventText();
  }
}

let currentEvent = null;
function showCurrentEventText() {
  if (!currentEvent) return;
  const overdue = currentEvent.motivo === "mensalidade_atrasada";
  $("#access-title").textContent = currentEvent.liberado ? tr("granted") :
    currentEvent.motivo === "digital_nao_cadastrada" ? tr("unknown") : tr("denied");
  $("#access-message").textContent = currentEvent.liberado ? tr("hello")(currentEvent.nome) :
    overdue ? tr("overdue") : tr("denied");
}

function setConnection(connected) {
  $(".connection-indicator").classList.toggle("online", connected);
  $("#connection-label").textContent = connected ? tr("online") : tr("waiting");
  if (!connected) {
    $("#screen-error").textContent = tr("networkError");
    $("#screen-error").hidden = false;
  } else $("#screen-error").hidden = true;
}

function clearEvent() {
  currentEvent = null;
  $("#access-card").className = "access-card idle";
  $("#access-title").textContent = tr("idleTitle");
  $("#access-message").textContent = tr("idleMessage");
  $("#student-photo").hidden = true;
  $("#photo-fallback").hidden = false;
  $("#access-time").hidden = true;
  if (photoUrl) URL.revokeObjectURL(photoUrl);
  photoUrl = null;
}

function playTone(allowed) {
  if (!soundEnabled || !soundContext) return;
  const notes = allowed
    ? [{ hz: 740, start: 0, length: 0.13 }, { hz: 988, start: 0.17, length: 0.2 }]
    : [{ hz: 320, start: 0, length: 0.24 }, { hz: 220, start: 0.28, length: 0.31 }];
  for (const note of notes) {
    const oscillator = soundContext.createOscillator();
    const gain = soundContext.createGain();
    oscillator.type = allowed ? "sine" : "triangle";
    oscillator.frequency.value = note.hz;
    gain.gain.setValueAtTime(0.0001, soundContext.currentTime + note.start);
    gain.gain.exponentialRampToValueAtTime(0.16, soundContext.currentTime + note.start + 0.018);
    gain.gain.exponentialRampToValueAtTime(0.0001, soundContext.currentTime + note.start + note.length);
    oscillator.connect(gain);
    gain.connect(soundContext.destination);
    oscillator.start(soundContext.currentTime + note.start);
    oscillator.stop(soundContext.currentTime + note.start + note.length + 0.02);
  }
}

async function fetchProtectedImage(path) {
  const response = await fetch(path, {
    headers: { "X-Monitor-Key": monitorKey }, cache: "no-store",
  });
  if (!response.ok) throw new Error("image");
  return URL.createObjectURL(await response.blob());
}

async function showEvent(event) {
  currentEvent = event;
  $("#access-card").className = `access-card ${event.liberado ? "allowed" : "denied"}`;
  $("#access-kicker").textContent = tr("accessLabel") || tr("kicker");
  showCurrentEventText();
  $("#access-time").textContent = tr("time")(event.data_hora);
  $("#access-time").hidden = false;
  $("#photo-fallback").textContent = event.nome?.slice(0, 1)?.toLocaleUpperCase(language) || "F";
  $("#student-photo").hidden = true;
  $("#photo-fallback").hidden = false;
  if (photoUrl) URL.revokeObjectURL(photoUrl);
  photoUrl = null;
  if (event.liberado && event.foto_disponivel) {
    try {
      photoUrl = await fetchProtectedImage(`/monitor/eventos/${event.id}/foto`);
      $("#student-photo").src = photoUrl;
      $("#student-photo").hidden = false;
      $("#photo-fallback").hidden = true;
    } catch { /* A photo is optional; the access result still appears. */ }
  }
  playTone(event.liberado);
  if (clearTimer) clearTimeout(clearTimer);
  clearTimer = setTimeout(clearEvent, 8500);
}

async function pollEvents() {
  if (!monitorKey) return;
  try {
    const response = await fetch(`/monitor/eventos?depois=${encodeURIComponent(lastEventId)}`, {
      headers: { "X-Monitor-Key": monitorKey, Accept: "application/json" }, cache: "no-store",
    });
    if (response.status === 401) throw new Error("key");
    if (!response.ok) throw new Error("network");
    const events = await response.json();
    setConnection(true);
    for (const item of events) {
      lastEventId = Math.max(lastEventId, item.id);
      await showEvent(item);
    }
  } catch (error) {
    setConnection(false);
    if (error.message === "key") {
      sessionStorage.removeItem(keyStorage);
      monitorKey = "";
      $("#key-error").textContent = tr("wrongKey");
      $("#key-error").hidden = false;
      $("#key-dialog").hidden = false;
      clearEvent();
    }
  } finally {
    if (monitorKey) pollTimer = setTimeout(pollEvents, 750);
  }
}

async function connect(key) {
  const response = await fetch("/monitor/estado", {
    headers: { "X-Monitor-Key": key, Accept: "application/json" }, cache: "no-store",
  });
  if (!response.ok) throw new Error("key");
  const status = await response.json();
  monitorKey = key;
  sessionStorage.setItem(keyStorage, key);
  lastEventId = status.ultimo_evento;
  $("#academy-name").textContent = status.academia;
  setConnection(true);
  if (logoUrl) URL.revokeObjectURL(logoUrl);
  logoUrl = null;
  if (status.logo_cadastrada) {
    try {
      logoUrl = await fetchProtectedImage("/monitor/logo");
      $("#academy-logo").src = logoUrl;
      $("#academy-logo").hidden = false;
    } catch { $("#academy-logo").hidden = true; }
  } else $("#academy-logo").hidden = true;
  $("#key-dialog").hidden = true;
  clearEvent();
  if (pollTimer) clearTimeout(pollTimer);
  pollEvents();
}

$("#key-form").addEventListener("submit", async (event) => {
  event.preventDefault();
  const button = $("#connect-button");
  button.disabled = true;
  $("#key-error").hidden = true;
  try { await connect($("#monitor-key").value.trim()); }
  catch {
    $("#key-error").textContent = tr("wrongKey");
    $("#key-error").hidden = false;
  } finally { button.disabled = false; }
});

$("#sound-button").addEventListener("click", async () => {
  try {
    const AudioContextClass = window.AudioContext || window.webkitAudioContext;
    if (!AudioContextClass) throw new Error("audio");
    soundContext ||= new AudioContextClass();
    await soundContext.resume();
    soundEnabled = true;
    $("#sound-button").setAttribute("aria-pressed", "true");
    $("#sound-button").textContent = tr("soundOn");
    playTone(true);
  } catch {
    $("#screen-error").textContent = tr("networkError");
    $("#screen-error").hidden = false;
  }
});

$("#monitor-language").addEventListener("change", (event) => {
  language = event.target.value;
  localStorage.setItem(languageStorage, language);
  applyLanguage();
});

applyLanguage();
if (monitorKey) {
  connect(monitorKey).catch(() => {
    sessionStorage.removeItem(keyStorage);
    monitorKey = "";
    $("#key-dialog").hidden = false;
    setConnection(false);
  });
}

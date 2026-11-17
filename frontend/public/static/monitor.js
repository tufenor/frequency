// Modo de teste: simula internet indisponível sem desligar a rede do computador.
// Ative com ?teste_offline=1 e desative com ?teste_offline=0.
const offlineTestStorageKey = "frequency.test_offline";
const offlineTestParam = new URLSearchParams(window.location.search).get("teste_offline");
if (offlineTestParam === "1") localStorage.setItem(offlineTestStorageKey, "1");
if (offlineTestParam === "0") localStorage.removeItem(offlineTestStorageKey);
const offlineTestMode = localStorage.getItem(offlineTestStorageKey) === "1";

const $ = (selector) => document.querySelector(selector);
const keyStorage = "frequency.monitor_key";
const sessionStorageKey = "frequency.monitor_session";
const languageStorage = "frequency.monitor_language";
// Keep the connection inside this browser tab. This lets a camera permission
// reload recover the monitor without sharing the code with another screen.
let monitorKey = sessionStorage.getItem(keyStorage) || "";
// Cada aba/janela é uma tela independente. "Duplicar aba" e "Nova tela" copiam o
// sessionStorage; só um recarregamento (F5 ou permissão da câmera) reaproveita a
// sessão e a câmera escolhida. Assim duas janelas nunca dividem eventos.
const navigationType = performance.getEntriesByType?.("navigation")?.[0]?.type;
const isReload = navigationType === "reload";
const newSessionId = () => window.crypto?.randomUUID?.() || `${Date.now()}-${Math.random()}`;
let monitorSession = (isReload && sessionStorage.getItem(sessionStorageKey)) || newSessionId();
sessionStorage.setItem(sessionStorageKey, monitorSession);
const cameraStorage = "frequency.monitor_camera";
const cameraClaimsStorage = "frequency.monitor_camera_claims";
function readSavedCamera() {
  try { return JSON.parse(sessionStorage.getItem(cameraStorage) || "{}") || {}; } catch { return {}; }
}
const savedCamera = isReload ? readSavedCamera() : {};
let selectedCameraId = savedCamera.id || "";
let selectedCameraLabel = savedCamera.label || "";
let cameraDevices = [];
let claimTimer = null;
let language = localStorage.getItem(languageStorage) ||
  (navigator.language?.toLowerCase().startsWith("es") ? "es-BO" : "pt-BR");
let lastEventId = 0;
let pollTimer = null;
let clearTimer = null;
let soundContext = null;
let soundEnabled = true;
let connectionActive = false;
let logoUrl = null;
let photoUrl = null;
let faceStream = null;
let faceTimer = null;
let faceBusy = false;
let faceStarting = false;

function monitorHeaders(extra = {}) {
  return { ...extra, "X-Monitor-Key": monitorKey, "X-Monitor-Session": monitorSession };
}

const text = {
  "pt-BR": {
    cameraLabel: "Câmera", cameraN: (n) => `Câmera ${n}`, newScreen: "Nova tela", cameraBusy: "Esta câmera está em uso por outro programa. Escolha outra câmera.", cameraGone: "A câmera escolhida foi desconectada. Escolha outra câmera.",
    title: "Tela de entrada", greeting: "BEM-VINDO À", kicker: "FREQUENCY · ACESSO",
    idleTitle: "Posicione seu rosto", idleMessage: "A câmera mostrará o resultado da sua entrada aqui.",
    hint: "Sua informação aparece por alguns segundos e depois é removida.", signature: "Acesso protegido por",
    activate: "Ativar som", soundOn: "Som ativo", camera: "Ativar câmera", cameraOn: "Câmera ativa", online: "Monitor conectado", waiting: "Aguardando conexão",
    granted: "Entrada liberada", hello: (name) => `Olá, ${name}`, overdue: "Há uma pendência na mensalidade. Procure a recepção.",
    denied: "Acesso não liberado. Procure a recepção.", unknown: "Cadastro não encontrado", language: "Idioma", keyOverline: "TELA DA ACADEMIA",
    connect: "Conectar esta tela", keyInfo: "Cole o código criado pelo dono da academia. Este código só mostra resultados de novas entradas.",
    keyLabel: "Código de conexão", connectButton: "Conectar monitor", wrongKey: "Código inválido. Confira com o dono da academia.",
    networkError: "Sem conexão com o sistema. Verifique a rede.", limit: "O limite de telas do seu plano foi atingido.", time: (date) => new Intl.DateTimeFormat(language, { hour: "2-digit", minute: "2-digit" }).format(new Date(date)),
  },
  "es-BO": {
    cameraLabel: "Cámara", cameraN: (n) => `Cámara ${n}`, newScreen: "Nueva pantalla", cameraBusy: "Esta cámara está en uso por otro programa. Elige otra cámara.", cameraGone: "La cámara elegida se desconectó. Elige otra cámara.",
    title: "Pantalla de acceso", greeting: "TE DAMOS LA BIENVENIDA A", kicker: "FREQUENCY · ACCESO",
    idleTitle: "Acerca tu huella", idleMessage: "El torniquete mostrará aquí el resultado de tu acceso.",
    hint: "Tu información aparecerá unos segundos y luego se borrará.", signature: "Acceso protegido por",
    activate: "Activar sonido", soundOn: "Sonido activo", camera: "Activar cámara", cameraOn: "Cámara activa", online: "Monitor conectado", waiting: "Esperando conexión",
    granted: "Acceso autorizado", hello: (name) => `Hola, ${name}`, overdue: "Hay una mensualidad pendiente. Acércate a recepción.",
    denied: "Acceso no autorizado. Acércate a recepción.", unknown: "No encontramos tu registro", language: "Idioma", keyOverline: "PANTALLA DEL GIMNASIO",
    connect: "Conectar esta pantalla", keyInfo: "Pega el código creado por el propietario. Este código solo muestra resultados de nuevos accesos.",
    keyLabel: "Código de conexión", connectButton: "Conectar monitor", wrongKey: "Código inválido. Consulta al propietario del gimnasio.",
    networkError: "Sin conexión con el sistema. Revisa la red.", limit: "Se alcanzó el límite de pantallas de tu plan.", time: (date) => new Intl.DateTimeFormat(language, { hour: "2-digit", minute: "2-digit" }).format(new Date(date)),
  },
  en: {
    cameraLabel: "Camera", cameraN: (n) => `Camera ${n}`, newScreen: "New screen", cameraBusy: "This camera is being used by another program. Choose another camera.", cameraGone: "The selected camera was disconnected. Choose another camera.",
    title: "Entry screen", greeting: "WELCOME TO", kicker: "FREQUENCY · ENTRY",
    idleTitle: "Scan your fingerprint", idleMessage: "The turnstile will show your entry result here.",
    hint: "Your information appears for a few seconds, then clears.", signature: "Access protected by",
    activate: "Enable sound", soundOn: "Sound on", camera: "Enable camera", cameraOn: "Camera on", online: "Monitor connected", waiting: "Waiting for connection",
    granted: "Entry approved", hello: (name) => `Hello, ${name}`, overdue: "There is an outstanding membership payment. Please see reception.",
    denied: "Entry not approved. Please see reception.", unknown: "We couldn't find your record", language: "Language", keyOverline: "GYM SCREEN",
    connect: "Connect this screen", keyInfo: "Paste the code created by the gym owner. This code only shows results for new entries.",
    keyLabel: "Connection code", connectButton: "Connect monitor", wrongKey: "Invalid code. Please check with the gym owner.",
    networkError: "No connection to the system. Check the network.", limit: "Your plan's screen limit has been reached.", time: (date) => new Intl.DateTimeFormat(language, { hour: "2-digit", minute: "2-digit" }).format(new Date(date)),
  },
  "zh-CN": {
    cameraLabel: "摄像头", cameraN: (n) => `摄像头 ${n}`, newScreen: "新屏幕", cameraBusy: "此摄像头正被其他程序使用。请选择其他摄像头。", cameraGone: "所选摄像头已断开。请选择其他摄像头。",
    title: "入场屏幕", greeting: "欢迎来到", kicker: "FREQUENCY · 入场",
    idleTitle: "请扫描指纹", idleMessage: "闸机将在这里显示您的入场结果。", hint: "您的信息显示几秒后将自动清除。",
    signature: "入场系统由", activate: "开启声音", soundOn: "声音已开启", camera: "开启摄像头", cameraOn: "摄像头已开启", online: "屏幕已连接", waiting: "等待连接",
    granted: "允许入场", hello: (name) => `您好，${name}`, overdue: "会员费用尚未结清，请联系前台。", denied: "未获准入场，请联系前台。",
    unknown: "未找到您的记录", language: "语言", keyOverline: "健身房屏幕", connect: "连接此屏幕", keyInfo: "请输入健身房负责人创建的代码。此代码仅显示新的入场结果。",
    keyLabel: "连接代码", connectButton: "连接屏幕", wrongKey: "代码无效，请联系健身房负责人。", networkError: "系统连接中断，请检查网络。",
    limit: "已达到套餐屏幕数量上限。", time: (date) => new Intl.DateTimeFormat(language, { hour: "2-digit", minute: "2-digit" }).format(new Date(date)),
  },
  "hi-IN": {
    cameraLabel: "कैमरा", cameraN: (n) => `कैमरा ${n}`, newScreen: "नई स्क्रीन", cameraBusy: "यह कैमरा किसी अन्य प्रोग्राम में उपयोग हो रहा है। दूसरा कैमरा चुनें।", cameraGone: "चुना गया कैमरा डिस्कनेक्ट हो गया। दूसरा कैमरा चुनें।",
    title: "प्रवेश स्क्रीन", greeting: "आपका स्वागत है", kicker: "FREQUENCY · प्रवेश",
    idleTitle: "अपनी उंगली स्कैन करें", idleMessage: "टर्नस्टाइल यहाँ आपके प्रवेश का परिणाम दिखाएगा।",
    hint: "आपकी जानकारी कुछ सेकंड दिखेगी और फिर हट जाएगी।", signature: "सुरक्षित प्रवेश",
    activate: "आवाज़ चालू करें", soundOn: "आवाज़ चालू", camera: "कैमरा चालू करें", cameraOn: "कैमरा चालू है", online: "मॉनिटर जुड़ा है", waiting: "कनेक्शन की प्रतीक्षा",
    granted: "प्रवेश की अनुमति है", hello: (name) => `नमस्ते, ${name}`, overdue: "सदस्यता भुगतान बाकी है। कृपया रिसेप्शन से संपर्क करें।",
    denied: "प्रवेश की अनुमति नहीं है। रिसेप्शन से संपर्क करें।", unknown: "आपका रिकॉर्ड नहीं मिला", language: "भाषा", keyOverline: "जिम स्क्रीन",
    connect: "इस स्क्रीन को जोड़ें", keyInfo: "जिम मालिक द्वारा बनाया गया कोड दर्ज करें। यह कोड केवल नई प्रविष्टियों का परिणाम दिखाता है।",
    keyLabel: "कनेक्शन कोड", connectButton: "मॉनिटर जोड़ें", wrongKey: "कोड गलत है। जिम मालिक से संपर्क करें।", networkError: "सिस्टम से कनेक्शन नहीं है। नेटवर्क जांचें।",
    limit: "आपकी योजना की स्क्रीन सीमा पूरी हो गई है।", time: (date) => new Intl.DateTimeFormat(language, { hour: "2-digit", minute: "2-digit" }).format(new Date(date)),
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
  $("#sound-button").setAttribute("aria-pressed", String(soundEnabled));
  $("#camera-button").textContent = faceStream ? tr("cameraOn") : tr("camera");
  $("#connection-label").textContent = connectionActive ? tr("online") : tr("waiting");
  $("#language-label").textContent = tr("language");
  $("#camera-choice-label").textContent = tr("cameraLabel");
  $("#new-screen-button").textContent = tr("newScreen");
  renderCameraOptions();
  $("#key-overline").textContent = tr("keyOverline");
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
    ["digital_nao_cadastrada", "rosto_nao_identificado"].includes(currentEvent.motivo) ? tr("unknown") : tr("denied");
  $("#access-message").textContent = currentEvent.liberado ? tr("hello")(currentEvent.nome) :
    overdue ? tr("overdue") : tr("denied");
}

function setConnection(isConnected) {
  connectionActive = offlineTestMode ? false : isConnected;
  $(".connection-indicator").classList.toggle("online", isConnected);
  $("#connection-label").textContent = isConnected ? tr("online") : tr("waiting");
  if (!isConnected) {
    $("#screen-error").textContent = tr("networkError");
    $("#screen-error").hidden = false;
  } else $("#screen-error").hidden = true;
}

function clearEvent() {
  currentEvent = null;
  $("#access-card").className = `access-card idle${faceStream ? " camera-active" : ""}`;
  $("#access-title").textContent = tr("idleTitle");
  $("#access-message").textContent = tr("idleMessage");
  $("#student-photo").hidden = true;
  $("#photo-fallback").hidden = false;
  $("#access-time").hidden = true;
  if (photoUrl) URL.revokeObjectURL(photoUrl);
  photoUrl = null;
}

function stopFaceCamera() {
  if (faceTimer) clearTimeout(faceTimer);
  faceTimer = null;
  faceStream?.getTracks().forEach((track) => track.stop());
  faceStream = null;
  releaseCameraClaim();
  $("#face-camera").srcObject = null;
  $("#face-camera-wrap").hidden = true;
  $("#access-card").classList.remove("camera-active");
  $("#camera-button").setAttribute("aria-pressed", "false");
  $("#camera-button").textContent = tr("camera");
}

async function recognizeFrame() {
  // Não pausa quando a janela perde o foco: com várias telas no mesmo computador,
  // cada janela continua reconhecendo pela própria câmera.
  if (!faceStream || faceBusy) return scheduleFaceFrame(1200);
  if (!monitorKey) {
    $("#face-camera-status").textContent = "Conecte o monitor para reconhecer.";
    return scheduleFaceFrame(2000);
  }
  const video = $("#face-camera");
  if (!video.videoWidth) return scheduleFaceFrame(500);
  faceBusy = true;
  try {
    const canvas = $("#face-canvas");
    const scale = Math.min(1, 640 / video.videoWidth);
    canvas.width = Math.round(video.videoWidth * scale);
    canvas.height = Math.round(video.videoHeight * scale);
    canvas.getContext("2d", { alpha: false }).drawImage(video, 0, 0, canvas.width, canvas.height);
    const blob = await new Promise((resolve) => canvas.toBlob(resolve, "image/jpeg", 0.8));
    if (!blob) throw new Error("capture");
    const encoded = await new Promise((resolve, reject) => {
      const file = new FileReader();
      file.onerror = reject;
      file.onload = () => resolve(String(file.result).split(",", 2)[1]);
      file.readAsDataURL(blob);
    });
    const response = await fetch("/acesso/facial", {
      method: "POST",
      headers: monitorHeaders({ "Content-Type": "application/json", Accept: "application/json" }),
      body: JSON.stringify({ foto_base64: encoded }),
      cache: "no-store",
    });
    const result = await response.json().catch(() => ({}));
    if (response.status === 401) {
      $("#face-camera-status").textContent = "Reconecte esta tela para reconhecer.";
    } else if (response.status === 422) {
      const prompts = {
        rosto_nao_detectado: "Posicione o rosto no centro.", rosto_multiplos_detectados: "Apenas uma pessoa por vez.",
        rosto_muito_distante: "Aproxime um pouco o rosto.", rosto_fora_do_quadro: "Centralize o rosto.",
        rosto_iluminacao_inadequada: "Melhore a iluminação.", rosto_imagem_desfocada: "Fique parado por um instante.",
      };
      $("#face-camera-status").textContent = prompts[result.detail] || "Ajuste o rosto e tente novamente.";
    } else if (!response.ok) {
      $("#face-camera-status").textContent = "Reconhecimento indisponível. Confira o Frequency.";
    } else {
      $("#face-camera-status").textContent = result.identificado ? "Rosto identificado." : "Rosto ainda não cadastrado.";
    }
  } catch {
    $("#face-camera-status").textContent = "Sem conexão para reconhecer. Tentando novamente.";
  } finally {
    faceBusy = false;
    scheduleFaceFrame(1600);
  }
}

function scheduleFaceFrame(delay) {
  if (faceTimer) clearTimeout(faceTimer);
  if (faceStream) faceTimer = setTimeout(recognizeFrame, delay);
}

function readCameraClaims() {
  try { return JSON.parse(localStorage.getItem(cameraClaimsStorage) || "{}") || {}; } catch { return {}; }
}

function writeCameraClaims(claims) {
  try { localStorage.setItem(cameraClaimsStorage, JSON.stringify(claims)); } catch { /* opcional */ }
}

// Registro local (somente neste computador) de qual câmera cada tela está usando,
// para que uma nova janela escolha sozinha uma webcam livre. Nada é mostrado na tela.
// Alguns navegadores dão um ID diferente para a mesma webcam em cada janela;
// por isso a câmera também é reconhecida pelo nome quando o nome é único.
function cameraClaimedByOtherScreen(deviceId) {
  const device = cameraDevices.find((item) => item.deviceId === deviceId);
  const label = device?.label || "";
  const uniqueLabel = label && cameraDevices.filter((item) => item.label === label).length === 1;
  return Object.entries(readCameraClaims()).some(([id, claim]) =>
    claim.session !== monitorSession && Date.now() - claim.at < 15000 &&
    (id === deviceId || (uniqueLabel && claim.label === label)));
}

function claimCamera(deviceId) {
  const claims = readCameraClaims();
  for (const [id, claim] of Object.entries(claims)) {
    if (claim.session === monitorSession || Date.now() - claim.at >= 15000) delete claims[id];
  }
  const label = cameraDevices.find((item) => item.deviceId === deviceId)?.label || "";
  if (deviceId) claims[deviceId] = { session: monitorSession, at: Date.now(), label };
  writeCameraClaims(claims);
  if (claimTimer) clearInterval(claimTimer);
  claimTimer = deviceId ? setInterval(() => claimCamera(deviceId), 5000) : null;
}

function releaseCameraClaim() {
  if (claimTimer) clearInterval(claimTimer);
  claimTimer = null;
  const claims = readCameraClaims();
  for (const [id, claim] of Object.entries(claims)) if (claim.session === monitorSession) delete claims[id];
  writeCameraClaims(claims);
}

async function listCameras() {
  if (!navigator.mediaDevices?.enumerateDevices) return [];
  try {
    const devices = await navigator.mediaDevices.enumerateDevices();
    return devices.filter((device) => device.kind === "videoinput" && device.deviceId);
  } catch { return []; }
}

function renderCameraOptions() {
  const select = $("#camera-choice");
  if (!select) return;
  select.replaceChildren(...cameraDevices.map((device, index) => {
    const option = document.createElement("option");
    option.value = device.deviceId;
    option.textContent = device.label || tr("cameraN")(index + 1);
    return option;
  }));
  if (selectedCameraId) select.value = selectedCameraId;
  $("#camera-choice-wrap").hidden = cameraDevices.length < 1;
}

function saveSelectedCamera() {
  selectedCameraLabel = cameraDevices.find((item) => item.deviceId === selectedCameraId)?.label || selectedCameraLabel;
  sessionStorage.setItem(cameraStorage, JSON.stringify({ id: selectedCameraId, label: selectedCameraLabel }));
}

function preferredCamera() {
  if (selectedCameraId && cameraDevices.some((device) => device.deviceId === selectedCameraId)) return selectedCameraId;
  const sameName = selectedCameraLabel && cameraDevices.filter((device) => device.label === selectedCameraLabel);
  if (sameName?.length === 1) return sameName[0].deviceId;
  const free = cameraDevices.find((device) => !cameraClaimedByOtherScreen(device.deviceId));
  return (free || cameraDevices[0])?.deviceId || "";
}

async function openCameraStream(deviceId) {
  const size = { width: { ideal: 1280 }, height: { ideal: 720 } };
  const video = deviceId ? { deviceId: { exact: deviceId }, ...size } : { facingMode: "user", ...size };
  try {
    return await navigator.mediaDevices.getUserMedia({ video, audio: false });
  } catch (error) {
    if (error?.name === "OverconstrainedError" && !deviceId) {
      return navigator.mediaDevices.getUserMedia({ video: true, audio: false });
    }
    if (error?.name === "NotReadableError" || /start video source/i.test(error?.message || "")) {
      await new Promise((resolve) => setTimeout(resolve, 700));
      try { return await navigator.mediaDevices.getUserMedia({ video: deviceId ? { deviceId: { exact: deviceId } } : true, audio: false }); }
      catch { throw new Error(tr("cameraBusy")); }
    }
    if (error?.name === "OverconstrainedError" || error?.name === "NotFoundError") {
      if (deviceId) throw new Error(tr("cameraGone"));
      throw new Error("Nenhuma webcam foi encontrada neste computador.");
    }
    if (error?.name === "NotAllowedError") throw new Error("Permita o uso da câmera nas configurações do navegador e tente novamente.");
    throw error;
  }
}

async function startFaceCamera() {
  if (!window.isSecureContext || !navigator.mediaDevices?.getUserMedia) {
    $("#face-camera-wrap").hidden = false;
    $("#access-card").classList.add("camera-active");
    $("#face-camera-status").textContent = "O navegador só libera a webcam em HTTPS com certificado confiável. Abra o Frequency pelo endereço HTTPS configurado para esta rede.";
    throw new Error("Esta conexão usa HTTP. Configure HTTPS confiável para usar a webcam pela rede.");
  }
  if (faceStream || faceStarting) return;
  faceStarting = true;
  try {
    cameraDevices = await listCameras();
    let stream = await openCameraStream(preferredCamera());
    // Antes da permissão o navegador pode esconder a lista; depois dela,
    // troca para uma webcam livre se a padrão já estiver em outra tela.
    cameraDevices = await listCameras();
    const openedId = stream.getVideoTracks()[0]?.getSettings?.().deviceId || "";
    const wanted = preferredCamera();
    if (!selectedCameraId && !selectedCameraLabel && wanted && openedId && wanted !== openedId && cameraClaimedByOtherScreen(openedId)) {
      stream.getTracks().forEach((track) => track.stop());
      stream = await openCameraStream(wanted);
    }
    faceStream = stream;
    selectedCameraId = faceStream.getVideoTracks()[0]?.getSettings?.().deviceId || wanted || selectedCameraId;
    saveSelectedCamera();
    claimCamera(selectedCameraId);
    renderCameraOptions();
  } finally {
    faceStarting = false;
  }
  const video = $("#face-camera");
  video.srcObject = faceStream;
  faceStream.getVideoTracks()[0]?.addEventListener("ended", () => {
    stopFaceCamera();
    $("#screen-error").textContent = tr("cameraGone");
    $("#screen-error").hidden = false;
  });
  $("#face-camera-wrap").hidden = false;
  $("#access-card").classList.add("camera-active");
  $("#camera-button").setAttribute("aria-pressed", "true");
  $("#camera-button").textContent = tr("cameraOn");
  await video.play();
  $("#face-camera-status").textContent = "Posicione o rosto no centro.";
  scheduleFaceFrame(600);
}

function playTone(allowed) {
  if (!soundEnabled || !soundContext) return;
  const notes = allowed
    ? [{ hz: 740, start: 0, length: 0.13 }, { hz: 988, start: 0.17, length: 0.2 }]
    : [{ hz: 320, start: 0, length: 0.24 }, { hz: 220, start: 0.28, length: 0.31 }];
  const peakVolume = allowed ? 0.16 : 0.34;
  for (const note of notes) {
    const oscillator = soundContext.createOscillator();
    const gain = soundContext.createGain();
    oscillator.type = allowed ? "sine" : "triangle";
    oscillator.frequency.value = note.hz;
    gain.gain.setValueAtTime(0.0001, soundContext.currentTime + note.start);
    gain.gain.exponentialRampToValueAtTime(peakVolume, soundContext.currentTime + note.start + 0.018);
    gain.gain.exponentialRampToValueAtTime(0.0001, soundContext.currentTime + note.start + note.length);
    oscillator.connect(gain);
    gain.connect(soundContext.destination);
    oscillator.start(soundContext.currentTime + note.start);
    oscillator.stop(soundContext.currentTime + note.start + note.length + 0.02);
  }
}

function prepareSoundContext() {
  const AudioContextClass = window.AudioContext || window.webkitAudioContext;
  if (!AudioContextClass) return;
  soundContext ||= new AudioContextClass();
  if (soundContext.state === "suspended") void soundContext.resume().catch(() => {});
}

async function fetchProtectedImage(path) {
  const response = await fetch(path, {
    headers: monitorHeaders(), cache: "no-store",
  });
  if (!response.ok) throw new Error("image");
  return URL.createObjectURL(await response.blob());
}

async function showEvent(event) {
  currentEvent = event;
  $("#access-card").className = `access-card ${event.liberado ? "allowed" : "denied"}${faceStream ? " camera-active" : ""}`;
  $("#access-kicker").textContent = tr("kicker");
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
      headers: monitorHeaders({ Accept: "application/json" }), cache: "no-store",
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
  let response;
  try {
    // Normaliza o codigo para permitir espacos, tracos e minusculas.
    monitorKey = String(key || "").replace(/[\s-]+/g, "").toUpperCase();
    if (!monitorKey) throw new Error("key");
    sessionStorage.setItem(keyStorage, monitorKey);
    response = await fetch("/monitor/estado", {
      headers: monitorHeaders({ Accept: "application/json" }), cache: "no-store",
    });
  } catch (error) {
    if (error?.message === "key") throw error;
    throw new Error("network");
  }
  if (response.status === 401) throw new Error("key");
  if (response.status === 403) {
    const detail = (await response.json().catch(() => ({}))).detail;
    if (detail === "limite_de_monitores_do_plano_atingido") throw new Error("limit");
    throw new Error("network");
  }
  if (!response.ok) throw new Error("network");
  const status = await response.json();
  // The shared code remains active until the owner explicitly replaces it.
  lastEventId = status.ultimo_evento;
  $("#academy-name").textContent = status.academia;
  $("#monitor-label").textContent = `${status.monitor_nome || "Monitor"} · ${status.monitor_numero || "1"}`;
  $("#monitor-label").hidden = false;
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
  startFaceCamera().catch((error) => {
    $("#screen-error").textContent = error.message;
    $("#screen-error").hidden = false;
  });
}

$("#key-form").addEventListener("submit", async (event) => {
  event.preventDefault();
  const button = $("#connect-button");
  button.disabled = true;
  $("#key-error").hidden = true;
  try {
    await connect($("#monitor-key").value.trim());
  }
  catch (error) {
    $("#key-error").textContent = error.message === "key" ? tr("wrongKey") : error.message === "limit" ? tr("limit") : tr("networkError");
    $("#key-error").hidden = false;
  } finally { button.disabled = false; }
});

$("#sound-button").addEventListener("click", async () => {
  try {
    prepareSoundContext();
    if (!soundContext) throw new Error("audio");
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

$("#camera-button").addEventListener("click", async () => {
  if (faceStream) {
    $("#face-camera-status").textContent = "A câmera já está ativa e procurando rostos.";
    return;
  }
  try { await startFaceCamera(); }
  catch (error) { $("#screen-error").textContent = error.message; $("#screen-error").hidden = false; }
});

$("#camera-choice")?.addEventListener("change", async (event) => {
  selectedCameraId = event.target.value;
  selectedCameraLabel = "";
  saveSelectedCamera();
  stopFaceCamera();
  $("#screen-error").hidden = true;
  try { await startFaceCamera(); }
  catch (error) { $("#screen-error").textContent = error.message; $("#screen-error").hidden = false; }
});

// Abre outra tela independente (outra janela, outra sessão, outra câmera).
$("#new-screen-button")?.addEventListener("click", () => {
  window.open("/monitor", "_blank", "popup,width=1100,height=760");
});

navigator.mediaDevices?.addEventListener?.("devicechange", async () => {
  cameraDevices = await listCameras();
  renderCameraOptions();
});

function closeMonitorSession() {
  if (monitorKey) {
    // This request remains alive while the window closes, freeing the slot now.
    void fetch("/monitor/sessao", { method: "DELETE", headers: monitorHeaders(), keepalive: true }).catch(() => {});
  }
  stopFaceCamera();
}

window.addEventListener("pagehide", closeMonitorSession);

$("#monitor-language").addEventListener("change", (event) => {
  language = event.target.value;
  localStorage.setItem(languageStorage, language);
  applyLanguage();
});

applyLanguage();
prepareSoundContext();
// A reload caused by changing the webcam keeps this tab connected. A new tab
// still starts empty because sessionStorage is isolated per browser tab.
const savedMonitorKey = sessionStorage.getItem(keyStorage);
if (savedMonitorKey) {
  connect(savedMonitorKey).catch((error) => {
    $("#key-error").textContent = error.message === "key" ? tr("wrongKey") : error.message === "limit" ? tr("limit") : tr("networkError");
    $("#key-error").hidden = false;
  });
}

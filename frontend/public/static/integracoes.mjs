import { cameraUrl, youtubePlaylistId, youtubeVideoId } from "./integracoes-core.mjs?v=2";
const $ = (selector) => document.querySelector(selector);
const jwtKey = "frequency.access_token";
const feature = document.body.dataset.feature;
let owner, cameraKey, youtubeKey, youtubeQueueKey, cameras = [], youtubeQueue = [], youtubeQueueIndex = -1, busy = false, youtubePlayer = null, youtubeApiPromise = null, youtubeFallbackTried = false, youtubeAdvanceTimer = null, youtubeAdvanceTriggered = false, youtubeSkipTriggered = false, youtubePlaybackStarted = false;
const streams = new Set();
let interfaceLocale = window.FrequencyI18n?.initialLocale?.() || "pt-BR";
const YOUTUBE_PLAYER_ORIGIN = "https://www.youtube-nocookie.com";
const tr = (value) => window.FrequencyI18n?.translate(interfaceLocale, value) || value;
const queryLocale = new URLSearchParams(location.search).get("locale");
function applyLocale(locale) {
  interfaceLocale = locale || interfaceLocale;
  document.documentElement.lang = interfaceLocale;
  window.FrequencyI18n?.renderStatic(tr);
  const selector = $("#integration-language"); if (selector) selector.value = interfaceLocale;
}
window.FrequencyI18n?.captureStatic();
applyLocale(interfaceLocale);
$("#integration-language")?.addEventListener("change", (event) => {
  interfaceLocale = event.target.value;
  window.FrequencyI18n?.saveLocale(interfaceLocale, owner);
  applyLocale(interfaceLocale);
});
window.addEventListener("message", (event) => {
  if (event.origin !== location.origin || event.data?.type !== "frequency-locale") return;
  const locale = event.data.locale;
  if (["pt-BR", "es-BO", "en-US", "zh-CN", "hi-IN"].includes(locale)) applyLocale(locale);
});

function read(storage, key, fallback = null) { try { return JSON.parse(storage.getItem(key)) ?? fallback; } catch { return fallback; } }
function notice(message = "", error = false) {
  const status = $("#integration-status");
  status.textContent = message;
  status.hidden = !message;
  status.classList.toggle("integration-error", error);
  status.classList.toggle("integration-success", Boolean(message) && !error);
}
function stopStreams() { for (const stop of [...streams]) stop(); }
function lock() { stopStreams(); $("#integration-content").hidden = true; }
async function authorize() {
  const token = sessionStorage.getItem(jwtKey);
  if (!token) { lock(); throw new Error(tr("Entre no Frequency com a conta do dono para continuar.")); }
  const response = await fetch("/eu", { headers: { Authorization: `Bearer ${token}` }, cache: "no-store", signal: AbortSignal.timeout(10000) });
  if (!response.ok) { lock(); throw new Error(tr("Sua sessão não está disponível. Entre novamente no Frequency.")); }
  const user = await response.json();
  const identity = `${user.academia_id}:${user.id}`;
  if (user.papel !== "dono" || !user.academia_id || user.bloqueada_frequency || (owner && owner !== identity)) { lock(); throw new Error(tr("Esta área exige a conta ativa do dono da academia.")); }
  const access = await fetch(`/academia/integracoes/${feature}`, { headers: { Authorization: `Bearer ${token}` }, cache: "no-store", signal: AbortSignal.timeout(10000) });
  if (!access.ok) { lock(); throw new Error(tr("Esta opção precisa estar incluída no pacote Premium ativo.")); }
  return identity;
}
async function action(work) {
  if (busy) return;
  busy = true;
  try { await authorize(); await work(); } catch (error) { notice(error instanceof TypeError ? tr("Falha de conexão. Confira a rede e tente novamente.") : error.message, true); }
  finally { busy = false; }
}
async function searchYoutube(query) {
  const termo = String(query || "").trim();
  if (termo.length < 2) throw new Error(tr("Digite pelo menos duas letras para pesquisar."));
  const token = sessionStorage.getItem(jwtKey);
  const response = await fetch(`/academia/integracoes/youtube/search?q=${encodeURIComponent(termo)}`, {
    headers: { Authorization: `Bearer ${token}` }, cache: "no-store", signal: AbortSignal.timeout(12000),
  });
  if (!response.ok) throw new Error(response.status === 502 ? tr("O YouTube não respondeu. Tente novamente.") : tr("Não foi possível pesquisar no YouTube."));
  const data = await response.json();
  const results = $("#youtube-results");
  results.replaceChildren();
  if (!data.resultados?.length) {
    results.append(node("p", tr("Nenhum vídeo encontrado para essa pesquisa.")));
  } else {
    data.resultados.forEach((item) => {
      const card = node("article"); card.className = "youtube-result-card";
      const image = node("img"); image.src = item.miniatura; image.alt = ""; image.loading = "lazy";
      const body = node("div"); body.className = "youtube-result-body";
      const title = node("h3", item.titulo);
      const use = button(tr("Usar vídeo"), () => action(async () => {
        await checkYoutubeVideo(item.id);
        enqueueYoutube(item.id, item.titulo, { play: false });
        youtubeQueueIndex = youtubeQueue.findIndex((entry) => entry.id === item.id);
        await loadYoutube(item.id);
      }));
      const add = button(tr("Adicionar à playlist"), () => action(async () => {
        await checkYoutubeVideo(item.id);
        enqueueYoutube(item.id, item.titulo, { play: false });
        notice(tr("Vídeo adicionado à playlist."));
      }));
      body.append(title, use, add); card.append(image, body); results.append(card);
    });
  }
  $("#youtube-results-wrap").hidden = false;
  notice(`${data.resultados?.length || 0} ${tr("resultado(s) encontrado(s).")}`);
}
async function checkYoutubeVideo(id) {
  const token = sessionStorage.getItem(jwtKey);
  const response = await fetch(`/academia/integracoes/youtube/check?video_id=${encodeURIComponent(id)}`, {
    headers: { Authorization: `Bearer ${token}` }, cache: "no-store", signal: AbortSignal.timeout(7000),
  });
  if (!response.ok) throw new Error(tr("Não foi possível validar este vídeo. Tente outro resultado."));
  const data = await response.json();
  if (!data.disponivel) throw new Error(tr("Este vídeo não está disponível no YouTube. Escolha outro resultado."));
}
function node(tag, text) { const result = document.createElement(tag); if (text) result.textContent = text; return result; }
function button(text, work) { const element = node("button", text); element.type = "button"; element.className = "button button-secondary"; element.addEventListener("click", work); return element; }
function saveYoutubeQueue() { localStorage.setItem(youtubeQueueKey, JSON.stringify(youtubeQueue)); renderYoutubeQueue(); }
function youtubeTitleKey(value) {
  return String(value || "").toLocaleLowerCase()
    .replace(/\b(official|video|audio|lyrics?|visualizer|remix|live|version|vers[aã]o)\b/giu, " ")
    .replace(/[^\p{L}\p{N}]+/gu, " ").replace(/\s+/g, " ").trim();
}
function youtubeSameTrackFamily(left, right) {
  const first = youtubeTitleKey(left); const second = youtubeTitleKey(right);
  return Boolean(first && second && (first === second || first.includes(second) || second.includes(first)));
}
function renderYoutubeQueue() {
  const list = $("#youtube-queue-list"); if (!list) return;
  list.replaceChildren();
  youtubeQueue.forEach((item, index) => { const row = node("div", `${index + 1}. ${item.title || item.id}`); row.className = `youtube-queue-item${index === youtubeQueueIndex ? " is-playing" : ""}`; list.append(row); });
  if (!youtubeQueue.length) list.append(node("p", tr("A fila está vazia.")));
}
async function suggestYoutubeQueue(selectedId, title) {
  const baseTitle = String(title || "").replace(/[|()[\]{}]/g, " ").replace(/\s+/g, " ").trim().slice(0, 72);
  if (baseTitle.length < 2) return;
  const token = sessionStorage.getItem(jwtKey);
  try {
    // Duas buscas com intenção diferente evitam que o primeiro resultado seja
    // apenas outra versão da música atual (live, lyric video ou remix).
    const queries = [`${baseTitle} songs like`, `${baseTitle} workout mix`];
    const responses = await Promise.all(queries.map((query) => fetch(
      `/academia/integracoes/youtube/search?q=${encodeURIComponent(query)}`,
      { headers: { Authorization: `Bearer ${token}` }, cache: "no-store", signal: AbortSignal.timeout(12000) },
    ).then((response) => response.ok ? response.json() : null).catch(() => null)));
    const existing = new Set(youtubeQueue.map((item) => item.id));
    const suggestions = responses.flatMap((data) => data?.resultados || [])
      .filter((item) => item.id !== selectedId && !existing.has(item.id) && !youtubeSameTrackFamily(item.titulo, title))
      .filter((item, index, all) => all.findIndex((other) => other.id === item.id) === index)
      .slice(0, 4);
    suggestions.forEach((item) => enqueueYoutube(item.id, item.titulo));
    if (suggestions.length) notice(`${suggestions.length} ${tr("sugestões adicionadas à playlist")}.`);
  } catch { /* A música escolhida continua disponível mesmo sem sugestões. */ }
}

function enqueueYoutube(id, title = "", options = {}) {
  const existing = youtubeQueue.findIndex((item) => item.id === id || youtubeSameTrackFamily(item.title, title));
  if (existing >= 0) { if (options.play) { youtubeQueueIndex = existing; loadYoutube(id); } else renderYoutubeQueue(); return; }
  youtubeQueue.push({ id, title: title || id });
  if (options.play && youtubeQueueIndex < 0) { youtubeQueueIndex = youtubeQueue.length - 1; loadYoutube(id); }
  saveYoutubeQueue();
  if (options.notice !== false) notice(tr("Vídeo adicionado à playlist."));
}
function playNextYoutube() {
  if (youtubeQueueIndex < 0 || youtubeQueueIndex + 1 >= youtubeQueue.length) return false;
  youtubeQueueIndex += 1; saveYoutubeQueue(); loadYoutube(youtubeQueue[youtubeQueueIndex].id, { fromQueue: true }); return true;
}
function stopYoutubeAdvanceWatcher() {
  clearInterval(youtubeAdvanceTimer);
  youtubeAdvanceTimer = null;
}
function startYoutubeAdvanceWatcher() {
  stopYoutubeAdvanceWatcher();
  // Um ciclo por segundo é suficiente para trocar no último segundo e reduz
  // pela metade o trabalho de consulta do iframe em relação ao polling de 500ms.
  youtubeAdvanceTimer = setInterval(() => {
    advanceYoutubeBeforeEnd().catch(() => { youtubeAdvanceTriggered = false; });
  }, 1000);
}
async function advanceYoutubeBeforeEnd() {
  if (!youtubePlayer || window.__frequencyYoutubeSource?.kind !== "video" || youtubeAdvanceTriggered) return;
  const duration = Number(youtubePlayer.getDuration?.() || 0);
  const current = Number(youtubePlayer.getCurrentTime?.() || 0);
  if (!duration || duration - current > 1.1) return;
  youtubeAdvanceTriggered = true;
  if (playNextYoutube()) return;
  const currentItem = youtubeQueue[youtubeQueueIndex];
  await suggestYoutubeQueue(window.__frequencyYoutubeSource.id, currentItem?.title || "");
  if (!playNextYoutube()) youtubeAdvanceTriggered = false;
}
function saveCameras(next) { localStorage.setItem(cameraKey, JSON.stringify(next)); cameras = next; renderCameras(); }
function renderCameras() {
  stopStreams(); const list = $("#camera-list"); list.replaceChildren();
  if (!cameras.length) list.append(node("p", tr("Nenhuma câmera adicionada. A conexão é opcional.")));
  cameras.forEach((camera, index) => {
    const card = node("article"); card.className = "camera-card";
    const display = node("div"), message = node("p", tr("Desconectada")); message.className = "camera-message"; message.setAttribute("role", "status");
    let timer;
    const stop = () => { clearTimeout(timer); const media = display.firstChild; if (media) { if (media.tagName === "VIDEO") media.pause(); media.removeAttribute("src"); if (media.tagName === "VIDEO") media.load(); } display.replaceChildren(); message.textContent = tr("Desconectada"); streams.delete(stop); };
    const connect = button(tr("Conectar"), () => action(async () => {
      if (document.hidden) return;
      const url = cameraUrl(camera.url, location.protocol); stop();
      const media = node(camera.kind === "mjpeg" ? "img" : "video");
      if (camera.kind === "mjpeg") { media.alt = camera.name; media.referrerPolicy = "no-referrer"; }
      else { media.controls = true; media.muted = true; media.autoplay = true; media.playsInline = true; }
      message.textContent = tr("Conectando…");
      const ready = () => { clearTimeout(timer); message.textContent = tr("Transmissão recebida"); };
      media.addEventListener(camera.kind === "mjpeg" ? "load" : "playing", ready);
      media.addEventListener("error", () => { stop(); message.textContent = tr("Não foi possível abrir. Confira o endereço, a rede e o formato da câmera."); });
      if (camera.kind === "mjpeg") message.textContent = tr("Conexão solicitada. Confira a imagem.");
      else timer = setTimeout(() => { stop(); message.textContent = tr("Sem confirmação de imagem. Confira o endereço e a compatibilidade."); }, 20000);
      streams.add(stop); display.append(media); media.src = url;
    }));
    card.append(node("h3", camera.name), display, message, connect, button(tr("Desconectar"), stop), button(tr("Remover"), () => action(async () => { saveCameras(cameras.filter((_, item) => item !== index)); notice(tr("Câmera removida deste navegador.")); })));
    list.append(card);
  });
}
function ensureYoutubeApi() {
  if (window.YT?.Player) return Promise.resolve(window.YT);
  if (youtubeApiPromise) return youtubeApiPromise;
  youtubeApiPromise = new Promise((resolve, reject) => {
    const previous = window.onYouTubeIframeAPIReady;
    window.onYouTubeIframeAPIReady = () => { previous?.(); resolve(window.YT); };
    const script = document.createElement("script");
    script.src = "https://www.youtube.com/iframe_api";
    script.async = true;
    script.onerror = () => reject(new Error(tr("Não foi possível carregar o player oficial do YouTube.")));
    document.head.append(script);
  });
  return youtubeApiPromise;
}
async function skipUnavailableYoutube(code) {
  if (youtubeSkipTriggered) return;
  youtubeSkipTriggered = true;
  const source = window.__frequencyYoutubeSource;
  const failed = youtubeQueueIndex >= 0 ? youtubeQueue[youtubeQueueIndex] : null;
  if (youtubeQueueIndex >= 0) {
    youtubeQueue.splice(youtubeQueueIndex, 1);
    youtubeQueueIndex -= 1;
    saveYoutubeQueue();
  }
  notice(tr("Vídeo indisponível. Pulando para o próximo…"));
  stopYoutubeAdvanceWatcher();
  youtubePlayer?.destroy?.(); youtubePlayer = null;
  $("#youtube-player").replaceChildren();
  if (!playNextYoutube() && source?.kind === "video") {
    await suggestYoutubeQueue(source.id, failed?.title || "");
    playNextYoutube();
  }
  youtubeSkipTriggered = false;
}

function youtubePlayerError(code) {
  const messages = {
    2: tr("O endereço do vídeo é inválido. Escolha outro resultado."),
    5: tr("Este vídeo não pode ser reproduzido no player incorporado."),
    100: tr("Este vídeo foi removido ou está privado."),
    101: tr("O proprietário não permite la reproducción en otros sitios."),
    150: tr("O proprietário não permite la reproducción en otros sitios."),
    153: tr("O YouTube recusou a incorporação deste vídeo."),
  };
  if ([2, 5, 100, 101, 150, 153].includes(code)) { skipUnavailableYoutube(code).catch(() => { youtubeSkipTriggered = false; }); return; }
  notice(messages[code] || tr("O YouTube não conseguiu reproduzir este vídeo. Escolha outro resultado."), true);
}
function youtubeCommand(command, args = []) {
  if (youtubePlayer?.[command]) { youtubePlayer[command](...args); return; }
  const frame = $("#youtube-player iframe");
  if (!frame?.contentWindow || $("#youtube-player-wrap").hidden) throw new Error(tr("Carregue um vídeo primeiro."));
  frame.contentWindow.postMessage(JSON.stringify({ event: "command", func: command, args }), YOUTUBE_PLAYER_ORIGIN);
}
function youtubeUrl(value) {
  const { kind, id } = value;
  const origin = encodeURIComponent(location.origin);
  const widgetReferrer = encodeURIComponent(location.href.split("#")[0]);
  const base = kind === "playlist"
    ? `${YOUTUBE_PLAYER_ORIGIN}/embed/videoseries?list=${encodeURIComponent(id)}`
    : `${YOUTUBE_PLAYER_ORIGIN}/embed/${id}`;
  return `${base}&enablejsapi=1&playsinline=1&autoplay=0&origin=${origin}&widget_referrer=${widgetReferrer}&rel=0`;
}
function youtubeSource(value) {
  const raw = String(value || "").trim();
  try { return { kind: "video", id: youtubeVideoId(raw) }; } catch {}
  return { kind: "playlist", id: youtubePlaylistId(raw) };
}
async function loadYoutube(value, options = {}) {
  const query = String(value || "").trim();
  if (!query) throw new Error(tr("Informe o ID ou link de um vídeo ou playlist do YouTube."));
  const source = youtubeSource(query);
  const autoStart = options.autoplay ?? youtubePlaybackStarted;
  if (source.kind === "video" && !options.fromQueue) {
    const queued = youtubeQueue.findIndex((item) => item.id === source.id);
    if (queued >= 0) youtubeQueueIndex = queued;
  }
  renderYoutubeQueue();
  window.__frequencyYoutubeSource = source;
  youtubeFallbackTried = false;
  localStorage.setItem(youtubeKey, query);
  stopYoutubeAdvanceWatcher(); youtubePlayer?.destroy?.(); youtubePlayer = null; youtubeAdvanceTriggered = false;
  $("#youtube-player").replaceChildren();
  $("#youtube-player-wrap").hidden = false;
  $("#youtube-empty-state").hidden = true;
  $("#youtube-search-title").textContent = source.kind === "playlist" ? "Playlist em reprodução" : "Vídeo em reprodução";
  $("#youtube-source-kind").textContent = source.kind === "playlist" ? "Playlist conectada" : "Vídeo conectado";
  $("#youtube-source-id").textContent = source.id;
  try {
    const YT = await ensureYoutubeApi();
    const playerVars = { autoplay: autoStart ? 1 : 0, enablejsapi: 1, playsinline: 1, origin: location.origin, widget_referrer: location.href.split("#")[0], rel: 0 };
    if (source.kind === "playlist") Object.assign(playerVars, { listType: "playlist", list: source.id });
    youtubePlayer = new YT.Player("youtube-player", {
      videoId: source.kind === "video" ? source.id : undefined,
      playerVars,
      events: {
        onReady: (event) => { if (autoStart) event.target.playVideo(); stopYoutubeAdvanceWatcher(); youtubeAdvanceTriggered = false; if (youtubePlaybackStarted) startYoutubeAdvanceWatcher(); notice(source.kind === "playlist" ? tr("Playlist carregada. Clique em Reproduzir para começar.") : tr("Vídeo carregado. Clique em Reproduzir para começar.")); },
        onStateChange: (event) => { if (event.data === YT.PlayerState.PLAYING) { youtubePlaybackStarted = true; youtubeAdvanceTriggered = false; startYoutubeAdvanceWatcher(); } if (event.data === YT.PlayerState.ENDED && source.kind === "video" && !playNextYoutube()) { youtubeAdvanceTriggered = false; advanceYoutubeBeforeEnd().catch(() => {}); } },
        onError: (event) => youtubePlayerError(event.data),
      },
    });
  } catch (error) {
    const frame = document.createElement("iframe");
    frame.title = "Player do YouTube"; frame.referrerPolicy = "strict-origin-when-cross-origin"; frame.allow = "autoplay; encrypted-media; picture-in-picture; fullscreen"; frame.allowFullscreen = true; frame.src = youtubeUrl(source);
    $("#youtube-player").append(frame);
    notice(error.message || tr("O player oficial não pôde ser carregado."), true);
  }
}
$("#youtube-form")?.addEventListener("submit", (event) => {
  event.preventDefault();
  action(async () => {
    const source = youtubeSource($("#youtube-video").value);
    if (source.kind === "video") { await checkYoutubeVideo(source.id); enqueueYoutube(source.id, source.id, { play: false }); youtubeQueueIndex = youtubeQueue.findIndex((entry) => entry.id === source.id); await loadYoutube(source.id); }
    else await loadYoutube($("#youtube-video").value);
  });
});
$("#youtube-search-form")?.addEventListener("submit", (event) => {
  event.preventDefault();
  action(async () => searchYoutube($("#youtube-search-query").value));
});
$("#youtube-clear")?.addEventListener("click", () => {
  localStorage.removeItem(youtubeKey);
  youtubeQueue = []; youtubeQueueIndex = -1; localStorage.removeItem(youtubeQueueKey); renderYoutubeQueue();
  stopYoutubeAdvanceWatcher(); youtubeAdvanceTriggered = false;
  youtubePlaybackStarted = false;
  youtubePlayer?.destroy?.(); youtubePlayer = null;
  $("#youtube-player").replaceChildren();
  $("#youtube-player-wrap").hidden = true;
  $("#youtube-empty-state").hidden = false;
  $("#youtube-video").value = "";
  notice("");
});
document.querySelectorAll("[data-youtube]").forEach((control) => control.addEventListener("click", () => action(async () => {
  youtubeCommand(control.dataset.youtube);
  notice(tr("Comando enviado ao player."));
})));
$("#camera-form")?.addEventListener("submit", (event) => {
  event.preventDefault(); const form = event.currentTarget, values = new FormData(form);
  action(async () => {
    if (cameras.length >= 8) throw new Error(tr("Limite de oito câmeras por conta neste navegador."));
    const name = String(values.get("name")).trim();
    if (!name) throw new Error(tr("Informe o nome da câmera."));
    const url = cameraUrl(String(values.get("url")), location.protocol);
    if (cameras.some((camera) => camera.url === url)) throw new Error(tr("Esta câmera já foi adicionada."));
    saveCameras([...cameras, { name, kind: values.get("kind") === "mjpeg" ? "mjpeg" : "video", url }]); form.reset(); notice(tr("Câmera salva neste navegador. Clique em Conectar para acompanhar."));
  });
});
document.addEventListener("visibilitychange", () => { if (document.hidden) stopStreams(); else if (owner) action(async () => {}); });
window.addEventListener("pagehide", stopStreams);
window.addEventListener("pageshow", (event) => { if (event.persisted) action(async () => {}); });
async function init() {
  document.body.classList.toggle("embedded", window.parent !== window);
  try {
    owner = await authorize();
    applyLocale(queryLocale || window.FrequencyI18n?.userLocale(owner, interfaceLocale) || interfaceLocale);
    if (feature === "cameras") {
      cameraKey = `frequency.cameras.${owner}`;
      const stored = read(localStorage, cameraKey, []); cameras = Array.isArray(stored) ? stored.filter((camera) => camera && typeof camera.name === "string" && typeof camera.url === "string").slice(0, 8) : [];
      renderCameras();
    } else {
      youtubeKey = `frequency.youtube.${owner}`;
      youtubeQueueKey = `frequency.youtube.queue.${owner}`;
      const savedQueue = read(localStorage, youtubeQueueKey, []);
      youtubeQueue = [];
      if (Array.isArray(savedQueue)) savedQueue.filter((item) => item && typeof item.id === "string").slice(0, 30).forEach((item) => enqueueYoutube(item.id, item.title || item.id, { notice: false }));
      renderYoutubeQueue();
      const saved = localStorage.getItem(youtubeKey);
      if (saved) {
        try {
          youtubeSource(saved);
          $("#youtube-video").value = saved;
          const savedSource = youtubeSource(saved);
          if (savedSource.kind === "video") youtubeQueueIndex = youtubeQueue.findIndex((entry) => entry.id === savedSource.id);
          loadYoutube(saved);
        } catch {
          // Buscas de texto antigas não são vídeos reproduzíveis. Não reabra
          // automaticamente uma pesquisa que deixa o player indisponível.
          localStorage.removeItem(youtubeKey);
        }
      }
    }
    $("#integration-content").hidden = false;
    notice("");
  } catch (error) { notice(error.message, true); }
}
init();

import { cameraUrl, validateCallback, validateSpotifyClientId } from "./integracoes-core.mjs";
const $ = (s) => document.querySelector(s);
const jwtKey = "frequency.access_token";
const tokenKey = "frequency.spotify.session";
const pendingKey = "frequency.spotify.pending";
const redirect = `${location.origin}/spotify`;
const feature = document.body.dataset.feature;
let owner, cameraKey, cameras = [], spotify = null, busy = false, blockedUntil = 0;
const streams = new Set();
function read(storage, key, fallback = null) { try { return JSON.parse(storage.getItem(key)) ?? fallback; } catch { return fallback; } }
function notice(message, error = false) { $("#integration-status").textContent = message; $("#integration-status").classList.toggle("integration-error", error); }
function stopStreams() { for (const stop of [...streams]) stop(); }
function disconnect() { spotify = null; sessionStorage.removeItem(tokenKey); sessionStorage.removeItem(pendingKey); renderSpotify(); }
function lock() { stopStreams(); if (feature === "spotify") disconnect(); $("#integration-content").hidden = true; }
async function authorize() {
  const token = sessionStorage.getItem(jwtKey);
  if (!token) { lock(); throw new Error("Entre no Frequency com a conta do dono para continuar."); }
  const response = await fetch("/eu", { headers: { Authorization: `Bearer ${token}` }, cache: "no-store", signal: AbortSignal.timeout(10000) });
  if (!response.ok) { lock(); throw new Error("Sua sessão não está disponível. Entre novamente no Frequency."); }
  const user = await response.json();
  const identity = `${user.academia_id}:${user.id}`;
  if (user.papel !== "dono" || !user.academia_id || user.bloqueada_frequency || (owner && owner !== identity)) { lock(); throw new Error("Esta área exige a conta ativa do dono da academia."); }
  const access = await fetch(`/academia/integracoes/${feature}`, { headers: { Authorization: `Bearer ${token}` }, cache: "no-store", signal: AbortSignal.timeout(10000) });
  if (!access.ok) { lock(); throw new Error("Recurso indisponível. Esta opção precisa estar incluída no seu pacote Premium e ser usada na instalação principal. Consulte o administrador do Frequency."); }
  return identity;
}
async function action(work) {
  if (busy) return;
  busy = true;
  try { await authorize(); await work(); } catch (error) { notice(error instanceof TypeError ? "Falha de conexão. Confira a rede e tente novamente." : error.message, true); }
  finally { busy = false; }
}
function node(tag, text) { const result = document.createElement(tag); if (text) result.textContent = text; return result; }
function button(text, work) { const el = node("button", text); el.type = "button"; el.className = "button button-secondary"; el.addEventListener("click", work); return el; }
function saveCameras(next) { localStorage.setItem(cameraKey, JSON.stringify(next)); cameras = next; renderCameras(); }
function renderCameras() {
  stopStreams(); const list = $("#camera-list"); list.replaceChildren();
  if (!cameras.length) list.append(node("p", "Nenhuma câmera adicionada. A conexão é opcional."));
  cameras.forEach((camera, index) => {
    const card = node("article"); card.className = "camera-card";
    const display = node("div"), message = node("p", "Desconectada"); message.className = "camera-message"; message.setAttribute("role", "status");
    let timer;
    const stop = () => { clearTimeout(timer); const media = display.firstChild; if (media) { if (media.tagName === "VIDEO") media.pause(); media.removeAttribute("src"); if (media.tagName === "VIDEO") media.load(); } display.replaceChildren(); message.textContent = "Desconectada"; streams.delete(stop); };
    const connect = button("Conectar", () => action(async () => {
      if (document.hidden) return;
      const url = cameraUrl(camera.url, location.protocol); stop();
      const media = node(camera.kind === "mjpeg" ? "img" : "video");
      if (camera.kind === "mjpeg") { media.alt = camera.name; media.referrerPolicy = "no-referrer"; }
      else { media.controls = true; media.muted = true; media.autoplay = true; media.playsInline = true; }
      message.textContent = "Conectando…";
      const ready = () => { clearTimeout(timer); message.textContent = "Transmissão recebida"; };
      media.addEventListener(camera.kind === "mjpeg" ? "load" : "playing", ready);
      media.addEventListener("error", () => { stop(); message.textContent = "Não foi possível abrir. Confira o endereço, a rede e o formato da câmera."; });
      // Continuous MJPEG responses may never emit a load event.
      if (camera.kind === "mjpeg") message.textContent = "Conexão solicitada. Confira a imagem; se ficar vazia, verifique a câmera e a rede.";
      else timer = setTimeout(() => { stop(); message.textContent = "Sem confirmação de imagem. Confira o endereço e a compatibilidade."; }, 20000);
      streams.add(stop); display.append(media); media.src = url;
    }));
    card.append(node("h3", camera.name), display, message, connect, button("Desconectar", stop), button("Remover", () => action(async () => { saveCameras(cameras.filter((_, i) => i !== index)); notice("Câmera removida deste navegador."); })));
    list.append(card);
  });
}
function renderSpotify() {
  if (feature !== "spotify") return;
  $("#spotify-controls").hidden = !spotify; $("#spotify-disconnect").hidden = !spotify;
  $("#spotify-connect").hidden = !!spotify;
  if (!spotify) { $("#spotify-track").textContent = "Spotify desconectado."; $("#spotify-device").replaceChildren(new Option("Dispositivo ativo", "")); }
}
async function tokenRequest(parameters) {
  const response = await fetch("https://accounts.spotify.com/api/token", { method: "POST", headers: { "Content-Type": "application/x-www-form-urlencoded" }, body: new URLSearchParams(parameters), signal: AbortSignal.timeout(15000) });
  if (!response.ok) { disconnect(); throw new Error("Não foi possível autorizar o Spotify. Confira o Client ID e o endereço de retorno."); }
  const result = await response.json();
  if (!result.access_token || !Number.isFinite(result.expires_in)) throw new Error("Resposta inválida do Spotify.");
  return result;
}
function storeToken(result, clientId) {
  spotify = { owner, clientId, access_token: result.access_token, refresh_token: result.refresh_token || spotify?.refresh_token, expires: Date.now() + result.expires_in * 1000 };
  sessionStorage.setItem(tokenKey, JSON.stringify(spotify)); renderSpotify();
}
async function player(path = "", method = "GET") {
  if (!spotify || spotify.owner !== owner) throw new Error("Conecte o Spotify primeiro.");
  if (Date.now() < blockedUntil) throw new Error("O Spotify pediu uma pausa. Aguarde antes de tentar novamente.");
  if (spotify.expires < Date.now() + 30000) {
    if (!spotify.refresh_token) { disconnect(); throw new Error("Conecte o Spotify novamente."); }
    const id = spotify.clientId;
    storeToken(await tokenRequest({ grant_type: "refresh_token", refresh_token: spotify.refresh_token, client_id: id }), id);
  }
  const response = await fetch(`https://api.spotify.com/v1/me/player${path}`, { method, headers: { Authorization: `Bearer ${spotify.access_token}` }, signal: AbortSignal.timeout(15000) });
  if (response.status === 401) { disconnect(); throw new Error("A autorização expirou. Conecte o Spotify novamente."); }
  if (response.status === 429) { blockedUntil = Date.now() + (Number(response.headers.get("Retry-After")) || 30) * 1000; throw new Error("Limite de consultas do Spotify. Aguarde antes de tentar novamente."); }
  if (!response.ok) throw new Error(response.status === 403 ? "Confira o Premium, as permissões do aplicativo e a disponibilidade deste controle no dispositivo." : response.status === 404 ? "Abra o Spotify no dispositivo e inicie uma música primeiro." : "O Spotify não confirmou a operação. Tente novamente.");
  if (response.status === 204) return null;
  return response.json();
}
async function refreshPlayer() {
  const devices = await player("/devices"), current = await player();
  const selected = $("#spotify-device").value;
  $("#spotify-device").replaceChildren(new Option("Dispositivo ativo", ""));
  for (const device of devices?.devices || []) if (device.id && !device.is_restricted) $("#spotify-device").append(new Option(device.name, device.id));
  if ([...$("#spotify-device").options].some(o => o.value === selected)) $("#spotify-device").value = selected;
  $("#spotify-track").textContent = current?.item ? `${current.is_playing ? "Tocando" : "Pausado"}: ${current.item.name} — ${(current.item.artists || []).map(a => a.name).join(", ")}` : "Sem reprodução ativa. Abra o Spotify em um dispositivo.";
  notice("Spotify atualizado.");
}
const random = () => Array.from(crypto.getRandomValues(new Uint8Array(32)), b => b.toString(16).padStart(2, "0")).join("");
$("#spotify-connect")?.addEventListener("click", () => action(async () => {
  const clientId = $("#spotify-client").value.trim();
  if (!validateSpotifyClientId(clientId)) throw new Error("Confira o Client ID público, que tem 32 caracteres.");
  if (location.protocol !== "https:" && !["127.0.0.1", "[::1]"].includes(location.hostname)) throw new Error("Abra por HTTPS ou pelo endereço local 127.0.0.1 para conectar o Spotify.");
  const verifier = random(), state = random();
  const digest = await crypto.subtle.digest("SHA-256", new TextEncoder().encode(verifier));
  const challenge = btoa(String.fromCharCode(...new Uint8Array(digest))).replace(/\+/g, "-").replace(/\//g, "_").replace(/=+$/, "");
  sessionStorage.setItem(pendingKey, JSON.stringify({ owner, verifier, state, clientId, created: Date.now() }));
  const params = new URLSearchParams({ response_type: "code", client_id: clientId, redirect_uri: redirect, state, code_challenge_method: "S256", code_challenge: challenge, scope: "user-read-playback-state user-modify-playback-state" });
  location.assign(`https://accounts.spotify.com/authorize?${params}`);
}));
$("#spotify-disconnect")?.addEventListener("click", () => { disconnect(); notice("Spotify desconectado deste navegador."); });
$("#spotify-refresh")?.addEventListener("click", () => action(refreshPlayer));
document.querySelectorAll("[data-player]").forEach(button => button.addEventListener("click", () => action(async () => {
  const command = button.dataset.player, params = new URLSearchParams();
  if ($("#spotify-device").value) params.set("device_id", $("#spotify-device").value);
  await player(`/${command}?${params}`, ["next", "previous"].includes(command) ? "POST" : "PUT");
  notice("Comando enviado ao Spotify. Use Atualizar para consultar a reprodução.");
})));
$("#spotify-set-volume")?.addEventListener("click", () => action(async () => {
  const params = new URLSearchParams({ volume_percent: $("#spotify-volume").value });
  if ($("#spotify-device").value) params.set("device_id", $("#spotify-device").value);
  await player(`/volume?${params}`, "PUT"); notice("Volume enviado ao Spotify.");
}));
$("#camera-form")?.addEventListener("submit", event => {
  event.preventDefault(); const form = event.currentTarget, values = new FormData(form);
  action(async () => {
    if (cameras.length >= 8) throw new Error("Limite de oito câmeras por conta neste navegador.");
    const name = String(values.get("name")).trim();
    if (!name) throw new Error("Informe o nome da câmera.");
    const url = cameraUrl(String(values.get("url")), location.protocol);
    if (cameras.some(c => c.url === url)) throw new Error("Esta câmera já foi adicionada.");
    saveCameras([...cameras, { name, kind: values.get("kind") === "mjpeg" ? "mjpeg" : "video", url }]); form.reset(); notice("Câmera salva neste navegador. Clique em Conectar para acompanhar.");
  });
});
document.addEventListener("visibilitychange", () => { if (document.hidden) stopStreams(); else if (owner) action(async () => {}); });
window.addEventListener("pagehide", stopStreams);
window.addEventListener("pageshow", event => { if (event.persisted) action(async () => {}); });
async function init() {
  const params = new URLSearchParams(location.search);
  if (params.has("code") || params.has("error")) history.replaceState(null, "", redirect);
  try {
    owner = await authorize();
    if (feature === "cameras") {
      cameraKey = `frequency.cameras.${owner}`;
      const stored = read(localStorage, cameraKey, []); cameras = Array.isArray(stored) ? stored.filter(c => c && typeof c.name === "string" && typeof c.url === "string").slice(0, 8) : [];
      renderCameras();
    } else {
      spotify = read(sessionStorage, tokenKey); if (spotify?.owner !== owner) disconnect();
      $("#spotify-redirect").textContent = redirect; renderSpotify();
    }
    $("#integration-content").hidden = false;
    notice("Opção do pacote Premium. Conecte quando desejar utilizar.");
    if (feature === "spotify" && (params.has("code") || params.has("error"))) {
      const pending = read(sessionStorage, pendingKey); sessionStorage.removeItem(pendingKey);
      const code = validateCallback(pending, params, owner);
      storeToken(await tokenRequest({ grant_type: "authorization_code", code, redirect_uri: redirect, client_id: pending.clientId, code_verifier: pending.verifier }), pending.clientId);
      notice("Spotify conectado. Clique em Atualizar para selecionar o dispositivo.");
    }
  } catch (error) { notice(error.message, true); }
}
init();

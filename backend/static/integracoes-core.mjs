export function cameraUrl(value, pageProtocol = "https:") {
  let url;
  try { url = new URL(value); } catch { throw new Error("Informe um endereço de transmissão válido."); }
  if (!["http:", "https:"].includes(url.protocol)) throw new Error("Use HTTP ou HTTPS. RTSP/ONVIF precisam de uma ponte local.");
  if (url.username || url.password || url.search || url.hash) throw new Error("Não use senhas, tokens ou parâmetros no endereço da câmera.");
  if (pageProtocol === "https:" && url.protocol !== "https:") throw new Error("Nesta página a câmera precisa usar HTTPS.");
  if (url.href.length > 2048) throw new Error("Endereço muito longo.");
  return url.href;
}
export function validateCallback(pending, params, owner, now = Date.now()) {
  if (!pending || pending.owner !== owner || !pending.state || params.get("state") !== pending.state || !Number.isFinite(pending.created) || now - pending.created > 600000 || now < pending.created) throw new Error("Conexão expirada ou inválida. Conecte o Spotify novamente.");
  if (params.has("error")) throw new Error("A autorização do Spotify não foi concluída.");
  if (!params.get("code")) throw new Error("O Spotify não retornou o código de autorização.");
  return params.get("code");
}
export function validateSpotifyClientId(value) {
  return /^[A-Za-z0-9]{32}$/.test(value);
}

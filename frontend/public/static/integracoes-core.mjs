export function cameraUrl(value, pageProtocol = "https:") {
  let url;
  try { url = new URL(value); } catch { throw new Error("Informe um endereço de transmissão válido."); }
  if (!["http:", "https:"].includes(url.protocol)) throw new Error("Use HTTP ou HTTPS. RTSP/ONVIF precisam de uma ponte local.");
  if (url.username || url.password || url.search || url.hash) throw new Error("Não use senhas, tokens ou parâmetros no endereço da câmera.");
  if (pageProtocol === "https:" && url.protocol !== "https:") throw new Error("Nesta página a câmera precisa usar HTTPS.");
  if (url.href.length > 2048) throw new Error("Endereço muito longo.");
  return url.href;
}
export function youtubeVideoId(value) {
  const input = String(value || "").trim();
  if (/^[A-Za-z0-9_-]{11}$/.test(input)) return input;
  let url;
  try { url = new URL(input); } catch { throw new Error("Informe um link ou ID válido do YouTube."); }
  const host = url.hostname.toLowerCase().replace(/^www\./, "");
  let id = "";
  if (host === "youtu.be") id = url.pathname.split("/").filter(Boolean)[0] || "";
  if (["youtube.com", "m.youtube.com"].includes(host)) {
    id = url.searchParams.get("v") || "";
    if (!id) {
      const parts = url.pathname.split("/").filter(Boolean);
      if (["embed", "shorts", "live"].includes(parts[0])) id = parts[1] || "";
    }
  }
  if (!/^[A-Za-z0-9_-]{11}$/.test(id)) throw new Error("Informe um link ou ID válido do YouTube.");
  return id;
}
export function youtubePlaylistId(value) {
  const input = String(value || "").trim();
  if (/^[A-Za-z0-9_-]{12,100}$/.test(input)) return input;
  let url;
  try { url = new URL(input); } catch { throw new Error("Informe o ID ou link de uma playlist do YouTube."); }
  const host = url.hostname.toLowerCase().replace(/^www./, "");
  if (!["youtube.com", "m.youtube.com", "youtu.be"].includes(host)) throw new Error("Informe uma playlist do YouTube.");
  const id = url.searchParams.get("list") || "";
  if (!/^[A-Za-z0-9_-]{12,100}$/.test(id)) throw new Error("Informe o ID ou link de uma playlist do YouTube.");
  return id;
}

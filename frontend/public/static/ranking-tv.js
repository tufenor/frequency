// Página de ranking para TV: somente leitura. O token vem do endereço (/painel/ranking/<token>) e nunca é gravado.
(() => {
  const token = location.pathname.split("/").filter(Boolean).pop() || "";
  const $ = (id) => document.getElementById(id);
  const fmt = (v, metrica) => (metrica === "volume" ? `${Math.round(v).toLocaleString("pt-BR")} kg` : `${v} ${v === 1 ? "treino" : "treinos"}`);
  async function atualizar() {
    try {
      const r = await fetch(`/painel/ranking/${encodeURIComponent(token)}/dados`, { cache: "no-store", referrerPolicy: "no-referrer" });
      if (!r.ok) throw new Error(String(r.status));
      const d = await r.json();
      $("academia").textContent = d.academia;
      $("titulo").textContent = d.desafio.nome;
      const f = (s) => new Date(s + "T12:00:00").toLocaleDateString("pt-BR", { day: "2-digit", month: "short" });
      $("periodo").textContent = `${f(d.desafio.inicio)} a ${f(d.desafio.fim)}`;
      const lista = $("lista");
      lista.replaceChildren(...d.ranking.map((p) => {
        const li = document.createElement("li");
        const a = document.createElement("span"); a.className = "pos"; a.textContent = `${p.posicao}º`;
        const b = document.createElement("span"); b.className = "nome"; b.textContent = p.nome;
        const c = document.createElement("span"); c.className = "valor"; c.textContent = fmt(p.valor, d.desafio.metrica);
        li.append(a, b, c);
        return li;
      }));
      $("vazio").hidden = d.ranking.length > 0;
      $("erro").hidden = true;
    } catch {
      $("erro").hidden = false;
    }
  }
  atualizar();
  setInterval(atualizar, 30000);
})();

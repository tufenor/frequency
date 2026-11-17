// Painel: desafios, aparelhos disponíveis e conferência de QR. Usa as funções globais do app.js.
(() => {
  const T = (t) => (typeof traduzir === "function" ? traduzir(t) : t);
  const E = (tag, text, cls) => element(tag, text, cls);
  const painel = (...f) => { const p = E("div", undefined, "panel"); p.append(...f); return p; };
  const campo = (rotulo, input) => { const l = E("label", T(rotulo)); l.append(input); return l; };
  const entrada = (nome, tipo = "text", extra = {}) => { const i = E("input"); i.name = nome; i.type = tipo; Object.assign(i, extra); return i; };
  const botao = (texto, fn, cls = "button button-secondary button-small") => {
    const b = E("button", T(texto), cls); b.type = "button";
    b.addEventListener("click", async () => { b.disabled = true; try { await fn(); } catch (e) { showNotice(e.message, true); } finally { b.disabled = false; } });
    return b;
  };
  function tabela(cab, linhas) {
    const t = E("table", undefined, "table"); const h = E("thead"); const r = E("tr"); cab.forEach((c) => r.append(E("th", T(c)))); h.append(r); t.append(h);
    const b = E("tbody"); linhas.forEach((cels) => { const tr = E("tr"); cels.forEach((c) => { const td = E("td"); if (c instanceof Node) td.append(c); else td.textContent = c ?? "—"; tr.append(td); }); b.append(tr); });
    t.append(b); const w = E("div", undefined, "table-wrap"); w.append(t); return w;
  }
  const raiz = (id) => document.getElementById(id + "-root");
  const SIT = { em_breve: "Em breve", em_andamento: "Em andamento", encerrado: "Encerrado" };
  const MET = { treinos: "Treinos concluídos", volume: "Volume (kg)" };

  async function desafios() {
    const r = raiz("desafios");
    const dados = await api("/academia/desafios");
    const detalhe = E("div");
    const lista = tabela(["Desafio", "Métrica", "Período", "Situação", "Participantes", ""], dados.desafios.map((d) => {
      const acoes = E("span");
      acoes.append(
        botao("Ranking", async () => {
          const x = await api(`/academia/desafios/${d.id}/ranking`);
          detalhe.replaceChildren(painel(E("h2", `${d.nome} · ${T(MET[d.metrica])}`), x.ranking.length ? tabela(["Posição", "Aluno", "Pontos"], x.ranking.map((p) => [`${p.posicao}º`, p.nome, p.valor])) : E("p", T("Ainda sem pontuação."), "muted")));
        }), " ",
        botao(d.tv_ativa ? "Trocar endereço da TV" : "Gerar endereço da TV", async () => {
          const x = await api(`/academia/desafios/${d.id}/tv`, { method: "POST" });
          const url = location.origin + x.caminho;
          detalhe.replaceChildren(painel(E("h2", T("Endereço da TV")), E("p", T("Abra este endereço no navegador da TV. Ele mostra só nomes abreviados e pontos, e se atualiza sozinho. Copie agora: ele não aparece de novo."), "muted"), (() => { const c = E("code", url, "mono-block"); return c; })()));
          await desafios();
        }), " ",
        d.tv_ativa ? botao("Desligar TV", async () => { await api(`/academia/desafios/${d.id}/tv`, { method: "DELETE" }); await desafios(); }) : "", " ",
        d.situacao !== "encerrado" ? botao("Encerrar", async () => { if (confirm(T("Encerrar este desafio? A tela da TV deixa de funcionar."))) { await api(`/academia/desafios/${d.id}`, { method: "PATCH", body: { ativo: false } }); await desafios(); } }) : "");
      return [d.nome, T(MET[d.metrica]), `${d.inicio} → ${d.fim}`, T(SIT[d.situacao]), d.participantes, acoes];
    }));
    const f = E("form", undefined, "panel form-grid"); const sel = E("select"); sel.name = "metrica";
    Object.entries(MET).forEach(([v, t]) => sel.add(new Option(T(t), v)));
    const hoje = new Date(); const fim = new Date(hoje.getTime() + 29 * 86400000);
    const ini = entrada("inicio", "date", { required: true }); ini.value = hoje.toLocaleDateString("sv-SE");
    const fi = entrada("fim", "date", { required: true }); fi.value = fim.toLocaleDateString("sv-SE");
    f.append(E("h2", T("Novo desafio")), campo("Nome *", entrada("nome", "text", { required: true, minLength: 2, maxLength: 80, placeholder: "Desafio de outubro" })), campo("O que conta", sel), campo("Início", ini), campo("Fim", fi));
    const a = E("div", undefined, "form-actions"); const b = E("button", T("Criar desafio"), "button button-primary"); b.type = "submit"; a.append(b); f.append(a);
    f.addEventListener("submit", async (ev) => { ev.preventDefault(); const d = new FormData(f); try { await api("/academia/desafios", { method: "POST", body: { nome: String(d.get("nome")).trim(), metrica: d.get("metrica"), inicio: d.get("inicio"), fim: d.get("fim") } }); await desafios(); } catch (e) { showNotice(e.message, true); } });
    r.replaceChildren(painel(lista), detalhe, f);
  }

  async function aparelhos() {
    const r = raiz("aparelhos");
    const d = await api("/academia/equipamentos");
    const caixas = d.equipamentos.map((e) => { const c = entrada("e", "checkbox"); c.checked = e.disponivel; c.dataset.nome = e.equipamento; const l = E("label"); l.append(c, " " + e.equipamento); return [l, c]; });
    const box = painel(...caixas.map(([l]) => l));
    box.append(botao("Salvar", async () => {
      await api("/academia/equipamentos", { method: "PUT", body: { indisponiveis: caixas.filter(([, c]) => !c.checked).map(([, c]) => c.dataset.nome) } });
      showNotice("Aparelhos atualizados.");
    }, "button button-primary"));
    r.replaceChildren(box);
  }

  async function qr() {
    const r = raiz("qr-acesso"); const res = E("div");
    const f = E("form", undefined, "panel form-grid");
    const inp = entrada("codigo", "text", { required: true, minLength: 8, maxLength: 400, autocomplete: "off", placeholder: "Cole ou leia o código fqm_…" });
    f.append(campo("Código do QR *", inp));
    const a = E("div", undefined, "form-actions"); const b = E("button", T("Conferir"), "button button-primary"); b.type = "submit"; a.append(b); f.append(a);
    f.addEventListener("submit", async (ev) => {
      ev.preventDefault();
      try {
        const x = await api("/academia/acesso/qr", { method: "POST", body: { codigo: inp.value.trim() } });
        res.replaceChildren(painel(E("h2", x.liberado ? T("Liberado") : T("Não liberado")), E("p", x.nome), E("p", x.liberado ? (x.dias_restantes != null ? `${T("Próximo vencimento em")} ${x.dias_restantes} ${T("dias")}.` : "") : T(({ mensalidade_atrasada: "Mensalidade atrasada.", aluno_inativo: "Aluno inativo.", plano_nao_cadastrado: "Aluno sem plano.", sem_pagamento_em_aberto: "Sem cobrança em aberto." })[x.motivo] || "Não liberado."), "muted")));
      } catch (e) { res.replaceChildren(painel(E("h2", T("QR inválido")), E("p", e.message, "muted"))); }
      inp.value = "";
    });
    r.replaceChildren(f, res);
  }

  window.FrequenciaOnda1B = { desafios, aparelhos, qr };
})();

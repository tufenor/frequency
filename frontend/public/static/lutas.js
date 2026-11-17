// Painel de Lutas e aulas coletivas. Usa as funções globais do app.js (api, element, showNotice, traduzir, state).
(() => {
  const T = (t) => (typeof traduzir === "function" ? traduzir(t) : t);
  const E = (tag, text, cls) => element(tag, text, cls);
  const dias = ["Domingo", "Segunda", "Terça", "Quarta", "Quinta", "Sexta", "Sábado"];
  const est = { tab: null, dados: {} };

  function campo(rotulo, input) { const l = E("label", T(rotulo)); l.append(input); return l; }
  function entrada(nome, tipo = "text", extra = {}) { const i = E("input"); i.name = nome; i.type = tipo; Object.assign(i, extra); return i; }
  function botao(texto, fn, cls = "button button-secondary button-small") {
    const b = E("button", T(texto), cls); b.type = "button";
    b.addEventListener("click", async () => { b.disabled = true; try { await fn(); } catch (e) { showNotice(e.message, true); } finally { b.disabled = false; } });
    return b;
  }
  function tabela(cabecalho, linhas) {
    const t = E("table", undefined, "table"); const h = E("thead"); const r = E("tr");
    cabecalho.forEach((c) => r.append(E("th", T(c)))); h.append(r); t.append(h);
    const b = E("tbody"); linhas.forEach((cels) => { const tr = E("tr"); cels.forEach((c) => { const td = E("td"); if (c instanceof Node) td.append(c); else td.textContent = c ?? "—"; tr.append(td); }); b.append(tr); });
    t.append(b); const w = E("div", undefined, "table-wrap"); w.append(t); return w;
  }
  function painel(...filhos) { const p = E("div", undefined, "panel"); p.append(...filhos); return p; }
  function form(titulo, campos, ao) {
    const f = E("form", undefined, "panel form-grid"); f.append(E("h2", T(titulo)), ...campos);
    const a = E("div", undefined, "form-actions"); const b = E("button", T("Salvar"), "button button-primary"); b.type = "submit"; a.append(b); f.append(a);
    f.addEventListener("submit", async (ev) => { ev.preventDefault(); try { await ao(new FormData(f)); f.reset(); await desenhar(); } catch (e) { showNotice(e.message, true); } });
    return f;
  }
  const dono = () => state.user?.papel === "dono";
  const professor = () => state.user?.papel === "professor";

  async function carregarBase() {
    const d = est.dados;
    [d.modalidades, d.turmas] = await Promise.all([api("/lutas/modalidades"), api("/lutas/turmas")]).then((r) => [r[0].modalidades, r[1].turmas]);
    if (!professor()) { [d.professores, d.faixas, d.planos] = await Promise.all([api("/lutas/professores"), api("/lutas/faixas"), api("/lutas/planos")]).then((r) => [r[0].professores, r[1].faixas, r[2].planos]); }
  }

  const abas = {
    chamada: ["Chamada", viewChamada], turmas: ["Turmas", viewTurmas], modalidades: ["Modalidades e planos", viewModalidades],
    professores: ["Professores", viewProfessores], faixas: ["Faixas", viewFaixas], relatorios: ["Relatórios", viewRelatorios], local: ["Local", viewLocal],
  };
  function abasDoPapel() { return professor() ? ["chamada", "turmas", "relatorios"] : dono() ? Object.keys(abas) : ["chamada", "turmas", "faixas", "relatorios"]; }

  async function desenhar() {
    const raiz = document.getElementById("lutas-root"); if (!raiz) return;
    await carregarBase();
    const nav = E("div", undefined, "tabs"); const lista = abasDoPapel(); est.tab = lista.includes(est.tab) ? est.tab : lista[0];
    lista.forEach((k) => { const b = E("button", T(abas[k][0]), "button " + (k === est.tab ? "button-primary" : "button-secondary") + " button-small"); b.type = "button"; b.addEventListener("click", () => { est.tab = k; desenhar(); }); nav.append(b); });
    const corpo = E("div"); raiz.replaceChildren(nav, corpo);
    corpo.replaceChildren(...(await abas[est.tab][1]()));
  }

  function opcoes(sel, itens, vazio) { sel.replaceChildren(); if (vazio) sel.add(new Option(T(vazio), "")); itens.forEach(([v, t]) => sel.add(new Option(t, v))); return sel; }

  async function viewModalidades() {
    const d = est.dados; const out = [];
    out.push(painel(tabela(["Modalidade", "Tipo", ""], d.modalidades.map((m) => [m.nome, T(m.categoria === "luta" ? "Luta" : "Aula coletiva"), dono() ? botao(m.ativa ? "Desativar" : "Ativar", async () => { await api(`/lutas/modalidades/${m.id}`, { method: "PATCH", body: { ativa: !m.ativa } }); await desenhar(); }) : ""]))));
    if (!dono()) return out;
    const cat = E("select"); cat.name = "categoria"; opcoes(cat, [["luta", T("Luta")], ["aula", T("Aula coletiva")]]);
    out.push(form("Nova modalidade", [campo("Nome *", entrada("nome", "text", { required: true, minLength: 2, maxLength: 60 })), campo("Tipo", cat)],
      (f) => api("/lutas/modalidades", { method: "POST", body: { nome: String(f.get("nome")).trim(), categoria: f.get("categoria") } })));
    const bloco = E("div", undefined, "panel"); bloco.append(E("h2", T("Quais modalidades cada plano inclui")), E("p", T("Plano sem modalidade não dá acesso à aba Luta do aluno."), "muted"));
    d.planos.forEach((p) => {
      const linha = E("div", undefined, "form-actions"); linha.append(E("strong", p.nome));
      d.modalidades.filter((m) => m.ativa).forEach((m) => { const c = entrada("m" + m.id, "checkbox"); c.checked = p.modalidade_ids.includes(m.id); c.dataset.mid = m.id; const l = E("label"); l.append(c, " " + m.nome); linha.append(l); });
      linha.append(botao("Salvar plano", async () => { const ids = [...linha.querySelectorAll("input:checked")].map((c) => Number(c.dataset.mid)); await api(`/lutas/planos/${p.id}/modalidades`, { method: "PUT", body: { modalidade_ids: ids } }); showNotice("Plano atualizado."); }));
      bloco.append(linha);
    });
    out.push(bloco); return out;
  }

  async function viewProfessores() {
    const d = est.dados; const out = [painel(tabela(["Professor", "Login", ""], d.professores.map((p) => [p.nome, p.email || T("sem login"), p.ativo && dono() ? botao("Desativar", async () => { await api(`/lutas/professores/${p.id}`, { method: "DELETE" }); await desenhar(); }) : (p.ativo ? "" : T("Inativo"))])))];
    if (dono()) out.push(form("Novo professor", [campo("Nome *", entrada("nome", "text", { required: true, minLength: 2 })), campo("E-mail de acesso (opcional)", entrada("email", "email")), campo("Senha (mín. 10 caracteres, só com e-mail)", entrada("senha", "password", { minLength: 10, autocomplete: "new-password" }))],
      (f) => api("/lutas/professores", { method: "POST", body: { nome: String(f.get("nome")).trim(), email: String(f.get("email") || "").trim() || null, senha: String(f.get("senha") || "") || null } })));
    return out;
  }

  async function viewTurmas() {
    const d = est.dados; const out = [];
    const nomeMod = (id) => d.modalidades.find((m) => m.id === id)?.nome || "—";
    const nomeProf = (id) => d.professores?.find((p) => p.id === id)?.nome || "—";
    out.push(painel(tabela(["Turma", "Modalidade", "Professor", "Horários", "Vagas", ""], d.turmas.map((t) => [
      t.nome, nomeMod(t.modalidade_id), professor() ? "" : nomeProf(t.professor_id),
      t.horarios.map((h) => `${T(dias[h.dia_semana])} ${h.inicio}–${h.fim}`).join(" · ") || "—",
      `${t.reservas}/${t.capacidade}${t.espera ? ` (+${t.espera} ${T("na espera")})` : ""}`,
      dono() ? botao("Horário…", async () => {
        const dia = prompt(T("Dia da semana (0 = domingo … 6 = sábado)")); if (dia === null) return;
        const ini = prompt(T("Início (HH:MM)")); if (!ini) return; const fim = prompt(T("Fim (HH:MM)")); if (!fim) return;
        await api(`/lutas/turmas/${t.id}/horarios`, { method: "POST", body: { dia_semana: Number(dia), inicio: ini, fim } }); await desenhar();
      }) : "",
    ]))));
    if (!dono()) return out;
    const sm = E("select"); sm.name = "modalidade_id"; opcoes(sm, d.modalidades.filter((m) => m.ativa).map((m) => [m.id, m.nome]));
    const sp = E("select"); sp.name = "professor_id"; opcoes(sp, d.professores.filter((p) => p.ativo).map((p) => [p.id, p.nome]), "Sem professor");
    const rs = entrada("exige_reserva", "checkbox");
    out.push(form("Nova turma", [campo("Nome *", entrada("nome", "text", { required: true, minLength: 2 })), campo("Modalidade *", sm), campo("Professor", sp), campo("Capacidade", entrada("capacidade", "number", { min: 1, max: 500, value: 30 })), campo("Exige reserva para confirmar presença", rs)],
      (f) => api("/lutas/turmas", { method: "POST", body: { nome: String(f.get("nome")).trim(), modalidade_id: Number(f.get("modalidade_id")), professor_id: f.get("professor_id") ? Number(f.get("professor_id")) : null, capacidade: Number(f.get("capacidade")), exige_reserva: f.get("exige_reserva") === "on" } })));
    return out;
  }

  async function viewFaixas() {
    const d = est.dados; const out = [];
    const nomeMod = (id) => d.modalidades.find((m) => m.id === id)?.nome || "—";
    out.push(painel(tabela(["Modalidade", "Faixa", "Ordem", "Aulas mínimas", ""], d.faixas.map((f) => [nomeMod(f.modalidade_id), f.nome, f.ordem, f.aulas_minimas, dono() ? botao("Apagar", async () => { await api(`/lutas/faixas/${f.id}`, { method: "DELETE" }); await desenhar(); }) : ""]))));
    if (dono()) {
      const sm = E("select"); sm.name = "modalidade_id"; opcoes(sm, d.modalidades.filter((m) => m.categoria === "luta").map((m) => [m.id, m.nome]));
      out.push(form("Nova faixa", [campo("Modalidade *", sm), campo("Nome *", entrada("nome", "text", { required: true })), campo("Ordem (0 = primeira)", entrada("ordem", "number", { min: 0, max: 50, value: 0 })), campo("Aulas validadas para chegar nela", entrada("aulas_minimas", "number", { min: 0, value: 0 }))],
        (f) => api("/lutas/faixas", { method: "POST", body: { modalidade_id: Number(f.get("modalidade_id")), nome: String(f.get("nome")).trim(), ordem: Number(f.get("ordem")), aulas_minimas: Number(f.get("aulas_minimas")) } })));
    }
    const sf = E("select"); sf.name = "faixa_id"; opcoes(sf, d.faixas.map((f) => [f.id, `${nomeMod(f.modalidade_id)} · ${f.nome}`]));
    out.push(form("Graduar aluno", [campo("ID do aluno *", entrada("aluno_id", "number", { required: true, min: 1 })), campo("Faixa *", sf)],
      async (f) => { await api(`/lutas/alunos/${Number(f.get("aluno_id"))}/graduacao`, { method: "POST", body: { faixa_id: Number(f.get("faixa_id")) } }); showNotice("Graduação registrada."); }));
    if (!professor()) out.push(form("Atestado médico", [campo("ID do aluno *", entrada("aluno_id", "number", { required: true, min: 1 })), campo("Válido até *", entrada("valido_ate", "date", { required: true })), campo("Observação", entrada("observacao", "text", { maxLength: 200 }))],
      async (f) => { await api(`/lutas/alunos/${Number(f.get("aluno_id"))}/atestado`, { method: "POST", body: { valido_ate: f.get("valido_ate"), observacao: String(f.get("observacao") || "") } }); showNotice("Atestado registrado."); }));
    return out;
  }

  async function viewChamada() {
    const d = est.dados; const st = est.chamada || (est.chamada = {});
    const st_t = E("select"); opcoes(st_t, d.turmas.map((t) => [t.id, t.nome])); if (st.turma) st_t.value = st.turma;
    const dt = entrada("data", "date"); dt.value = st.data || new Date().toLocaleDateString("sv-SE");
    const lista = E("div");
    async function abrir(horario) {
      st.turma = st_t.value; st.data = dt.value; if (!st.turma) { lista.replaceChildren(E("p", T("Cadastre uma turma primeiro."), "muted")); return; }
      let c; try { c = await api(`/lutas/chamada?turma_id=${st.turma}&data=${st.data}` + (horario ? `&horario_id=${horario}` : "")); } catch (e) { lista.replaceChildren(E("p", e.message, "muted")); return; }
      if (c.escolher_horario) { lista.replaceChildren(...c.escolher_horario.map((h) => botao(new Date(h.inicio).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" }), () => abrir(h.horario_id)))); return; }
      const cab = E("div", undefined, "panel"); cab.append(E("h2", `${c.turma} · ${new Date(c.inicio).toLocaleString()}`), E("p", `${T("Código do QR da aula")}: ${c.codigo_qr}`, "muted"));
      const rotulo = { confirmada: "Aguardando validação", validada: "Presente", ausente: "Ausente" };
      const linhas = c.alunos.map((a) => [a.nome, a.estado ? T(rotulo[a.estado]) : T("Não confirmou"), a.dentro_do_raio === false ? T("Fora do raio") : a.dentro_do_raio ? T("No local") : "—",
        c.ajustavel ? (() => { const w = E("span"); w.append(botao("Presente", async () => { await api(`/lutas/chamada/${c.aula_id}/alunos/${a.aluno_id}`, { method: "PUT", body: { acao: "validar" } }); await abrir(horario); }, "button button-primary button-small"), " ", botao("Ausente", async () => { await api(`/lutas/chamada/${c.aula_id}/alunos/${a.aluno_id}`, { method: "PUT", body: { acao: "ausentar" } }); await abrir(horario); })); return w; })() : T("Prazo de ajuste encerrado")]);
      lista.replaceChildren(cab, painel(tabela(["Aluno", "Situação", "Local", ""], linhas)));
    }
    const ir = botao("Abrir chamada", () => abrir(), "button button-primary");
    const barra = painel(campo("Turma", st_t), campo("Data", dt), ir);
    return [barra, lista];
  }

  async function viewRelatorios() {
    const d = est.dados; const out = [];
    const oc = await api("/lutas/relatorios/ocupacao");
    out.push(painel(E("h2", T("Ocupação das turmas")), tabela(["Turma", "Reservas", "Capacidade", "Ocupação", "Média de presentes"], oc.turmas.map((t) => [t.nome, t.reservas, t.capacidade, t.ocupacao_pct + "%", t.media_presentes]))));
    const st = E("select"); opcoes(st, d.turmas.map((t) => [t.id, t.nome]));
    const de = entrada("de", "date"); const ate = entrada("ate", "date"); const hoje = new Date(); ate.value = hoje.toLocaleDateString("sv-SE"); hoje.setDate(hoje.getDate() - 30); de.value = hoje.toLocaleDateString("sv-SE");
    const res = E("div");
    const ver = botao("Ver frequência", async () => {
      const r = await api(`/lutas/relatorios/frequencia?turma_id=${st.value}&de=${de.value}&ate=${ate.value}`);
      res.replaceChildren(E("p", `${r.aulas_no_periodo} ${T("aulas no período")}`, "muted"), tabela(["Aluno", "Presenças validadas", "Ausências", "Pendentes"], r.alunos.map((a) => [a.nome, a.validadas, a.ausencias, a.pendentes])));
    }, "button button-primary");
    out.push(painel(E("h2", T("Frequência por turma")), campo("Turma", st), campo("De", de), campo("Até", ate), ver, res)); return out;
  }

  async function viewLocal() {
    const l = await api("/lutas/local");
    return [form("Local da academia (para saber se o aluno confirmou dentro)", [
      campo("Latitude *", entrada("latitude", "number", { required: true, step: "any", value: l.latitude ?? "" })), campo("Longitude *", entrada("longitude", "number", { required: true, step: "any", value: l.longitude ?? "" })),
      campo("Raio em metros (20–2000)", entrada("raio_m", "number", { min: 20, max: 2000, value: l.raio_m })), campo("Fuso horário", entrada("fuso", "text", { value: l.fuso }))],
      async (f) => { await api("/lutas/local", { method: "PUT", body: { latitude: Number(f.get("latitude")), longitude: Number(f.get("longitude")), raio_m: Number(f.get("raio_m")), fuso: String(f.get("fuso")) } }); showNotice("Local salvo."); })];
  }

  window.FrequenciaLutas = {
    async carregar() {
      const raiz = document.getElementById("lutas-root");
      try { await desenhar(); } catch (e) {
        if (/lutas[_ ]desligado/i.test(e.message)) raiz.replaceChildren(painel(E("p", T("O módulo de lutas e aulas ainda não está ligado para esta academia. Fale com o suporte Frequency."))));
        else throw e;
      }
    },
  };
})();

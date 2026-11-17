/* Business UI. API routes are documented in API_CONTRACT.md. No external dependencies. */
const businessState = { summary: null, academies: [], invoices: [], plans: [], payments: [], imageUrls: new Map(), invoiceRequest: 0 };

function uiText(tag, text, className) { return element(tag, traduzir(text), className); }
function actionButton(text, action, tone = "quiet") {
  const button = uiText("button", text, `button button-${tone} button-small`);
  button.type = "button";
  button.addEventListener("click", () => busyAction(button, action));
  return button;
}
async function busyAction(control, action) {
  if (control.disabled) return;
  control.disabled = true;
  control.setAttribute("aria-busy", "true");
  try { await action(); } catch (error) { showNotice(error.message, true); }
  finally { control.disabled = false; control.removeAttribute("aria-busy"); }
}
function bindForm(id, action) {
  $(id).addEventListener("submit", (event) => {
    event.preventDefault();
    const form = event.currentTarget;
    if (state.config.somente_consulta || !form.reportValidity()) return;
    busyAction(form.querySelector('[type="submit"]'), async () => action(form, formObject(form)));
  });
}
function statCards(target, items) {
  $(target).replaceChildren(...items.map(([label, value, symbol, note]) => {
    const card = element("article", null, "stat-card");
    const top = element("div", null, "stat-card-title");
    const mark = element("span", null, "stat-icon"); mark.append(icon(symbol || "chart"));
    top.append(uiText("p", label), mark);
    card.append(top, element("strong", value));
    if (note) card.append(uiText("small", note, "field-help"));
    return card;
  }));
}
function lastMonths(count = 12) {
  const now = new Date();
  return Array.from({ length: count }, (_, i) => {
    const date = new Date(Date.UTC(now.getFullYear(), now.getMonth() - count + i + 1, 1));
    return date.toISOString().slice(0, 7);
  });
}
function monthLabel(key) {
  return new Intl.DateTimeFormat(interfaceLocale, { month: "short", year: "2-digit", timeZone: "UTC" }).format(new Date(`${key}-01T00:00:00Z`));
}
function amountCents(value) {
  const text = String(value ?? "0");
  if (!/^\d+(\.\d{1,2})?$/.test(text)) throw new Error(traduzir("Valor financeiro invÃ¡lido recebido do servidor."));
  const [whole, fraction = ""] = text.split(".");
  const cents = Number(whole) * 100 + Number(fraction.padEnd(2, "0"));
  if (!Number.isSafeInteger(cents)) throw new Error(traduzir("Valor financeiro fora do limite suportado."));
  return cents;
}
function sumMoney(rows, key) { return rows.reduce((sum, row) => sum + amountCents(row[key]), 0) / 100; }
function fillCurrencies(selectId, currencies, defaultCurrency) {
  const select = $(selectId);
  const previous = select.value;
  const values = [...new Set(currencies.filter(Boolean))].sort();
  if (!values.length) values.push(defaultCurrency || "BRL");
  select.replaceChildren(...values.map((currency) => new Option(currency, currency)));
  select.value = values.includes(previous) ? previous : values.includes(defaultCurrency) ? defaultCurrency : values[0];
}
function drawChart(target, rows, valueKey, currency, title) {
  const host = $(target);
  const months = lastMonths();
  const values = months.map((mes) => currency
    ? sumMoney(rows.filter((row) => row.mes === mes && row.moeda === currency), valueKey)
    : rows.filter((row) => row.mes === mes).reduce((sum, row) => sum + Number(row[valueKey] || 0), 0));
  const format = (v) => currency ? formatMoney(v, currency) : new Intl.NumberFormat(interfaceLocale).format(v);
  const svg = document.createElementNS("http://www.w3.org/2000/svg", "svg");
  svg.setAttribute("viewBox", "0 0 640 235"); svg.setAttribute("role", "img"); svg.setAttribute("aria-label", traduzir(title));
  const svgNode = (name, attrs, text) => {
    const node = document.createElementNS(svg.namespaceURI, name);
    Object.entries(attrs).forEach(([key, value]) => node.setAttribute(key, value));
    if (text !== undefined) node.textContent = text;
    svg.append(node); return node;
  };
  const max = Math.max(1, ...values);
  [0, 0.5, 1].forEach((ratio) => svgNode("line", { x1: 10, x2: 630, y1: 185 - ratio * 155, y2: 185 - ratio * 155, class: "chart-gridline" }));
  values.forEach((value, i) => {
    const bar = svgNode("rect", { x: 14 + i * 52, y: 185 - value / max * 155, width: 27, height: Math.max(value ? 2 : 0, value / max * 155), rx: 5, class: i === 11 ? "chart-bar current" : "chart-bar" });
    const tooltip = document.createElementNS(svg.namespaceURI, "title");
    tooltip.textContent = `${monthLabel(months[i])}: ${format(value)}`; bar.append(tooltip);
    svgNode("text", { x: 28 + i * 52, y: 208, "text-anchor": "middle", class: "chart-axis" }, monthLabel(months[i]));
  });
  const details = element("details", null, "chart-data");
  details.append(uiText("summary", "Ver valores do grÃ¡fico"));
  const table = element("table");
  const head = element("thead"), header = element("tr");
  header.append(uiText("th", "MÃªs"), uiText("th", currency ? "Recebido" : "Assinaturas")); head.append(header);
  const body = element("tbody");
  months.forEach((month, i) => { const row = element("tr"); row.append(element("td", monthLabel(month)), element("td", format(values[i]))); body.append(row); });
  table.append(head, body); details.append(table);
  host.replaceChildren(svg, details);
  if (!values.some(Boolean)) host.prepend(uiText("p", "Nenhum registro neste perÃ­odo.", "chart-empty"));
}

function drawCompositionChart(selector, parts, title) {
  const host = $(selector);
  if (!host) return;
  const total = parts.reduce((sum, [, count]) => sum + count, 0);
  if (!total) {
    host.replaceChildren(uiText("p", "Nenhum registro neste perÃ­odo.", "chart-empty"));
    return;
  }
  const wrap = element("div", null, "finance-breakdown");
  const bar = element("div", null, "finance-breakdown-bar");
  bar.setAttribute("role", "img");
  bar.setAttribute("aria-label", traduzir(title));
  parts.forEach(([label, count, tone]) => {
    if (!count) return;
    const segment = element("span", null, `finance-breakdown-segment finance-breakdown-${tone}`);
    segment.style.width = `${(count / total) * 100}%`;
    segment.title = `${traduzir(label)}: ${count}`;
    segment.setAttribute("aria-label", `${traduzir(label)}: ${count}`);
    bar.append(segment);
  });
  const legend = element("div", null, "finance-breakdown-legend");
  parts.forEach(([label, count, tone]) => {
    const item = element("div", null, "finance-breakdown-item");
    const marker = element("span", null, `finance-breakdown-marker finance-breakdown-${tone}`);
    marker.setAttribute("aria-hidden", "true");
    item.append(marker, element("span", traduzir(label)), element("strong", `${count}`));
    legend.append(item);
  });
  const details = element("details", null, "chart-data");
  details.append(uiText("summary", "Ver valores do grÃ¡fico"));
  const table = element("table");
  const thead = element("thead");
  const header = element("tr");
  header.append(uiText("th", "SituaÃ§Ã£o"), uiText("th", "Total"));
  thead.append(header);
  table.append(thead);
  const body = element("tbody");
  parts.forEach(([label, count]) => {
    const row = element("tr");
    row.append(element("td", traduzir(label)), element("td", count));
    body.append(row);
  });
  table.append(body);
  details.append(table);
  wrap.append(bar, legend, details);
  host.replaceChildren(wrap);
}

async function loadBusiness() {
  const [summary, academies] = await Promise.all([api("/admin/frequency/resumo"), api("/admin/frequency/academias")]);
  businessState.summary = summary; businessState.academies = academies;
  statCards("#business-stats", [["Academias", summary.academias, "building"], ["Assinaturas ativas", summary.assinaturas_ativas, "check"], ["Com aviso de atraso", summary.faturas_em_atraso, "alert"], ["Acesso bloqueado", summary.academias_bloqueadas, "shield"]]);
  fillCurrencies("#business-currency", [...summary.receita_mensal.map((r) => r.moeda), ...summary.faturas_abertas_por_moeda.map((r) => r.moeda)], state.user.moeda);
  renderBusinessMoney();
  drawChart("#business-sales", summary.vendas_mensais || [], "assinaturas", null, "Novas assinaturas");
  const attention = academies.filter((a) => a.aviso || a.bloqueada || ["suspensa", "cancelada"].includes(a.assinatura_status));
  $("#business-attention").replaceChildren(...attention.map((academy) => {
    const row = element("div", null, "attention-row");
    const text = element("div"); text.append(element("strong", academy.academia), element("p", academy.email_dono || "â€”", "muted"));
    row.append(text, badge(academy.bloqueada || ["suspensa", "cancelada"].includes(academy.assinatura_status) ? "Acesso bloqueado" : "Em atraso", "bad"));
    row.append(actionButton("Ver cobranÃ§as", () => { $("#frequency-invoice-search").value = academy.academia; setPage("cobrancas-frequency"); }));
    return row;
  }));
  if (!attention.length) $("#business-attention").append(uiText("p", "Nenhuma pendÃªncia de assinatura para acompanhar.", "list-empty"));
}
function renderBusinessMoney() {
  const data = businessState.summary; if (!data) return;
  const currency = $("#business-currency").value;
  const paid = data.receita_mensal.filter((r) => r.moeda === currency);
  const open = data.faturas_abertas_por_moeda.find((r) => r.moeda === currency);
  statCards("#business-money", [["Recebido neste mÃªs", formatMoney(sumMoney(paid.filter((r) => r.mes === lastMonths(1)[0]), "recebido"), currency), "chart"], ["Total a receber", formatMoney(open?.total || 0, currency), "card"], ["Total vencido", formatMoney(open?.total_atrasado || 0, currency), "alert"]]);
  drawChart("#business-chart", paid, "recebido", currency, "Receita recebida");
}
async function loadFinance() {
  businessState.payments = await api("/pagamentos?filtro=todos");
  fillCurrencies("#finance-currency", businessState.payments.map((r) => r.moeda), state.user.moeda);
  renderFinance();
}
function renderFinance() {
  const currency = $("#finance-currency").value;
  const payments = businessState.payments.filter((p) => p.moeda === currency);
  const paid = payments.filter((p) => p.status === "pago");
  const open = payments.filter((p) => p.status === "em_aberto");
  const overdue = open.filter((p) => p.atrasado);
  const monthly = paid.filter((p) => p.data_pagamento).map((p) => ({ mes: p.data_pagamento.slice(0, 7), moeda: currency, recebido: p.valor }));
  statCards("#finance-stats", [["Recebido neste mÃªs", formatMoney(sumMoney(monthly.filter((r) => r.mes === lastMonths(1)[0]), "recebido"), currency), "chart"], ["Total a receber", formatMoney(sumMoney(open, "valor"), currency), "card"], ["Total vencido", formatMoney(sumMoney(overdue, "valor"), currency), "alert"]]);
  drawChart("#finance-chart", monthly, "recebido", currency, "Receita recebida");
  const composition = [["Pagas", paid.length, "good"], ["Em aberto no prazo", open.length - overdue.length, "warn"], ["Atrasadas", overdue.length, "bad"]];
  drawCompositionChart("#finance-sales", composition, "DistribuiÃ§Ã£o por status");
}

let dialogReturnFocus = null;
function openBusinessDialog(title, description, fields, onSubmit, confirmLabel = "Salvar") {
  const dialog = $("#business-dialog"), form = $("#business-dialog-form");
  dialogReturnFocus = document.activeElement;
  $("#business-dialog-title").textContent = traduzir(title);
  $("#business-dialog-description").textContent = description;
  $("#business-dialog-error").textContent = "";
  $("#business-dialog-fields").replaceChildren(...fields);
  const submit = $("#business-dialog-submit"); submit.textContent = traduzir(confirmLabel); submit.disabled = false;
  form.onsubmit = async (event) => {
    event.preventDefault();
    if (!form.reportValidity() || submit.disabled) return;
    submit.disabled = true;
    try { await onSubmit(formObject(form)); dialog.close(); }
    catch (error) { $("#business-dialog-error").textContent = traduzir(error.message); }
    finally { submit.disabled = false; }
  };
  dialog.showModal();
}
function formField(label, name, options = {}) {
  const wrapper = uiText("label", label);
  const input = element(options.options ? "select" : "input"); input.name = name;
  if (options.options) options.options.forEach(([labelText, value]) => input.append(new Option(traduzir(labelText), value)));
  else { input.type = options.type || "text"; input.maxLength = options.maxLength || 1000; if (options.minLength) input.minLength = options.minLength; }
  for (const attribute of ["min", "max", "step"]) if (options[attribute] !== undefined) input.setAttribute(attribute, options[attribute]);
  input.required = options.required !== false;
  if (options.value !== undefined) input.value = options.value;
  wrapper.append(input); return wrapper;
}
async function loadFrequencyInvoices() {
  const request = ++businessState.invoiceRequest;
  const rows = await api(`/admin/frequency/faturas?status=${encodeURIComponent($("#frequency-invoice-filter").value)}`);
  if (request !== businessState.invoiceRequest) return;
  businessState.invoices = rows; renderFrequencyInvoices();
}
function filteredInvoices() {
  const query = $("#frequency-invoice-search").value.trim().toLocaleLowerCase(interfaceLocale);
  return businessState.invoices.filter((row) => [row.academia, row.referencia].some((value) => String(value || "").toLocaleLowerCase(interfaceLocale).includes(query)));
}
function invoiceStatus(invoice) {
  const overdue = invoice.status === "em_aberto" && invoice.vencimento < localDateKey();
  const labels = { pago: "Pago", em_aberto: "Em aberto", cancelado: "Cancelada", estornado: "Estornada" };
  return badge(overdue ? "Atrasado" : labels[invoice.status] || invoice.status, invoice.status === "pago" ? "good" : overdue ? "bad" : "warn");
}
function localDateKey() { const now = new Date(); return `${now.getFullYear()}-${String(now.getMonth() + 1).padStart(2, "0")}-${String(now.getDate()).padStart(2, "0")}`; }
function renderFrequencyInvoices() {
  const rows = filteredInvoices();
  $("#frequency-invoices-empty").hidden = rows.length > 0;
  $("#frequency-invoices").replaceChildren(...rows.map((invoice) => {
    const row = element("tr"), label = element("td"); label.append(element("strong", invoice.academia), element("small", invoice.referencia, "cell-detail"));
    const status = element("td"); status.append(invoiceStatus(invoice));
    const actions = element("td"), wrap = element("div", null, "table-actions");
    if (invoice.status === "em_aberto" && !state.config.somente_consulta) {
      wrap.append(actionButton("Confirmar recebimento", () => confirmInvoice(invoice), "primary"), actionButton("Cancelar", () => cancelInvoice(invoice)));
    }
    actions.append(wrap);
    row.append(label, element("td", formatDate(invoice.vencimento)), element("td", formatMoney(invoice.valor, invoice.moeda)), status, actions); return row;
  }));
}
function confirmInvoice(invoice) {
  const fields = [formField("Meio de pagamento", "meio_pagamento", { options: [["QR", "QR"], ["TransferÃªncia", "transferencia"], ["Dinheiro", "dinheiro"], ["Outro", "outro"]] }), formField("ReferÃªncia do pagamento", "referencia_pagamento", { required: false, maxLength: 160 }), formField("ObservaÃ§Ã£o", "observacao_admin", { required: false, maxLength: 1000 })];
  const checked = element("label", null, "check-label"); const checkbox = element("input"); checkbox.type = "checkbox"; checkbox.required = true;
  checked.append(checkbox, uiText("span", "Conferi o recebimento deste valor no banco ou caixa.")); fields.push(checked);
  openBusinessDialog("Confirmar recebimento", `${invoice.academia} Â· ${formatMoney(invoice.valor, invoice.moeda)} Â· ${traduzir("Vencimento")}: ${formatDate(invoice.vencimento)}. ${traduzir("A confirmaÃ§Ã£o gera a prÃ³xima fatura da assinatura ativa.")}`, fields, async (data) => {
    await api(`/admin/frequency/faturas/${invoice.id}/pagar`, { method: "PATCH", body: data });
    showNotice("Recebimento confirmado."); await loadFrequencyInvoices();
  }, "Confirmar recebimento");
}
function cancelInvoice(invoice) {
  openBusinessDialog("Cancelar cobranÃ§a", `${invoice.academia} Â· ${formatMoney(invoice.valor, invoice.moeda)}`, [formField("Motivo do cancelamento", "observacao_admin", { minLength: 3 })], async (data) => {
    await api(`/admin/frequency/faturas/${invoice.id}/cancelar`, { method: "PATCH", body: data });
    showNotice("CobranÃ§a cancelada."); await loadFrequencyInvoices();
  }, "Cancelar cobranÃ§a");
}
async function loadFrequencyAudit() {
  const rows = await api("/admin/frequency/auditoria?limite=100");
  const actions = { fatura_paga: "Recebimento confirmado", fatura_cancelada: "CobranÃ§a cancelada", plano_criado: "Pacote criado", assinatura_criada: "Assinatura criada", qr_atualizado: "QR atualizado", qr_removido: "QR removido", contato_atualizado: "Contato atualizado", assinatura_status_alterado: "SituaÃ§Ã£o da assinatura alterada", plano_status_alterado: "SituaÃ§Ã£o do pacote alterada", fatura_recorrente_criada: "PrÃ³xima fatura criada" };
  $("#frequency-audit").replaceChildren(...rows.map((row) => {
    const item = element("div", null, "audit-row"); item.append(uiText("strong", actions[row.acao] || row.acao.replaceAll("_", " ")), element("span", `${row.administrador || "â€”"} Â· ${formatDate(row.criado_em)} Â· #${row.entidade_id || row.id}`)); return item;
  }));
  if (!rows.length) $("#frequency-audit").append(uiText("p", "Nenhuma alteraÃ§Ã£o registrada.", "list-empty"));
}
function csvCell(value) { const text = String(value ?? ""); return `"${(/^[\s]*[=+\-@]/.test(text) ? "'" : "") + text.replaceAll('"', '""')}"`; }
function exportInvoices() {
  const rows = filteredInvoices();
  const values = [["ID", "Academia", "ReferÃªncia", "Vencimento", "Moeda", "Valor", "Status"], ...rows.map((r) => [r.id, r.academia, r.referencia, r.vencimento, r.moeda, r.valor, r.status])];
  const blob = new Blob(["\uFEFF" + values.map((r) => r.map(csvCell).join(";")).join("\r\n")], { type: "text/csv;charset=utf-8" });
  const url = URL.createObjectURL(blob), anchor = element("a"); anchor.href = url; anchor.download = `frequency-faturas-${localDateKey()}.csv`; anchor.click(); setTimeout(() => URL.revokeObjectURL(url), 1000);
}

async function loadFrequencyPlans() {
  const [plans, academies] = await Promise.all([api("/admin/frequency/planos"), api("/admin/frequency/academias")]);
  businessState.plans = plans; businessState.academies = academies;
  $("#frequency-plans").replaceChildren(...plans.map((plan) => {
    const card = element("article", null, "plan-card"); card.append(element("h2", plan.nome), element("p", plan.descricao, "muted"), element("p", formatMoney(plan.valor, plan.moeda), "plan-price"), element("p", `${plan.duracao_dias} ${traduzir("dias")}`, "plan-duration"), element("p", `Categoria ${plan.nivel} Â· CÃ¢meras ${plan.cameras ? "incluÃ­das" : "nÃ£o incluÃ­das"} Â· YouTube ${plan.youtube ? "incluÃ­do" : "nÃ£o incluÃ­do"}`), badge(plan.ativo ? "Ativo" : "Inativo", plan.ativo ? "good" : "warn"));
    if (!state.config.somente_consulta) card.append(actionButton("Editar pacote", () => editPackage(plan)));
    if (!state.config.somente_consulta) card.append(actionButton(plan.ativo ? "Desativar novas assinaturas" : "Ativar pacote", async () => {
      await api(`/admin/frequency/planos/${plan.id}/status`, { method: "PATCH", body: { ativo: !plan.ativo } }); await loadFrequencyPlans();
    })); return card;
  }));
  if (!plans.length) $("#frequency-plans").append(uiText("p", "Nenhum pacote cadastrado. Defina seus preÃ§os para comeÃ§ar.", "list-empty"));
  $("#subscription-plan").replaceChildren(new Option(traduzir("Selecione um pacote"), ""), ...plans.filter((p) => p.ativo).map((p) => new Option(`${p.nome} Â· ${formatMoney(p.valor, p.moeda)}`, p.id)));
  $("#subscription-academy").replaceChildren(new Option(traduzir("Selecione uma academia"), ""), ...academies.filter((a) => !a.assinatura_id && a.academia_ativa).map((a) => new Option(a.academia, a.academia_id)));
  $("#frequency-subscriptions").replaceChildren(...academies.map((academy) => {
    const row = element("tr"), status = element("td"), actions = element("td");
    status.append(badge(academy.assinatura_status ? ({ ativa: "Ativa", suspensa: "Suspensa", cancelada: "Cancelada" }[academy.assinatura_status]) : "Sem assinatura", academy.assinatura_status === "ativa" && !academy.bloqueada ? "good" : "warn"));
    if (academy.assinatura_id && !state.config.somente_consulta) actions.append(actionButton(academy.assinatura_status === "ativa" ? "Suspender" : "Reativar", () => {
      const next = academy.assinatura_status === "ativa" ? "suspensa" : "ativa";
      openBusinessDialog(next === "suspensa" ? "Suspender assinatura" : "Reativar assinatura", `${academy.academia}. ${traduzir(next === "suspensa" ? "A suspensÃ£o bloqueia o sistema e a catraca. As faturas continuam registradas." : "O bloqueio por atraso permanece se houver fatura vencida hÃ¡ 5 dias.")}`, [], async () => {
        await api(`/admin/frequency/assinaturas/${academy.assinatura_id}/status`, { method: "PATCH", body: { status: next } }); await loadFrequencyPlans();
      }, "Confirmar");
    }));
    row.append(element("td", academy.academia), element("td", academy.plano || "â€”"), status, element("td", formatDate(academy.proximo_vencimento)), actions); return row;
  }));
}
function editPackage(plan) {
  const fields = [formField("Nome", "nome", { value: plan.nome, maxLength: 100 }),
    formField("DescriÃ§Ã£o", "descricao", { value: plan.descricao, required: false }),
    formField("Valor", "valor", { type: "number", value: plan.valor, min: "0.01", step: "0.01" }),
    formField("Moeda", "moeda", { value: plan.moeda, options: ["BRL", "BOB", "USD", "EUR", "GBP", "CNY", "INR"].map(x => [x, x]) }),
    formField("DuraÃ§Ã£o em dias", "duracao_dias", { type: "number", value: plan.duracao_dias, min: 1, max: 3660 }),
    formField("Categoria", "nivel", { value: plan.nivel, options: [["Essencial", "essencial"], ["Profissional", "profissional"], ["Premium", "premium"]] }),
    formField("CÃ¢meras", "cameras", { value: String(plan.cameras), options: [["NÃ£o incluÃ­das", "false"], ["IncluÃ­das no Premium", "true"]] }),
    formField("YouTube", "youtube", { value: String(plan.youtube), options: [["NÃ£o incluÃ­do", "false"], ["IncluÃ­do no Premium", "true"]] })];
  openBusinessDialog("Editar pacote", "Os recursos mudam para os assinantes deste pacote; faturas jÃ¡ emitidas mantÃªm seus valores.", fields, async values => {
    await api(`/admin/frequency/planos/${plan.id}`, { method: "PATCH", body: { ...values, duracao_dias: Number(values.duracao_dias), cameras: values.cameras === "true", youtube: values.youtube === "true" } });
    await loadFrequencyPlans(); showNotice("Pacote atualizado.");
  });
}
async function privateImage(path, imageSelector, emptySelector, key) {
  const image = $(imageSelector), empty = $(emptySelector);
  image.hidden = true; image.removeAttribute("src"); empty.hidden = true;
  const generation = Symbol(); businessState.imageUrls.get(key)?.revoke?.();
  businessState.imageUrls.set(key, { generation });
  const response = await fetchFrequency(path, { cache: "no-store", headers: { Authorization: `Bearer ${state.token}` } });
  if (response.status === 401) { endSession("Sua sessÃ£o expirou. Entre novamente."); throw new Error(traduzir("SessÃ£o encerrada.")); }
  if (businessState.imageUrls.get(key)?.generation !== generation) return false;
  if (response.status === 404) { empty.hidden = false; return false; }
  if (!response.ok) { const data = await response.json().catch(() => ({})); throw new Error(apiMessage(data.detail)); }
  const blob = await response.blob();
  if (businessState.imageUrls.get(key)?.generation !== generation || !state.token) return false;
  const url = URL.createObjectURL(blob); businessState.imageUrls.set(key, { generation, revoke: () => URL.revokeObjectURL(url) });
  image.src = url; image.hidden = false; return true;
}
async function loadPlatformQr() {
  $("#platform-qr-remove").hidden = true;
  const exists = await privateImage(`/admin/frequency/qr/${encodeURIComponent($("#platform-qr-currency").value)}`, "#platform-qr-image", "#platform-qr-empty", "platform-qr");
  $("#platform-qr-remove").hidden = !exists || state.config.somente_consulta;
}
async function loadPlatformSettings() {
  const data = await api("/admin/frequency/configuracao");
  const form = $("#frequency-contact-form"); form.elements.contato_email.value = data.contato_email || ""; form.elements.contato_telefone.value = data.contato_telefone || "";
  await loadPlatformQr();
}
function renderSubscriptionBanner() {
  const user = state.user || {}, banner = $("#subscription-banner");
  banner.hidden = !user.aviso_frequency && !user.bloqueada_frequency;
  banner.classList.toggle("blocked", Boolean(user.bloqueada_frequency));
  $("#subscription-banner-title").textContent = traduzir(user.bloqueada_frequency ? "Acesso bloqueado" : "Sua assinatura precisa de atenÃ§Ã£o");
  $("#subscription-banner-copy").textContent = traduzir(user.bloqueada_frequency ? "Entre em contato com o administrador do sistema para regularizar a assinatura." : "HÃ¡ uma cobranÃ§a Frequency em atraso. Regularize para evitar o bloqueio do sistema e da catraca.");
  $$('[data-page]').forEach((button) => { button.disabled = Boolean(user.bloqueada_frequency) && !["assinatura", "preferencias"].includes(button.dataset.page); });
}
async function loadOwnerSubscription() {
  const freshUser = await api("/eu"); Object.assign(state.user, freshUser, { idioma: interfaceLocale }); renderSubscriptionBanner();
  const box = $("#owner-subscription-state");
  $("#owner-billing-content").hidden = true;
  box.classList.toggle("blocked", Boolean(freshUser.bloqueada_frequency));
  box.replaceChildren(icon(freshUser.bloqueada_frequency ? "shield" : "check"), uiText("h2", freshUser.bloqueada_frequency ? "Acesso bloqueado" : freshUser.aviso_frequency ? "Sua assinatura precisa de atenÃ§Ã£o" : "Consulte sua assinatura"));
  if (state.user.papel === "recepcao") { box.append(uiText("p", "Procure o dono da academia para consultar ou regularizar a assinatura do Frequency.")); return; }
  const data = await api("/assinatura-frequency");
  Object.assign(state.user, { bloqueada_frequency: data.bloqueada_frequency, aviso_frequency: data.aviso_frequency }); renderSubscriptionBanner();
  box.append(uiText("p", data.bloqueada_frequency ? "Entre em contato com o administrador do sistema para regularizar a assinatura." : data.assinatura ? "Acompanhe abaixo os dados da sua assinatura." : "Nenhuma assinatura vinculada. Fale com o administrador do sistema."));
  $("#owner-billing-content").hidden = false;
  const invoice = data.fatura_atual, summary = $("#owner-invoice-summary"); summary.replaceChildren();
  const paymentActions = $("#owner-payment-actions"); paymentActions.replaceChildren();
  if (invoice) {
    summary.append(element("p", formatMoney(invoice.valor, invoice.moeda), "invoice-amount"), element("p", `${traduzir("Vencimento")}: ${formatDate(invoice.vencimento)}`), invoiceStatus(invoice));
    const payButton = element("button", traduzir("Pagar online"), "button button-primary");
    payButton.type = "button";
    payButton.addEventListener("click", () => openBusinessDialog(
      "Pagar assinatura Frequency",
      traduzir("Informe seu documento para abrir o checkout seguro do provedor."),
      [formField("Documento do pagador", "documento", { minLength: 5, maxLength: 20 })],
      async values => {
        const checkout = await api("/assinatura-frequency/checkout", { method: "POST", body: { documento: values.documento.trim() } });
        window.location.assign(checkout.checkout_url);
      },
      "Continuar para pagamento",
    ));
    paymentActions.append(payButton);
  }
  else summary.append(uiText("p", "Nenhuma cobranÃ§a em aberto.", "muted"));
  if (invoice) await privateImage("/assinatura-frequency/qr", "#owner-frequency-qr", "#owner-frequency-qr-empty", "owner-qr");
  else { $("#owner-frequency-qr").hidden = true; $("#owner-frequency-qr-empty").hidden = true; }
  const contact = $("#owner-frequency-contact"); contact.replaceChildren();
  const adminEmail = data.contato?.contato_email || "contato@exemplo.invalid";
  const adminPhone = data.contato?.contato_telefone || "";
  contact.append(element("p", adminEmail), element("p", adminPhone));
  if (invoice) {
    const message = `OlÃ¡, enviei o comprovante da fatura Frequency ${invoice.referencia || invoice.id}. Academia: ${state.user?.academia_nome || ""}.`;
    const whatsapp = element("a", traduzir("Enviar comprovante pelo WhatsApp"), "button button-secondary button-small");
    whatsapp.href = `https://wa.me/${adminPhone.replace(/\\D/g, "")}?text=${encodeURIComponent(message)}`;
    whatsapp.target = "_blank"; whatsapp.rel = "noopener noreferrer";
    contact.append(whatsapp);
  }
  if (invoice) {
    const note = $("#owner-frequency-qr-empty");
    if (!note.hidden) note.textContent = traduzir("O administrador ainda nÃ£o cadastrou um QR para esta moeda.");
    const steps = element("ol", null, "payment-steps");
    steps.append(element("li", traduzir("Escaneie o QR e faÃ§a o depÃ³sito do valor exibido.")), element("li", traduzir("Guarde o comprovante.")), element("li", traduzir("Envie o comprovante pelo WhatsApp ao administrador.")));
    $("#owner-frequency-qr")?.parentElement?.append(steps);
  }
  $("#owner-frequency-invoices").replaceChildren(...data.faturas.map((f) => { const row = element("tr"), status = element("td"); status.append(invoiceStatus(f)); row.append(element("td", f.referencia), element("td", formatDate(f.vencimento)), element("td", formatMoney(f.valor, f.moeda)), status); return row; }));
}
function loadPreferences() {
  fetch("/academia/preferencias", { headers: { Authorization: `Bearer ${state.token}` }, cache: "no-store" })
    .then(async response => { if (!response.ok) throw new Error(apiMessage((await response.json().catch(() => ({}))).detail)); return response.json(); })
    .then(data => {
      const form = $("#academy-preferences-form");
      form.elements.pais.value = data.pais;
      for (const field of ["cidade", "estado", "endereco", "codigo_postal"]) form.elements[field].value = data[field] || "";
      $("#preferences-country-summary").replaceChildren(element("strong", data.pais), element("p", `${traduzir("Moeda")}: ${data.moeda}`));
    }).catch(error => showNotice(error.message, true));
  $("#preference-language").value = interfaceLocale;
  $("#language-save-state").textContent = traduzir("PreferÃªncia de idioma salva somente neste navegador.");
}
function clearBusinessSession() {
  businessState.imageUrls.forEach((entry) => entry.revoke?.()); businessState.imageUrls.clear();
  businessState.invoices = []; businessState.payments = []; businessState.plans = []; businessState.academies = []; businessState.summary = null; businessState.invoiceRequest++;
  if ($("#business-dialog")?.open) $("#business-dialog").close();
}
function initBusinessUI() {
  $$("[data-go]").forEach((button) => { if (button.dataset.go !== "alunos") button.addEventListener("click", () => setPage(button.dataset.go)); });
  $$("[data-refresh-business]").forEach((button) => button.addEventListener("click", () => setPage("negocio")));
  $("#business-currency").addEventListener("change", renderBusinessMoney);
  $("#finance-currency").addEventListener("change", renderFinance);
  $("#refresh-finance").addEventListener("click", () => setPage("financeiro"));
  $("#frequency-invoice-filter").addEventListener("change", () => setPage("cobrancas-frequency"));
  $("#frequency-invoice-search").addEventListener("input", renderFrequencyInvoices);
  $("#export-frequency-invoices").addEventListener("click", exportInvoices);
  $(".audit-panel").addEventListener("toggle", (event) => { if (event.currentTarget.open) loadFrequencyAudit().catch((error) => showNotice(error.message, true)); });
  $$("[data-package-template]").forEach((button) => button.addEventListener("click", () => {
    $("#package-create").open = true; const form = $("#frequency-plan-form"); form.elements.nome.value = button.dataset.packageTemplate; form.elements.valor.focus();
    if (form.elements.nivel) form.elements.nivel.value = button.dataset.packageTemplate.toLowerCase();
    $("#package-extras").disabled = form.elements.nivel?.value !== "premium";
  }));
  $("#package-level").addEventListener("change", event => { $("#package-extras").disabled = event.target.value !== "premium"; });
  bindForm("#academy-preferences-form", async (_form, values) => {
    const response = await fetch("/academia/preferencias", { method: "PATCH", headers: { Authorization: `Bearer ${state.token}`, "Content-Type": "application/json" }, body: JSON.stringify(Object.fromEntries(["pais", "cidade", "estado", "endereco", "codigo_postal"].map(key => [key, values[key].trim()]))) });
    const data = await response.json().catch(() => ({}));
    if (!response.ok) throw new Error(apiMessage(data.detail));
    state.user.pais = data.pais; state.user.moeda = data.moeda;
    $("#plan-value-label").textContent = `${traduzir("Valor")} (${data.moeda}) *`;
    showNotice("LocalizaÃ§Ã£o salva. A moeda vale para novos planos e cobranÃ§as; os registros existentes sÃ£o preservados."); loadPreferences();
  });
  bindForm("#frequency-plan-form", async (form, values) => {
    await api("/admin/frequency/planos", { method: "POST", body: { nome: values.nome.trim(), descricao: values.descricao.trim(), valor: values.valor, moeda: values.moeda, duracao_dias: Number(values.duracao_dias), nivel: values.nivel, cameras: form.elements.cameras.checked, youtube: form.elements.youtube.checked } }); form.reset(); $("#package-extras").disabled = true; showNotice("Pacote criado."); await loadFrequencyPlans();
  });
  bindForm("#frequency-subscription-form", async (form, values) => {
    await api("/admin/frequency/assinaturas", { method: "POST", body: { academia_id: Number(values.academia_id), plano_id: Number(values.plano_id), vencimento: values.vencimento } }); form.reset(); showNotice("Assinatura criada."); await loadFrequencyPlans();
  });
  $("#platform-qr-currency").addEventListener("change", () => loadPlatformQr().catch((error) => showNotice(error.message, true)));
  $("#platform-qr-file").addEventListener("change", async (event) => {
    const input = event.currentTarget, file = input.files?.[0]; if (!file) return;
    if (!["image/png", "image/jpeg", "image/webp"].includes(file.type) || file.size > 2 * 1024 * 1024) { showNotice("Envie uma imagem PNG, JPG ou WebP de atÃ© 2 MB.", true); input.value = ""; return; }
    const currency = $("#platform-qr-currency"); currency.disabled = true;
    await busyAction(input, async () => {
      await api(`/admin/frequency/qr/${encodeURIComponent(currency.value)}`, { method: "PUT", headers: { "Content-Type": file.type }, body: file }); showNotice("QR atualizado."); await loadPlatformQr();
    }); input.value = ""; currency.disabled = false;
  });
  $("#platform-qr-remove").addEventListener("click", () => {
    const currency = $("#platform-qr-currency").value;
    openBusinessDialog("Remover QR", `${traduzir("Moeda")}: ${currency}`, [], async () => { await api(`/admin/frequency/qr/${encodeURIComponent(currency)}`, { method: "DELETE" }); await loadPlatformQr(); showNotice("QR removido."); }, "Remover QR");
  });
  bindForm("#frequency-contact-form", async (_form, values) => { await api("/admin/frequency/configuracao", { method: "PUT", body: { contato_email: values.contato_email.trim() || null, contato_telefone: values.contato_telefone.trim() || null } }); showNotice("Contato atualizado."); });
  $("#refresh-subscription").addEventListener("click", () => setPage("assinatura"));
  $("#business-dialog-cancel").addEventListener("click", () => $("#business-dialog").close());
  $("#business-dialog").addEventListener("close", () => dialogReturnFocus?.focus());
  ["#login-language", "#app-language", "#preference-language"].forEach((selector) => $(selector).addEventListener("change", (event) => setInterfaceLanguage(event.target.value)));
}


const SALES_WHATSAPP = ""; // defina o numero comercial do negocio (formato 591XXXXXXXX)

// Modo de teste: simula internet indisponível sem desligar a rede do computador.
// Ative com ?teste_offline=1 e desative com ?teste_offline=0.
const offlineTestStorageKey = "frequency.test_offline";
const offlineTestParam = new URLSearchParams(window.location.search).get("teste_offline");
if (offlineTestParam === "1") localStorage.setItem(offlineTestStorageKey, "1");
if (offlineTestParam === "0") localStorage.removeItem(offlineTestStorageKey);
const offlineTestMode = localStorage.getItem(offlineTestStorageKey) === "1";
function isOfflineTestMode() { return offlineTestMode; }
const tokenStorageKey = "frequency.access_token";
const state = { token: null, user: null, students: [], plans: [], platformAcademies: [], prospectingLeads: [], prospectingConfig: null, prospectingImageUrl: null, config: { somente_consulta: false }, qrPreviewUrl: null, monitorLogoPreviewUrl: null, academyLogoPreviewUrl: null, editingStudentId: null, studentEditRequestId: 0, studentPhotoBlob: null, studentPhotoPreviewUrl: null, studentCameraStream: null, studentFaceSamples: [], studentFacePreviewUrls: [], studentEditPhotoBlob: null, studentEditPhotoPreviewUrl: null, studentEditCameraStream: null, backupDirectoryHandle: null };
let backupConfig = null;
function detectFrequencyDeviceClass() {
  const userAgent = typeof navigator === "undefined" ? "" : navigator.userAgent || "";
  const platform = typeof navigator === "undefined" ? "" : navigator.platform || "";
  const touchPoints = typeof navigator === "undefined" ? 0 : Number(navigator.maxTouchPoints || 0);
  const ipad = /iPad/i.test(userAgent) || (platform === "MacIntel" && touchPoints > 1);
  if (ipad || (/Android/i.test(userAgent) && !/Mobile/i.test(userAgent))) return "tablet";
  if (/Android|iPhone|iPod|Windows Phone|Mobile/i.test(userAgent)) return "mobile";
  return "desktop";
}

const frequencyDeviceClass = detectFrequencyDeviceClass();

function isTouchOnlyDevice() {
  const touchPoints = Number(navigator?.maxTouchPoints || 0);
  const coarsePointer = typeof window.matchMedia === "function" && window.matchMedia("(pointer: coarse)").matches;
  return touchPoints > 0 && coarsePointer;
}

function browserDirectoryPickerAvailable() {
  return typeof window.showDirectoryPicker === "function";
}

function renderBackupDevicePolicy() {
  const notice = $("#backup-device-notice");
  const navButton = $('[data-page="backup"]');
  const downloadButton = $("#backup-download-latest");
  const mobileDevice = frequencyDeviceClass !== "desktop";
  if (downloadButton?.querySelector("span")) downloadButton.querySelector("span").textContent = traduzir(mobileDevice ? "Salvar no dispositivo" : "Baixar última cópia");
  if (navButton) navButton.title = "";
  if (!notice) return;
  notice.hidden = false;
  notice.textContent = mobileDevice
    ? traduzir("Toque em Salvar no dispositivo. No iPhone escolha Salvar em Arquivos; no Android escolha Files, Downloads ou Google Drive.")
    : traduzir("A cópia fica na pasta configurada pelo computador que hospeda o Frequency; você também pode baixá-la para este dispositivo.");
}

Object.assign(state, { facialEvents: [], facialLastId: null, facialTimer: null, facialNoticeTimer: null, facialGeneration: 0, facialCooldowns: new Map() });
const FACIAL_NOTIFICATION_DURATION_MS = 3000;
const FACIAL_REPEAT_COOLDOWN_MS = 10000;

function renderFacialEvents() {
  const panel = $(".facial-notifications");
  const count = state.facialEvents.length;
  $("#facial-count").textContent = String(count);
  panel?.classList?.toggle("has-events", count > 0);
  $("#facial-empty").textContent = traduzir("Nenhum acesso facial novo nesta sessão.");
  $("#facial-empty").hidden = count > 0;
  $("#facial-events").replaceChildren(...state.facialEvents.map((event) => {
    const card = element(event.aluno_id ? "button" : "div", null, `facial-event ${event.liberado ? "facial-allowed" : "facial-blocked"}`);
    if (event.aluno_id) { card.type = "button"; card.dataset.studentId = event.aluno_id; }
    card.append(element("strong", `${event.liberado ? "✓" : "✕"} ${traduzir(event.liberado ? "Liberado" : "Bloqueado")}`));
    card.append(element("span", event.nome_aluno || traduzir("Rosto não identificado")));
    const date = new Date(event.data_hora);
    card.append(element("small", Number.isNaN(date.getTime()) ? "—" : new Intl.DateTimeFormat(interfaceLocale, { dateStyle: "short", timeStyle: "medium" }).format(date)));
    return card;
  }));
}

function stopFacialEvents() {
  clearTimeout(state.facialTimer);
  clearTimeout(state.facialNoticeTimer);
  state.facialTimer = null;
  state.facialNoticeTimer = null;
  state.facialGeneration += 1;
  state.facialEvents = [];
  state.facialLastId = null;
  state.facialCooldowns = new Map();
  renderFacialEvents();
}

function startFacialEvents() {
  stopFacialEvents();
  if (!["dono", "recepcao"].includes(state.user?.papel) || state.user.bloqueada_frequency) return;
  const generation = state.facialGeneration;
  const poll = async () => {
    let hasFacialRows = false;
    try {
      const baseline = state.facialLastId === null;
      const rows = await api(baseline ? "/presencas?limite=1" : `/presencas?limite=100&depois=${state.facialLastId}`);
      if (generation !== state.facialGeneration) return;
      state.facialLastId = Math.max(state.facialLastId || 0, ...rows.map((row) => row.id));
      if (!baseline) {
        const now = Date.now();
        const facialRows = rows.filter((row) => row.metodo_identificacao === "facial").reverse().filter((row) => {
          const key = `${row.aluno_id || row.nome_aluno || "desconhecido"}:${row.liberado ? "liberado" : "bloqueado"}`;
          const last = state.facialCooldowns.get(key) || 0;
          if (now - last < FACIAL_REPEAT_COOLDOWN_MS) return false;
          state.facialCooldowns.set(key, now);
          return true;
        });
        if (facialRows.length) {
          state.facialEvents = facialRows.slice(0, 8);
          renderFacialEvents();
          clearTimeout(state.facialNoticeTimer);
          hasFacialRows = true;
        }
      }
    } catch (_) { /* Retry without changing the cursor or interrupting the active page. */ }
    if (generation === state.facialGeneration) {
      state.facialTimer = setTimeout(poll, 2500);
      if (hasFacialRows) state.facialNoticeTimer = setTimeout(() => {
        if (generation !== state.facialGeneration) return;
        state.facialEvents = [];
        state.facialNoticeTimer = null;
        renderFacialEvents();
      }, FACIAL_NOTIFICATION_DURATION_MS);
    }
  };
  void poll();
}
let interfaceLocale = window.FrequencyI18n?.initialLocale() || "pt-BR";

const $ = (selector, root = document) => root.querySelector(selector);
const $$ = (selector, root = document) => Array.from(root.querySelectorAll(selector));

const featureUrls = { cameras: "/cameras", youtube: "/youtube" };
const featureFrames = { cameras: "#feature-frame-cameras", youtube: "#feature-frame-youtube" };
function prepareFeatureFrames(user) {
  for (const feature of Object.keys(featureUrls)) {
    if (user.papel === "dono" && user.recursos_frequency?.[feature]) {
      const frame = $(featureFrames[feature]);
      if (frame && !frame.src) frame.src = `${featureUrls[feature]}?locale=${encodeURIComponent(interfaceLocale)}`;
    }
  }
}
function syncFeatureLocale() {
  $$('[id^="feature-frame-"]').forEach((frame) => frame.contentWindow?.postMessage({ type: "frequency-locale", locale: interfaceLocale }, location.origin));
}

const roleNames = {
  admin_plataforma: "Administrador da plataforma",
  dono: "Dono da academia",
  recepcao: "Recepção",
  professor: "Professor",
};

const statusLabels = {
  ativo: "Ativo",
  inativo: "Inativo",
  em_aberto: "Em aberto",
  pago: "Pago",
  em_dia: "Em dia",
  atrasado: "Atrasado",
  vence_em_breve: "Vence em breve",
};

const traducoesEs = {
  "Frequency — gestão da academia": "Frequency — gestión del gimnasio",
  "GESTÃO QUE ACOMPANHA O SEU RITMO": "GESTIÓN A SU RITMO",
  "Mais tempo para o que move você.": "Más tiempo para lo que te mueve.",
  "Alunos, mensalidades e acessos da sua academia em um só lugar.": "Alumnos, mensualidades y accesos de tu gimnasio en un solo lugar.",
  "TREINO · GESTÃO · EVOLUÇÃO": "ENTRENAMIENTO · GESTIÓN · EVOLUCIÓN",
  "ÁREA DA ACADEMIA": "ÁREA DEL GIMNASIO",
  "Bem-vindo de volta": "Te damos la bienvenida",
  "Entre com seu e-mail e senha para continuar.": "Ingresa tu correo y contraseña para continuar.",
  "E-mail": "Correo electrónico",
  "E-mail *": "Correo electrónico *",
  "Senha": "Contraseña",
  "Entrar": "Ingresar",
  "Acesso reservado à equipe da academia.": "Acceso reservado al equipo del gimnasio.",
  "Consulta na nuvem": "Consulta en la nube",
  "Sair": "Salir",
  "MENU": "MENÚ",
  "Visão geral": "Resumen",
  "Alunos": "Alumnos",
  "Pagamentos": "Pagos",
  "Acessos": "Accesos",
  "Planos": "Planes",
  "Equipe": "Equipo",
  "Tela do aluno": "Pantalla del alumno",
  "Telas do aluno": "Pantallas del alumno",
  "EXPERIÊNCIA NA ENTRADA": "EXPERIENCIA DE ACCESO",
  "Configure o segundo monitor, o som de acesso e a identidade visual da academia.": "Configura el segundo monitor, el sonido de acceso y la identidad visual del gimnasio.",
  "Cada tela tem seu próprio código e câmera. Conecte somente a quantidade permitida pelo plano.": "Cada pantalla tiene su propio código y cámara. Conecta solo la cantidad permitida por tu plan.",
  "Abrir segunda tela": "Abrir segunda pantalla",
  "Abrir uma tela": "Abrir una pantalla",
  "Conectar telas individualmente": "Conectar pantallas individualmente",
  "Crie um código para cada janela. No computador da tela, abra /monitor, informe o código correspondente e ative a câmera daquele computador.": "Crea un código para cada ventana. En el equipo de la pantalla, abre /monitor, introduce el código correspondiente y activa la cámara de ese equipo.",
  "Adicionar tela": "Añadir pantalla",
  "Verificando telas e limite do plano…": "Comprobando pantallas y límite del plan…",
  "Conectar o monitor": "Conectar el monitor",
  "Gere um código e informe-o somente no computador ligado ao monitor da entrada. O código libera apenas a tela de resultado; não dá acesso ao painel nem ao histórico.": "Genera un código e introdúcelo solo en el equipo conectado al monitor de entrada. El código solo permite ver el resultado; no da acceso al panel ni al historial.",
  "Verificando configuração…": "Verificando la configuración…",
  "Gerar ou renovar código": "Generar o renovar código",
  "Código da tela": "Código de pantalla",
  "Copiar código": "Copiar código",
  "Logo da academia": "Logo del gimnasio",
  "A imagem será exibida na segunda tela. Ela fica nesta instalação e pode ser trocada ou removida.": "La imagen se mostrará en la segunda pantalla. Se guarda en esta instalación y se puede cambiar o quitar.",
  "Sua logo aparece aqui": "Tu logo aparece aquí",
  "Escolher logo": "Elegir logo",
  "Remover logo": "Quitar logo",
  "O que aparece para o aluno": "Lo que ve el alumno",
  "Som curto e claro quando a entrada é liberada; tom diferente quando é recusada.": "Un sonido breve y claro cuando se autoriza el acceso; otro tono cuando se deniega.",
  "Ícone e mensagem grandes, com bom contraste, que desaparecem automaticamente.": "Un icono y un mensaje grandes, con buen contraste, que desaparecen automáticamente.",
  "Nome abreviado e foto opcional; documento, telefone e histórico não aparecem.": "Nombre abreviado y foto opcional; no se muestra documento, teléfono ni historial.",
  "Ative o som uma vez no próprio monitor. Navegadores exigem esse toque antes de permitir áudio.": "Activa el sonido una vez en el propio monitor. Los navegadores requieren ese toque antes de permitir audio.",
  "Telas conectadas neste plano.": "Pantallas conectadas en este plan.",
  "Código compartilhado ativo. Cada nova janela recebe um número do plano.": "Código compartido activo. Cada nueva ventana recibe un número del plan.",
  "Nenhum código compartilhado criado ainda.": "Todavía no hay un código compartido.",
  "Nenhuma tela conectada ainda.": "Todavía no hay pantallas conectadas.",
  "Tela": "Pantalla",
  "Código compartilhado": "Código compartido",
  "Use este mesmo código em todas as telas.": "Usa este mismo código en todas las pantallas.",
  "Já existe um código compartilhado. Use o mesmo código nas outras telas.": "Ya existe un código compartido. Usa el mismo código en las otras pantallas.",
  "Código compartilhado gerado. Use-o em todas as telas.": "Código compartido generado. Úsalo en todas las pantallas.",
  "Abrir tela": "Abrir pantalla",
  "Desconectar": "Desconectar",
  "Nome desta tela (por exemplo, Recepção):": "Nombre de esta pantalla (por ejemplo, Recepción):",
  "Código compartilhado ativo. Ele permanece visível até você gerar outro ou desconectar.": "El código compartido permanece visible hasta que generes otro.",
  "Desconectar esta tela? Ela deixará de receber novos acessos.": "¿Desconectar esta pantalla? Dejará de recibir nuevos accesos.",
  "Tela desconectada.": "Pantalla desconectada.",
  "Academias": "Gimnasios",
  "Gestão da academia": "Gestión del gimnasio",
  "RESUMO": "RESUMEN",
  "Acompanhe a situação dos alunos da sua academia.": "Consulta la situación de los alumnos de tu gimnasio.",
  "Ver alunos": "Ver alumnos",
  "Situação dos alunos": "Situación de los alumnos",
  "Informações de vencimento e alertas.": "Información de vencimientos y alertas.",
  "Atualizar": "Actualizar",
  "Carregando…": "Cargando…",
  "CADASTRO": "REGISTRO",
  "Consulte os alunos e cadastre novas matrículas.": "Consulta a los alumnos y registra nuevas matrículas.",
  "Novo aluno": "Nuevo alumno",
  "Os campos com * são obrigatórios.": "Los campos con * son obligatorios.",
  "Cancelar": "Cancelar",
  "Nome *": "Nombre *",
  "Documento *": "Documento *",
  "Telefone": "Teléfono",
  "Data de nascimento": "Fecha de nacimiento",
  "Plano": "Plan",
  "Sem plano": "Sin plan",
  "Identificador da biometria": "Identificador biométrico",
  "Salvar aluno": "Guardar alumno",
  "Editar": "Editar",
  "Editar dados do aluno": "Editar datos del alumno",
  "Documento, telefone e nascimento. Plano, cobranças e biometria não serão alterados.": "Documento, teléfono y fecha de nacimiento. No se modificarán el plan, los cobros ni la biometría.",
  "Salvar alterações": "Guardar cambios",
  "Foto do aluno (opcional)": "Foto del alumno (opcional)",
  "Só registre uma imagem com autorização da pessoa.": "Registra una imagen solo con autorización de la persona.",
  "Prévia da foto do aluno": "Vista previa de la foto del alumno",
  "Foto opcional": "Foto opcional",
  "Tirar foto": "Tomar foto",
  "Capturar foto": "Capturar foto",
  "Cancelar câmera": "Cancelar cámara",
  "Selecionar imagem": "Seleccionar imagen",
  "Remover foto": "Quitar foto",
  "Confirmo que a pessoa autorizou o cadastro desta foto.": "Confirmo que la persona autorizó registrar esta foto.",
  "Esta tela não tem acesso à câmera. Escolha uma imagem do computador.": "Esta pantalla no tiene acceso a la cámara. Selecciona una imagen del equipo.",
  "Permita o acesso à câmera ou escolha uma imagem do computador.": "Permite el acceso a la cámara o selecciona una imagen del equipo.",
  "Use uma foto JPG, PNG ou WebP.": "Usa una foto JPG, PNG o WebP.",
  "A foto precisa ter até 5 MB.": "La foto debe pesar hasta 5 MB.",
  "Não foi possível preparar essa foto. Tente outra imagem.": "No se pudo preparar esta foto. Prueba con otra imagen.",
  "Essa foto ficou grande demais. Selecione uma imagem menor.": "La foto es demasiado grande. Selecciona una imagen más pequeña.",
  "Confirme que a pessoa autorizou o cadastro desta foto.": "Confirma que la persona autorizó registrar esta foto.",
  "Alunos cadastrados": "Alumnos registrados",
  "Buscar por nome ou documento": "Buscar por nombre o documento",
  "Buscar por nome": "Buscar por nombre",
  "Nome": "Nombre",
  "Documento": "Documento",
  "Status": "Estado",
  "Dias restantes": "Días restantes",
  "Nenhum aluno cadastrado ainda.": "Todavía no hay alumnos registrados.",
  "Nenhum aluno corresponde à busca.": "Ningún alumno coincide con la búsqueda.",
  "FINANCEIRO": "FINANZAS",
  "Consulte cobranças e registre pagamentos recebidos.": "Consulta los cobros y registra los pagos recibidos.",
  "Consulte as cobranças registradas na academia.": "Consulta los cobros registrados en el gimnasio.",
  "Aluno": "Alumno",
  "Todos os alunos": "Todos los alumnos",
  "Situação": "Situación",
  "Todas as cobranças": "Todos los cobros",
  "Em aberto": "Pendiente",
  "Atrasadas": "Vencidos",
  "Pagas": "Pagados",
  "QR de pagamento da academia": "QR de pago del gimnasio",
  "Para usar o QR, primeiro é preciso atualizar a estrutura do banco com a migração 004.": "Para usar el QR, primero hay que actualizar la base de datos con la migración 004.",
  "Adicione ou troque a imagem do QR usado para receber.": "Agrega o cambia la imagen QR que usas para recibir pagos.",
  "Nenhum QR cadastrado.": "No hay ningún QR registrado.",
  "Adicionar ou substituir o QR": "Agregar o reemplazar el QR",
  "Remover QR": "Eliminar QR",
  "Este QR é uma imagem informativa. Até conectar um provedor bancário com confirmação automática, a equipe precisa confirmar o recebimento antes de baixar a cobrança.": "Este QR es una imagen informativa. Hasta conectar un proveedor bancario con confirmación automática, el equipo debe verificar el pago antes de marcar el cobro como pagado.",
  "Vencimento": "Vencimiento",
  "Valor": "Importe",
  "Nenhuma cobrança encontrada para este filtro.": "No se encontraron cobros con este filtro.",
  "CATRACA": "TORNIQUETE",
  "Histórico de acessos": "Historial de accesos",
  "Últimas 100 tentativas de entrada registradas.": "Últimos 100 intentos de acceso registrados.",
  "Data e hora": "Fecha y hora",
  "Resultado": "Resultado",
  "Motivo": "Motivo",
  "Nenhum acesso registrado ainda.": "Todavía no hay accesos registrados.",
  "MATRÍCULAS": "INSCRIPCIONES",
  "Veja os planos disponíveis para os alunos.": "Consulta los planes disponibles para los alumnos.",
  "Novo plano": "Nuevo plan",
  "Defina o valor e a duração.": "Define el importe y la duración.",
  "Nome do plano *": "Nombre del plan *",
  "Duração em dias *": "Duración en días *",
  "Criar plano": "Crear plan",
  "Nenhum plano cadastrado ainda.": "Todavía no hay planes registrados.",
  "ACESSO": "ACCESO",
  "Crie, consulte e suspenda acessos da recepção da sua academia.": "Crea, consulta y suspende accesos del personal de recepción.",
  "Senha inicial *": "Contraseña inicial *",
  "Use pelo menos 8 caracteres e compartilhe a senha por um canal seguro.": "Usa al menos 8 caracteres y comparte la contraseña por un canal seguro.",
  "Criar acesso": "Crear acceso",
  "Contas de recepção": "Cuentas de recepción",
  "Ações": "Acciones",
  "Nenhuma conta de recepção cadastrada.": "No hay cuentas de recepción registradas.",
  "PLATAFORMA": "PLATAFORMA",
  "Cadastre e administre academias na plataforma.": "Registra y administra gimnasios en la plataforma.",
  "Nova academia": "Nuevo gimnasio",
  "Será criado também o acesso do dono.": "También se creará el acceso del propietario.",
  "Nome da academia *": "Nombre del gimnasio *",
  "Logo da academia (opcional)": "Logo del gimnasio (opcional)",
  "Ela pode aparecer na tela do aluno. PNG, JPG ou WebP; até 5 MB.": "Puede aparecer en la pantalla del alumno. PNG, JPG o WebP; hasta 5 MB.",
  "País *": "País *",
  "Nome do dono *": "Nombre del propietario *",
  "E-mail do dono *": "Correo electrónico del propietario *",
  "Senha inicial do dono *": "Contraseña inicial del propietario *",
  "Criar academia": "Crear gimnasio",
  "Academias cadastradas": "Gimnasios registrados",
  "País": "País",
  "Nenhuma academia cadastrada.": "No hay gimnasios registrados.",
  "Administrador da plataforma": "Administrador de la plataforma",
  "Dono da academia": "Propietario del gimnasio",
  "Recepção": "Recepción",
  "Ativo": "Activo",
  "Inativo": "Inactivo",
  "Pago": "Pagado",
  "Em dia": "Al día",
  "Atrasado": "Vencido",
  "Vence em breve": "Vence pronto",
  "Suspenso": "Suspendido",
  "Em aberto": "Pendiente",
  "Pendente": "Pendiente",
  "Alunos cadastrados": "Alumnos registrados",
  "Alunos ativos": "Alumnos activos",
  "Com alerta": "Con alerta",
  "Ainda não há alunos para exibir.": "Todavía no hay alumnos para mostrar.",
  "Sem alerta": "Sin alerta",
  "Vence em breve": "Vence pronto",
  "Desativar": "Desactivar",
  "Ativar": "Activar",
  "Registrar pagamento": "Registrar pago",
  "Apagar pagamento": "Eliminar pago",
  "Pendente": "Pendiente",
  "Biometria não cadastrada": "Biometría no registrada",
  "Aluno inativo": "Alumno inactivo",
  "Plano não cadastrado": "Plan no registrado",
  "Sem mensalidade em aberto": "Sin mensualidad pendiente",
  "Mensalidade atrasada": "Mensualidad vencida",
  "Academia suspensa": "Gimnasio suspendido",
  "Identificação desconhecida": "Identificación desconocida",
  "Liberado": "Permitido",
  "Bloqueado": "Bloqueado",
  "Ativa": "Activa",
  "Suspender": "Suspender",
  "Reativar": "Reactivar",
  "E-mail ou senha incorretos.": "Correo electrónico o contraseña incorrectos.",
  "Muitas tentativas de acesso. Aguarde alguns minutos e tente novamente.": "Demasiados intentos de acceso. Espera unos minutos e inténtalo de nuevo.",
  "Sua sessão expirou. Entre novamente.": "Tu sesión venció. Ingresa nuevamente.",
  "Esta conta não está ativa. Fale com o administrador.": "Esta cuenta no está activa. Comunícate con el administrador.",
  "Sua conta não tem permissão para esta ação.": "Tu cuenta no tiene permiso para esta acción.",
  "Este e-mail já está cadastrado.": "Este correo electrónico ya está registrado.",
  "Informe um e-mail válido.": "Ingresa un correo electrónico válido.",
  "Cadastre o e-mail do aluno antes de enviar o convite.": "Registra el correo del alumno antes de enviar la invitación.",
  "O app do aluno ainda não está ligado nesta academia.": "La app del alumno aún no está activada en este gimnasio.",
  "Não foi possível enviar o convite agora. Aguarde um minuto e tente novamente.": "No se pudo enviar la invitación ahora. Espera un minuto e inténtalo de nuevo.",
  "O cadastro de e-mail do aluno depende de uma atualização do sistema.": "El registro del correo del alumno depende de una actualización del sistema.",
  "E-mail (acesso ao app)": "Correo electrónico (acceso a la app)",
  "E-mail para acesso ao app": "Correo electrónico para acceso a la app",
  "Enviar convite": "Enviar invitación",
  "Redefinir acesso": "Restablecer acceso",
  "Convite enviado por e-mail.": "Invitación enviada por correo electrónico.",
  "Acesso redefinido. Envie um novo convite.": "Acceso restablecido. Envía una nueva invitación.",
  "Redefinir o acesso deste aluno ao app? Ele precisará criar uma nova senha.": "¿Restablecer el acceso de este alumno a la app? Deberá crear una nueva contraseña.",
  "Sem e-mail cadastrado: o aluno ainda não pode entrar no app.": "Sin correo registrado: el alumno aún no puede entrar a la app.",
  "E-mail cadastrado. O aluno cria a senha no primeiro acesso, com um código enviado ao e-mail.": "Correo registrado. El alumno crea su contraseña en el primer acceso, con un código enviado al correo.",
  "Acesso ao app ativo.": "Acceso a la app activo.",
  "Esta academia ou o e-mail informado já está cadastrado. Confira os dados.": "Este gimnasio o correo electrónico ya está registrado. Verifica los datos.",
  "Documento ou biometria já cadastrados.": "El documento o la biometría ya están registrados.",
  "Aluno não encontrado nesta academia.": "No se encontró al alumno en este gimnasio.",
  "Informe o documento do aluno.": "Ingresa el documento del alumno.",
  "Não há dados para atualizar.": "No hay datos para actualizar.",
  "Documento já cadastrado nesta academia.": "El documento ya está registrado en este gimnasio.",
  "Informe nome e documento do aluno.": "Ingresa el nombre y el documento del alumno.",
  "Informe o nome do plano.": "Ingresa el nombre del plan.",
  "Preencha todos os campos obrigatórios.": "Completa todos los campos obligatorios.",
  "Informe o nome e o e-mail.": "Ingresa el nombre y el correo electrónico.",
  "Use uma senha com pelo menos oito caracteres.": "Usa una contraseña de al menos ocho caracteres.",
  "A data de nascimento não pode estar no futuro.": "La fecha de nacimiento no puede ser futura.",
  "O plano selecionado não pertence a esta academia.": "El plan seleccionado no pertenece a este gimnasio.",
  "O aluno não tem um plano cadastrado.": "El alumno no tiene un plan registrado.",
  "Não foi possível associar o cadastro à academia. Atualize a tela e tente novamente.": "No se pudo asociar el registro con el gimnasio. Actualiza la página e inténtalo de nuevo.",
  "A academia está suspensa. Fale com o administrador.": "El gimnasio está suspendido. Comunícate con el administrador.",
  "Não há mensalidade em aberto para este aluno.": "El alumno no tiene una mensualidad pendiente.",
  "Este pagamento já foi registrado como pago.": "Este pago ya fue registrado.",
  "Pagamento não encontrado.": "No se encontró el pago.",
  "O filtro de pagamentos não é válido.": "El filtro de pagos no es válido.",
  "Nenhum QR de pagamento foi cadastrado.": "No se ha registrado ningún QR de pago.",
  "Envie uma imagem PNG, JPG ou WebP.": "Carga una imagen PNG, JPG o WebP.",
  "A imagem do QR deve ter no máximo 2 MB.": "La imagen QR debe pesar como máximo 2 MB.",
  "Não foi possível reconhecer o formato da imagem enviada.": "No se pudo reconocer el formato de la imagen.",
  "Para usar o QR, primeiro é preciso atualizar a estrutura do banco com a migração 004.": "Para usar el QR, primero hay que actualizar la base de datos con la migración 004.",
  "Academia não encontrada.": "No se encontró el gimnasio.",
  "Conta de recepção não encontrada nesta academia.": "No se encontró la cuenta de recepción en este gimnasio.",
  "Esta cópia da nuvem permite consulta. Faça alterações no sistema local da academia.": "Esta copia en la nube permite consultas. Realiza los cambios en el sistema local del gimnasio.",
  "Confira os campos preenchidos e tente novamente.": "Revisa los campos e inténtalo de nuevo.",
  "Não foi possível concluir a solicitação. Tente novamente.": "No se pudo completar la solicitud. Inténtalo de nuevo.",
  "Sua conta não tem acesso a esta área.": "Tu cuenta no tiene acceso a esta sección.",
  "A equipe não faz parte da cópia de consulta na nuvem.": "El equipo no forma parte de la copia de consulta en la nube.",
  "Consulte os alunos e as informações disponíveis nesta cópia.": "Consulta los alumnos y la información disponible en esta copia.",
  "Consulte as academias cadastradas na plataforma.": "Consulta los gimnasios registrados en la plataforma.",
  "Não foi possível carregar o QR da academia.": "No se pudo cargar el QR del gimnasio.",
  "Não foi possível conectar ao Frequency. Verifique a conexão e tente novamente.": "No se pudo conectar con Frequency. Verifica la conexión e inténtalo de nuevo.",
  "Não foi possível confirmar o modo desta instalação.": "No se pudo confirmar el modo de esta instalación.",
  "A configuração desta instalação está incompleta.": "La configuración de esta instalación está incompleta.",
  "Confirmação": "Confirmación",
  "Ativo": "Activo",
  "Suspenso": "Suspendido",
  "Entrando…": "Ingresando…",
  "Não foi possível entrar.": "No se pudo iniciar sesión.",
  "Sessão encerrada.": "Sesión cerrada.",
  "Vocês saiu do Frequency.": "Saliste de Frequency.",
  "Você saiu do Frequency.": "Saliste de Frequency.",
  "Aluno cadastrado.": "Alumno registrado.",
  "Aluno desativado.": "Alumno desactivado.",
  "Aluno ativado.": "Alumno activado.",
  "Confirmar que este pagamento foi recebido?": "¿Confirmas que recibiste este pago?",
  "Pagamento registrado.": "Pago registrado.",
  "Confirmar apagar este pagamento já pago?": "¿Confirmas que quieres eliminar este pago ya registrado?",
  "Pagamento apagado.": "Pago eliminado.",
  "QR de pagamento atualizado.": "QR de pago actualizado.",
  "Remover o QR de pagamento desta academia?": "¿Eliminar el QR de pago de este gimnasio?",
  "QR removido.": "QR eliminado.",
  "Plano criado.": "Plan creado.",
  "Acesso da recepção criado. Compartilhe os dados por um canal seguro.": "Acceso de recepción creado. Comparte los datos por un canal seguro.",
  "Academia criada com acesso do dono.": "Gimnasio creado con acceso del propietario.",
  "Academia suspensa.": "Gimnasio suspendido.",
  "Academia ativada.": "Gimnasio activado.",
  "Confirma suspender o acesso desta pessoa da recepção?": "¿Confirmas que quieres suspender el acceso de esta persona de recepción?",
  "Confirma reativar o acesso desta pessoa da recepção?": "¿Confirmas que quieres reactivar el acceso de esta persona de recepción?",
  "Desativar este aluno?": "¿Desactivar a este alumno?",
  "Ativar este aluno?": "¿Activar a este alumno?",
  "Confirmar que este pagamento foi recebido?": "¿Confirmas que recibiste este pago?",
  "Remover o QR de pagamento desta academia?": "¿Eliminar el QR de pago de este gimnasio?",
  "Confirma suspender esta academia?": "¿Confirmas la suspensión de este gimnasio?",
  "Confirma ativar esta academia?": "¿Confirmas la activación de este gimnasio?",
  "Confirma suspender o acesso desta pessoa da recepção?": "¿Confirmas que quieres suspender el acceso de esta persona de recepción?",
  "Confirma reativar o acesso desta pessoa da recepção?": "¿Confirmas que quieres reactivar el acceso de esta persona de recepción?",
  "Acesso da recepção suspenso.": "Acceso de recepción suspendido.",
  "Acesso da recepção reativado.": "Acceso de recepción reactivado.",
  "Entre novamente para continuar.": "Ingresa nuevamente para continuar.",
  "A tela ainda não tem um código ativo.": "La pantalla todavía no tiene un código activo.",
  "Código ativo. Abra /monitor no segundo computador e informe o código gerado.": "Código activo. Abre /monitor en el segundo equipo e introduce el código generado.",
  "O código foi mostrado uma única vez. Guarde-o apenas no computador do monitor.": "El código se muestra una sola vez. Guárdalo solo en el equipo del monitor.",
  "Confirma gerar outro código? O monitor atual será desconectado.": "¿Confirmas que quieres generar otro código? El monitor actual se desconectará.",
  "Código copiado.": "Código copiado.",
  "Não foi possível copiar automaticamente. Selecione e copie o código.": "No se pudo copiar automáticamente. Selecciona y copia el código.",
  "Logo da tela atualizada.": "Logo de pantalla actualizada.",
  "Logo removida.": "Logo quitada.",
  "Envie uma imagem JPG, PNG ou WebP de até 5 MB.": "Carga una imagen JPG, PNG o WebP de hasta 5 MB.",
  "Confirma remover a logo da segunda tela?": "¿Confirmas que quieres quitar el logo de la segunda pantalla?",
  "A tela do monitor precisa da migração 007 antes de ser configurada.": "La pantalla del monitor necesita la migración 007 antes de configurarse.",
  "Destino local": "Destino local",
  "A cópia é criptografada antes de ser salva na pasta configurada pelo computador que hospeda o Frequency.": "La copia se cifra antes de guardarse en la carpeta configurada por el ordenador que aloja Frequency.",
  "Este caminho pertence ao computador que executa o Frequency. Em celular ou tablet, use “Baixar última cópia” para guardar o arquivo no dispositivo atual.": "Esta ruta pertenece al ordenador que ejecuta Frequency. En teléfono o tableta, usa «Descargar la última copia» para guardar el archivo en el dispositivo actual.",
  "O Google Drive do computador que hospeda o Frequency está disponível. Para enviar à sua conta neste dispositivo, use Compartilhar.": "Google Drive del ordenador que aloja Frequency está disponible. Para enviarla a tu cuenta en este dispositivo, usa Compartir.",
  "Google Drive detectado no computador que hospeda o Frequency. O próximo backup será salvo na pasta sincronizada.": "Google Drive detectado en el ordenador que aloja Frequency. La próxima copia se guardará en la carpeta sincronizada.",
  "No celular ou tablet, baixe a cópia e use Compartilhar para enviá-la ao aplicativo Google Drive.": "En el teléfono o tableta, descarga la copia y usa Compartir para enviarla a la aplicación Google Drive.",
  "Instale o Google Drive para computador neste equipamento ou baixe a cópia criptografada para enviá-la manualmente.": "Instala Google Drive para ordenador en este equipo o descarga la copia cifrada para enviarla manualmente.",
  "Compartilhar última cópia": "Compartir la última copia",
  "Usar pasta sincronizada": "Usar carpeta sincronizada",
  "Abrir Google Drive": "Abrir Google Drive",
  "Cópia compartilhada. Escolha o Google Drive ou outro destino na janela do dispositivo.": "Copia compartida. Elige Google Drive u otro destino en la ventana del dispositivo.",
  "Backup baixado. Use Compartilhar para enviá-lo ao Google Drive.": "Copia descargada. Usa Compartir para enviarla a Google Drive.",
  "A cópia fica na pasta configurada pelo computador que hospeda o Frequency; você também pode baixá-la para este dispositivo.": "La copia queda en la carpeta configurada por el ordenador que aloja Frequency; también puedes descargarla en este dispositivo.",
  "Neste dispositivo, a cópia será baixada pelo navegador. Se o navegador permitir, você também poderá escolher uma pasta.": "En este dispositivo, la copia se descargará mediante el navegador. Si el navegador lo permite, también podrás elegir una carpeta.",
  "Escolha uma pasta neste navegador para salvar o próximo arquivo criptografado.": "Elige una carpeta en este navegador para guardar el próximo archivo cifrado.",
  "Pasta do navegador selecionada. Gere o backup e baixe a cópia para salvá-la aqui.": "Carpeta del navegador seleccionada. Genera la copia y descárgala para guardarla aquí.",
  "Este navegador não permite escolher uma pasta diretamente. Use o download da cópia criptografada.": "Este navegador no permite elegir una carpeta directamente. Usa la descarga de la copia cifrada.",
  "Salvar no dispositivo": "Guardar en el dispositivo",
  "Toque em Salvar no dispositivo. No iPhone escolha Salvar em Arquivos; no Android escolha Files, Downloads ou Google Drive.": "Toca en Guardar en el dispositivo. En iPhone elige Guardar en Archivos; en Android elige Files, Descargas o Google Drive.",
  "Backup baixado. Abra o menu Compartilhar para salvar em Arquivos ou Downloads.": "Copia descargada. Abre el menú Compartir para guardarla en Archivos o Descargas.",
  "Escolha Arquivos, Files, Downloads ou Google Drive para salvar a cópia.": "Elige Archivos, Files, Descargas o Google Drive para guardar la copia.",
  "Baixar última cópia": "Descargar la última copia",
  "Backup baixado para este dispositivo.": "Copia descargada en este dispositivo.",
  "Backup salvo na pasta escolhida.": "Copia guardada en la carpeta elegida.",
  "Nenhum backup criptografado foi encontrado nesta instalação.": "No se encontró ninguna copia cifrada en esta instalación.",
  "O backup ainda não foi configurado nesta instalação.": "La copia aún no está configurada en esta instalación.",
  "Já existe um backup em andamento.": "Ya hay una copia en curso.",
  "Preparando a cópia criptografada…": "Preparando la copia cifrada…",
  "O backup demorou para ficar disponível. Atualize o estado e tente novamente.": "La copia tardó en estar disponible. Actualiza el estado y vuelve a intentarlo.",
};

function traduzir(texto) {
  if (typeof texto !== "string") return texto;
  return window.FrequencyI18n.translate(interfaceLocale, texto, traducoesEs);
}

function traduzirDocumento(idioma) {
  interfaceLocale = idioma || "pt-BR";
  document.documentElement.lang = interfaceLocale;
  document.title = traduzir("Frequency — gestão da academia");
  window.FrequencyI18n.renderStatic(traduzir);
  if (typeof populateCountryOptions === "function") populateCountryOptions();
  if (typeof preparePhoneFields === "function") preparePhoneFields();
  ["#login-language", "#app-language", "#preference-language"].forEach((selector) => { if ($(selector)) $(selector).value = interfaceLocale; });
}

function setInterfaceLanguage(locale) {
  window.FrequencyI18n.saveLocale(locale, state.user?.id);
  if (state.user) state.user.idioma = locale;
  traduzirDocumento(locale);
  renderSignupPlanContext?.();
  configureSignupNextActions?.();
  configureSignupSupportAction?.();
  syncFeatureLocale();
  renderFacialEvents();
  if (state.user) { $("#account-role").textContent = traduzir(roleNames[state.user.papel]); setPage(state.page || "dashboard"); }
}

const messages = {
  desafios_desligado: "Os desafios ainda não estão ligados para esta academia.",
  gerador_desligado: "O gerador de treino ainda não está ligado para esta academia.",
  mensalidade_desligada: "A mensalidade no app ainda não está ligada para esta academia.",
  qr_invalido: "QR inválido ou vencido. Peça para o aluno abrir o QR de novo no app.",
  mensalidade_atrasada: "Mensalidade atrasada.",
  sem_pagamento_em_aberto: "Sem cobrança em aberto.",
  aluno_inativo: "Aluno inativo.",
  plano_nao_cadastrado: "Aluno sem plano.",
  limite_de_desafios: "Limite de desafios ativos atingido.",
  periodo_invalido: "Período inválido.",
  desafio_encerrado: "Este desafio já terminou.",
  pelo_menos_um_equipamento: "Deixe pelo menos um aparelho disponível.",
  lutas_desligado: "O módulo de lutas ainda não está ligado para esta academia.",
  fora_do_prazo_de_ajuste: "A chamada só pode ser corrigida até 24 horas depois do fim da aula.",
  plano_sem_modalidade: "O plano deste aluno não inclui esta modalidade.",
  sem_aula_neste_dia: "Esta turma não tem aula neste dia.",
  aula_no_futuro: "Esta aula ainda não começou.",
  horario_ja_existe: "Esta turma já tem um horário que começa nesse momento.",
  modalidade_ja_existe: "Já existe uma modalidade com este nome.",
  email_em_uso: "Este e-mail já está em uso.",
  ordem_ja_existe: "Já existe uma faixa nesta posição.",
  turma_cheia: "A turma está cheia.",
  seletor_de_pasta_indisponivel: "O seletor de pasta só está disponível no computador que hospeda o Frequency.",
  backup_nao_configurado: "O backup ainda não foi configurado nesta instalação.",
  backup_em_andamento: "Já existe um backup em andamento.",
  backup_gerenciado_pela_plataforma: "Na versão web, a Frequency faz o backup da sua academia automaticamente. Para ter cópias no seu computador, use o Frequency Local.",
  backup_indisponivel: "Não foi possível iniciar o backup.",
  backup_nao_encontrado: "Nenhum backup criptografado foi encontrado nesta instalação.",
  assinatura_frequency_bloqueada: "Entre em contato com o administrador do sistema para regularizar a assinatura.",
  experiencia_expirada: "Sua experiência gratuita terminou. Escolha um plano para continuar usando o Frequency.",
  migracao_frequency_pendente: "A cobrança Frequency ainda não está disponível nesta instalação. Fale com o administrador.",
  plano_frequency_ja_cadastrado: "Já existe um pacote com esse nome.",
  recursos_exclusivos_premium: "Câmeras e YouTube só podem ser incluídos em pacotes Premium.",
  premium_deve_ser_mais_caro: "O pacote Premium precisa ter preço proporcional maior que os demais pacotes ativos na mesma moeda.",
  assinatura_frequency_ja_cadastrada: "Esta academia já possui assinatura.",
  fatura_frequency_ja_finalizada: "Esta fatura já foi finalizada. Atualize a lista.",
  fatura_frequency_em_aberto_nao_encontrada: "Esta cobrança não está mais em aberto. Atualize a lista.",
  cancelar_ultima_fatura_ativa: "Suspenda ou cancele a assinatura antes de cancelar sua última fatura.",
  qr_frequency_nao_cadastrado: "Nenhum QR cadastrado.",
  google_nao_configurado: "A conexão Google ainda não foi configurada no servidor.",
  arquivo_nao_encontrado: "O arquivo não está disponível neste servidor.",
  link_download_expirado: "O link de download expirou. Clique novamente para gerar outro.",
  google_sessao_oauth_invalida: "A autorização do Google expirou ou foi aberta em outro navegador. Tente novamente neste dispositivo.",
  google_state_invalido: "A autorização do Google expirou. Tente novamente.",
  google_callback_incompleto: "O Google não devolveu a autorização completa. Tente novamente.",
  google_indisponivel: "O Google não respondeu agora. Tente novamente em instantes.",
  google_identidade_invalida: "Não foi possível confirmar sua conta Google. Tente outra conta.",
  google_falhou: "Não foi possível concluir o acesso com o Google. Tente novamente.",
  conta_nao_encontrada: "Nenhuma conta Frequency usa este e-mail do Google. Cadastre a academia ou entre com e-mail e senha.",
  gmail_autorizacao_incompleta: "O Google não autorizou a leitura do Gmail. Tente conectar novamente.",
  gmail_autorizacao_expirada: "A autorização do Gmail expirou. Desconecte e conecte novamente.",
  gmail_indisponivel: "A API de leitura do Gmail não respondeu. Tente novamente em instantes.",
  google_conta_nao_verificada: "A conta Google precisa estar verificada para conectar o Gmail.",
  email_ou_senha_incorretos: "E-mail ou senha incorretos.",
  login_temporariamente_limitado: "Muitas tentativas de acesso. Aguarde alguns minutos e tente novamente.",
  senha_atual_incorreta: "A senha atual está incorreta.",
  token_invalido: "Sua sessão expirou. Entre novamente.",
  usuario_invalido: "Esta conta não está ativa. Fale com o administrador.",
  sem_permissao: "Sua conta não tem permissão para esta ação.",
  email_ja_cadastrado: "Este e-mail já está cadastrado.",
  email_invalido: "Informe um e-mail válido.",
  aluno_sem_email: "Cadastre o e-mail do aluno antes de enviar o convite.",
  recurso_desligado: "O app do aluno ainda não está ligado nesta academia.",
  convite_nao_enviado: "Não foi possível enviar o convite agora. Aguarde um minuto e tente novamente.",
  migracao_email_pendente: "O cadastro de e-mail do aluno depende de uma atualização do sistema.",
  cliente_ja_cadastrado: "Este cliente já está cadastrado. Use o e-mail informado para entrar ou recuperar o acesso.",
  academia_ou_email_ja_cadastrado: "Esta academia ou o e-mail informado já está cadastrado. Confira os dados.",
  migracao_lead_cadastro_pendente: "O cadastro está temporariamente indisponível porque a estrutura de leads ainda precisa ser atualizada.",
  documento_ou_biometria_ja_cadastrado: "Documento já cadastrado.",
  documento_obrigatorio: "Informe o documento do aluno.",
  nenhum_campo_para_atualizar: "Não há dados para atualizar.",
  documento_ja_cadastrado: "Documento já cadastrado nesta academia.",
  formato_de_foto_nao_suportado: "Use uma foto JPG, PNG ou WebP.",
  foto_invalida: "Não foi possível reconhecer essa foto. Escolha outra imagem.",
  foto_muito_grande: "Essa foto ficou grande demais. Selecione uma imagem menor.",
  migracao_foto_pendente: "Para salvar fotos, primeiro é preciso atualizar a estrutura do banco com a migração 006.",
  foto_nao_cadastrada: "Este aluno ainda não tem foto.",
  formato_de_foto_nao_suportado: "Use uma foto JPG, PNG ou WebP.",
  foto_invalida: "Não foi possível reconhecer essa foto. Escolha outra imagem.",
  foto_muito_grande: "Essa foto ficou grande demais. Selecione uma imagem menor.",
  migracao_foto_pendente: "Para salvar fotos, primeiro é preciso atualizar a estrutura do banco com a migração 006.",
  aluno_nao_encontrado: "Aluno não encontrado nesta academia.",
  nome_e_documento_obrigatorios: "Informe nome e documento do aluno.",
  nome_do_plano_obrigatorio: "Informe o nome do plano.",
  preencha_todos_os_campos: "Preencha todos os campos obrigatórios.",
  preencha_nome_e_email: "Informe o nome e o e-mail.",
  a_senha_precisa_ter_pelo_menos_8_caracteres: "Use uma senha com pelo menos oito caracteres.",
  data_nascimento_invalida: "A data de nascimento não pode estar no futuro.",
  plano_invalido: "O plano selecionado não pertence a esta academia.",
  plano_nao_encontrado: "Plano não encontrado.",
  plano_em_uso: "Este plano está ligado a alunos e não pode ser apagado.",
  plano_ja_atribuido: "Este aluno já está vinculado a outro plano.",
  plano_nao_cadastrado: "O aluno não tem um plano cadastrado.",
  aluno_sem_plano: "Selecione um plano antes de registrar o pagamento.",
  academia_invalida: "Não foi possível associar o cadastro à academia. Atualize a tela e tente novamente.",
  academia_inativa: "A academia está suspensa. Fale com o administrador.",
  sem_pagamento_em_aberto: "Não há mensalidade em aberto para este aluno.",
  pagamento_ja_pago: "Este pagamento já foi registrado como pago.",
  pagamento_nao_encontrado: "Pagamento não encontrado.",
  pagamento_nao_pago_para_excluir: "Somente pagamentos já pagos podem ser apagados.",
  filtro_de_pagamentos_invalido: "O filtro de pagamentos não é válido.",
  qr_nao_cadastrado: "Nenhum QR de pagamento foi cadastrado.",
  formato_de_qr_nao_suportado: "Envie uma imagem PNG, JPG ou WebP.",
  imagem_de_qr_muito_grande: "A imagem do QR deve ter no máximo 2 MB.",
  imagem_de_qr_invalida: "Não foi possível reconhecer o formato da imagem enviada.",
  migracao_qr_pendente: "Para usar o QR, primeiro é preciso atualizar a estrutura do banco com a migração 004.",
  academia_nao_encontrada: "Academia não encontrada.",
  recepcionista_nao_encontrado: "Conta de recepção não encontrada nesta academia.",
  modo_somente_consulta: "Esta cópia da nuvem permite consulta. Faça alterações no sistema local da academia.",
  migracao_monitor_pendente: "A tela do monitor precisa da migração 007 antes de ser configurada.",
  chave_do_monitor_ausente: "Informe o código de conexão da segunda tela.",
  chave_do_monitor_invalida: "O código da segunda tela expirou ou foi renovado. Gere outro código no painel.",
  limite_de_monitores_do_plano_atingido: "O limite de telas do seu plano foi atingido. Atualize o plano ou desconecte uma tela antes de adicionar outra.",
  foto_nao_cadastrada: "Este aluno ainda não tem foto.",
  logo_nao_cadastrada: "Nenhuma logo foi cadastrada.",
  migracao_pagamento_online_pendente: "Atualize o banco com a migração de pagamentos online antes de usar este recurso.",
  dlocal_nao_configurado: "O pagamento online ainda não foi configurado nesta instalação.",
  pagamento_exige_url_https: "O pagamento online exige um endereço HTTPS público.",
  pagamento_em_criacao: "Já existe uma tentativa de pagamento em preparação. Aguarde e atualize a tela.",
  gateway_pagamento_indisponivel: "O provedor de pagamento não respondeu. Tente novamente em instantes.",
  documento_pagador_obrigatorio: "Informe um documento válido para iniciar o pagamento.",
  pagamento_webhook_exige_https: "A confirmação automática exige HTTPS.",
  assinatura_webhook_invalida: "A confirmação do provedor não pôde ser validada.",
};

function element(tag, text, className) {
  const node = document.createElement(tag);
  if (text !== undefined && text !== null) node.textContent = String(text);
  if (className) node.className = className;
  return node;
}

function icon(name, className = "icon") {
  const svg = document.createElementNS("http://www.w3.org/2000/svg", "svg");
  svg.setAttribute("class", className);
  svg.setAttribute("aria-hidden", "true");
  const use = document.createElementNS("http://www.w3.org/2000/svg", "use");
  use.setAttribute("href", `#icon-${name}`);
  svg.append(use);
  return svg;
}

function showNotice(text, isError = false) {
  const notice = $("#app-notice");
  notice.textContent = traduzir(text);
  notice.classList.toggle("error", isError);
  notice.hidden = !text;
}

function apiMessage(detail) {
  if (typeof detail === "string") return traduzir(messages[detail] || detail.replaceAll("_", " "));
  if (Array.isArray(detail)) return traduzir("Confira os campos preenchidos e tente novamente.");
  return traduzir("Não foi possível concluir a solicitação. Tente novamente.");
}

async function fetchFrequency(input, init) {
  if (isOfflineTestMode()) {
    window.dispatchEvent(new CustomEvent("frequency:connection", { detail: false }));
  }
  const controller = new AbortController();
  const timeout = setTimeout(() => controller.abort(), 20000);
  try {
    const response = await fetch(input, { ...init, signal: controller.signal, cache: "no-store" });
    window.dispatchEvent(new CustomEvent("frequency:connection", { detail: true }));
    return response;
  } catch (error) {
    window.dispatchEvent(new CustomEvent("frequency:connection", { detail: false }));
    throw new Error(traduzir(error.name === "AbortError" ? "O servidor demorou para responder. Confira o resultado antes de reenviar." : "Não foi possível conectar ao Frequency. Verifique a conexão e tente novamente."));
  } finally { clearTimeout(timeout); }
}

async function api(path, options = {}) {
  const requestToken = state.token;
  const headers = new Headers(options.headers || {});
  headers.set("Accept", "application/json");
  headers.set("X-Frequency-Device-Class", frequencyDeviceClass);
  if (state.token) headers.set("Authorization", `Bearer ${state.token}`);

  let body = options.body;
  if (body && typeof body === "object" && !(body instanceof FormData) && !(body instanceof URLSearchParams) && !(body instanceof Blob)) {
    headers.set("Content-Type", "application/json");
    body = JSON.stringify(body);
  }

  const response = await fetchFrequency(path, { ...options, headers, body });
  if (requestToken !== state.token) throw new Error(traduzir("Sessão encerrada."));
  let data = null;
  try {
    data = await response.json();
  } catch {
    data = null;
  }

  if (response.status === 401 && path !== "/login") {
    endSession("Sua sessão expirou. Entre novamente.");
    throw new Error("Sessão encerrada.");
  }
  if (response.status === 402 && state.user) {
    state.user.bloqueada_frequency = true;
    renderSubscriptionBanner();
    if (state.page !== "assinatura") setPage("assinatura");
  }
  if (!response.ok) {
    const error = new Error(response.status === 429 ? traduzir("Muitas tentativas de acesso. Aguarde alguns minutos e tente novamente.") : response.status >= 500 && !data?.detail ? traduzir("O serviço está indisponível. Tente novamente em alguns instantes.") : apiMessage(data?.detail));
    error.status = response.status; error.detail = data?.detail; throw error;
  }
  return data;
}

async function carregarConfiguracao() {
  const response = await fetchFrequency("/config", { cache: "no-store", headers: { Accept: "application/json" } });
  if (!response.ok) throw new Error("Não foi possível confirmar o modo desta instalação.");
  const config = await response.json();
  if (typeof config.somente_consulta !== "boolean") {
    throw new Error("A configuração desta instalação está incompleta.");
  }
  return config;
}

function endSession(message = "") {
  stopFacialEvents();

  const loginLocale = state.user?.idioma || interfaceLocale;
  sessionStorage.removeItem(tokenStorageKey);
  state.token = null;
  state.user = null;
  state.config = { somente_consulta: false };
  clearBusinessSession();
  $$("tbody").forEach((node) => node.replaceChildren());
  ["#monitor-key-value", "#academy-form input[type=password]"].forEach((selector) => { if ($(selector)) $(selector).value = ""; });
  $("#monitor-key-wrap").hidden = true;
  $("#copy-monitor-key").hidden = true;
  closeStudentEditForm();
  $("#student-form").reset();
  $("#student-form").hidden = true;
  clearStudentPhoto();
  state.students = [];
  state.plans = [];
  traduzirDocumento(loginLocale);
  if (state.qrPreviewUrl) URL.revokeObjectURL(state.qrPreviewUrl);
  state.qrPreviewUrl = null;
  $("#app-view").hidden = true;
  $("#login-view").hidden = false;
  $("#login-feedback").textContent = traduzir(message);
  $("#login-password").value = "";
}

function formatMoney(value, currency = state.user?.moeda || "BRL") {
  const amount = Number(value);
  if (!Number.isFinite(amount)) return "—";
  const locale = state.user?.idioma || interfaceLocale;
  return new Intl.NumberFormat(locale, { style: "currency", currency }).format(amount);
}

function formatDate(value) {
  if (!value) return "—";
  const parts = String(value).slice(0, 10).split("-").map(Number);
  if (parts.length !== 3 || parts.some((part) => !Number.isInteger(part))) return String(value);
  return new Intl.DateTimeFormat(state.user?.idioma || interfaceLocale, { dateStyle: "short", timeZone: "UTC" })
    .format(new Date(Date.UTC(parts[0], parts[1] - 1, parts[2])));
}

async function loadMonitorSettings() {
  const [settings, monitors] = await Promise.all([
    api("/academia/tela-acesso"),
    api("/academia/monitores"),
  ]);
  renderMonitors(monitors);
  if (settings.codigo_compartilhado) {
    $("#monitor-key-value").value = settings.codigo_compartilhado;
    $("#monitor-key-wrap").hidden = false;
    $("#copy-monitor-key").hidden = false;
  } else {
    $("#monitor-key-value").value = "";
    $("#monitor-key-wrap").hidden = true;
    $("#copy-monitor-key").hidden = true;
  }
  const opened = Number(monitors.limites?.telas_abertas || 0);
  const limit = Number(monitors.limites?.max_monitores || 0);
  $("#monitor-key-status").textContent = monitors.limites.monitores_ativos
    ? `${traduzir("Código compartilhado ativo. Cada nova janela recebe um número do plano.")} ${traduzir("Monitores abertos")}: ${opened}/${limit}.`
    : traduzir("Nenhum código compartilhado criado ainda.");
  $("#remove-monitor-logo").hidden = !settings.logo_cadastrada;
  const response = await fetchFrequency("/academia/tela-acesso/logo", {
    cache: "no-store",
    headers: { Authorization: `Bearer ${state.token}` },
  });
  if (response.status === 401) {
    endSession("Sua sessão expirou. Entre novamente.");
    return;
  }
  if (response.ok) {
    const blob = await response.blob();
    if (state.monitorLogoPreviewUrl) URL.revokeObjectURL(state.monitorLogoPreviewUrl);
    state.monitorLogoPreviewUrl = URL.createObjectURL(blob);
    $("#monitor-logo-preview").src = state.monitorLogoPreviewUrl;
    $("#monitor-logo-preview").hidden = false;
    $("#monitor-logo-placeholder").hidden = true;
  } else if (response.status === 404) {
    if (state.monitorLogoPreviewUrl) URL.revokeObjectURL(state.monitorLogoPreviewUrl);
    state.monitorLogoPreviewUrl = null;
    $("#monitor-logo-preview").hidden = true;
    $("#monitor-logo-placeholder").hidden = false;
  } else {
    let detail = null;
    try { detail = (await response.json())?.detail; } catch { detail = null; }
    throw new Error(apiMessage(detail));
  }
}

function renderMonitors(data) {
  const list = $("#monitor-list");
  if (!list) return;
  list.replaceChildren();
  const active = (data.monitores || []).filter((monitor) => monitor.ativo);
  if (!active.length) {
    list.append(element("p", traduzir("Nenhuma tela conectada ainda."), "list-empty"));
    return;
  }
  active.forEach((monitor, index) => {
    const item = element("article", null, "monitor-item");
    const title = element("div", null, "monitor-item-title");
    title.append(element("strong", traduzir("Código compartilhado")));
    title.append(element("span", traduzir("Use este mesmo código em todas as telas."), "muted"));
    const actions = element("div", null, "monitor-item-actions");
    const open = element("a", traduzir("Abrir tela"), "button button-quiet");
    open.href = "/monitor";
    open.target = "_blank";
    open.rel = "noopener";
    const deactivate = element("button", traduzir("Desconectar"), "button button-quiet");
    deactivate.type = "button";
    deactivate.dataset.monitorId = String(monitor.id);
    actions.append(open, deactivate);
    item.append(title, actions);
    list.append(item);
  });
  (data.sessoes || []).forEach((session) => {
    const item = element("article", null, "monitor-item monitor-session-item");
    const title = element("div", null, "monitor-item-title");
    title.append(element("strong", `${traduzir("Monitor")} · ${session.numero}`));
    const lastSignal = new Intl.DateTimeFormat(state.user?.idioma || interfaceLocale, { dateStyle: "short", timeStyle: "short" }).format(new Date(session.ultimo_sinal));
    title.append(element("span", `${traduzir("Tela aberta")} · ${lastSignal}`, "muted"));
    const actions = element("div", null, "monitor-item-actions");
    const close = element("button", traduzir("Encerrar tela"), "button button-quiet");
    close.type = "button";
    close.dataset.sessionId = String(session.id);
    close.dataset.monitorSession = "true";
    actions.append(close);
    item.append(title, actions);
    list.append(item);
  });
}

function badge(text, tone = "") {
  const tones = { good: "badge badge-good", warn: "badge badge-warn", bad: "badge badge-bad" };
  return element("span", traduzir(text || "—"), tones[tone] || "badge");
}

function setPage(pageName) {
  if (state.page === "alunos" && pageName !== "alunos") stopStudentCamera();
  const pageRoles = {
    dashboard: ["dono", "recepcao"], alunos: ["dono", "recepcao"], pagamentos: ["dono", "recepcao"], planos: ["dono", "recepcao"],
    negocio: ["admin_plataforma"], "site-analytics": ["admin_plataforma"], prospeccao: ["admin_plataforma"], "cobrancas-frequency": ["admin_plataforma"], pacotes: ["admin_plataforma"], "recebimento-frequency": ["admin_plataforma"], "gmail-frequency": ["admin_plataforma"],
    financeiro: ["dono"], assinatura: ["dono", "recepcao"], preferencias: ["dono", "recepcao"], backup: ["dono"], instalar: ["admin_plataforma", "dono", "recepcao"],
    equipe: ["dono"],
    academias: ["admin_plataforma"],
    presencas: ["dono", "recepcao"], "mapa-regiao": ["dono", "recepcao"],
    "tela-aluno": ["dono"], exercicios: ["dono"], quiosques: ["dono"], lutas: ["dono", "recepcao", "professor"], desafios: ["dono"], aparelhos: ["dono"], "qr-acesso": ["dono", "recepcao"], cameras: ["dono"], youtube: ["dono"],
  };
  if (!state.user || !pageRoles[pageName]) return;
  if (state.user.bloqueada_frequency && !["assinatura", "preferencias", "instalar"].includes(pageName)) pageName = "assinatura";
  if (pageRoles[pageName] && !pageRoles[pageName].includes(state.user?.papel)) {
    showNotice("Sua conta não tem acesso a esta área.", true);
    return;
  }
  if (pageName === "equipe" && state.config.somente_consulta) {
    showNotice("A equipe não faz parte da cópia de consulta na nuvem.", true);
    return;
  }

  $$("[data-view]").forEach((page) => {
    const isFeature = ["cameras", "youtube"].includes(page.dataset.view);
    page.hidden = !isFeature && page.dataset.view !== pageName;
    page.classList.toggle("feature-page-background", isFeature && page.dataset.view !== pageName);
    if (isFeature) page.setAttribute("aria-hidden", String(page.dataset.view !== pageName));
  });
  $$("[data-page]").forEach((button) => { button.classList.toggle("active", button.dataset.page === pageName); if (button.dataset.page === pageName) button.setAttribute("aria-current", "page"); else button.removeAttribute("aria-current"); });
  state.page = pageName;
  showNotice("");

  const loaders = {
    negocio: loadBusiness, "site-analytics": loadSiteAnalytics, prospeccao: loadProspecting, "cobrancas-frequency": loadFrequencyInvoices, pacotes: loadFrequencyPlans, "recebimento-frequency": loadPlatformSettings, "gmail-frequency": loadPlatformGmail, financeiro: loadFinance, assinatura: loadOwnerSubscription, preferencias: loadPreferences,
    dashboard: loadDashboard, backup: loadBackupPage,
    alunos: loadStudents,
    pagamentos: async () => {
      await loadStudents();
      await loadAcademyQr();
    },
    presencas: loadPresencas, "mapa-regiao": loadRegionMap,
    planos: loadPlans,
    academias: loadAcademies,
    equipe: loadReceptionTeam,
    "tela-aluno": loadMonitorSettings, exercicios: loadExercises, quiosques: loadKiosks, lutas: () => window.FrequenciaLutas?.carregar(), desafios: () => window.FrequenciaOnda1B?.desafios(), aparelhos: () => window.FrequenciaOnda1B?.aparelhos(), "qr-acesso": () => window.FrequenciaOnda1B?.qr(), cameras: async () => {}, youtube: async () => {},
  };
  const page = $(`[data-view="${pageName}"]`);
  let feedback = $(".page-feedback", page);
  if (!feedback) { feedback = element("div", null, "page-feedback"); feedback.setAttribute("role", "status"); page.prepend(feedback); }
  const request = Symbol(); page.loadRequest = request;
  feedback.replaceChildren(uiText("span", "Carregando…")); feedback.hidden = !loaders[pageName];
  page.setAttribute("aria-busy", String(Boolean(loaders[pageName])));
  const content = Array.from(page.children).filter((node) => node !== feedback && !node.classList.contains("page-heading"));
  content.forEach((node) => { node.inert = true; node.classList.add("page-pending"); });
  Promise.resolve().then(() => loaders[pageName]?.()).then(() => { if (page.loadRequest === request) feedback.hidden = true; }).catch((error) => {
    if (page.loadRequest !== request || !state.user) return;
    feedback.replaceChildren(uiText("span", error.message), actionButton("Tentar novamente", () => setPage(pageName)));
    feedback.classList.add("page-error");
  }).finally(() => {
    if (page.loadRequest !== request) return;
    page.setAttribute("aria-busy", "false");
    content.forEach((node) => { node.inert = false; node.classList.remove("page-pending"); });
  });
}

function showApplication(user) {
  state.user = { ...user, idioma: window.FrequencyI18n.userLocale(user.id, user.idioma), moeda: user.moeda || "BRL" };
  user = state.user;
  traduzirDocumento(user.idioma);
  renderBackupDevicePolicy();
  $("#login-view").hidden = true;
  $("#app-view").hidden = false;
  $("#account-name").textContent = user.nome || "Usuário";
  $("#account-role").textContent = traduzir(roleNames[user.papel] || "Usuário");
  $("#plan-value-label").textContent = `${traduzir("Valor")} (${user.moeda}) *`;
  const somenteConsulta = state.config.somente_consulta;
  if (isOfflineTestMode()) {
    const pill = $("#sync-mode-pill");
    pill.hidden = false;
    pill.textContent = traduzir("Modo offline de teste");
    pill.title = traduzir("A internet está sendo simulada como indisponível neste navegador.");
    pill.classList.add("offline-test");
  }
  $("#sync-mode-pill").hidden = !somenteConsulta;

  $$('[data-role]').forEach((node) => { node.hidden = node.dataset.role !== user.papel; });
  $$('[data-roles]').forEach((node) => {
    node.hidden = !node.dataset.roles.split(/\s+/).includes(user.papel);
  });
  $$('[data-feature-link]').forEach((node) => {
    node.hidden = user.papel !== "dono" || somenteConsulta || !user.recursos_frequency?.[node.dataset.featureLink];
  });
  prepareFeatureFrames(user);
  $$('[data-sync-write]').forEach((node) => {
    const roleAllowed = !node.dataset.role || node.dataset.role === user.papel;
    const rolesAllowed = !node.dataset.roles || node.dataset.roles.split(/\s+/).includes(user.papel);
    const collapsed = node.hasAttribute("data-write-collapsed");
    node.hidden = somenteConsulta || !roleAllowed || !rolesAllowed || collapsed;
  });
  if (somenteConsulta) {
    $('[data-page="equipe"]').hidden = true;
    $("#students-description").textContent = traduzir("Consulte os alunos e as informações disponíveis nesta cópia.");
    $("#student-search-label").textContent = traduzir("Buscar por nome");
    $("#payments-description").textContent = traduzir("Consulte as cobranças registradas na academia.");
    $("#academies-description").textContent = traduzir("Consulte as academias cadastradas na plataforma.");
  }
  $$("[data-feature-link]").forEach(node => { node.hidden = user.papel !== "dono" || somenteConsulta || !user.recursos_frequency?.[node.dataset.featureLink]; });
  renderSubscriptionBanner();
  startFacialEvents();
  setPage(user.papel === "admin_plataforma" ? "negocio" : user.bloqueada_frequency ? "assinatura" : user.papel === "professor" ? "lutas" : "dashboard");
}

async function loadDashboard() {
  const [students, situation] = await Promise.all([
    api("/alunos"),
    api("/alunos/situacao"),
  ]);
  state.students = students;
  await loadOperationStatus();

  const activeCount = students.filter((student) => student.status === "ativo").length;
  const alertCount = situation.filter((row) => Boolean(row.alerta)).length;
  const stats = [
    ["Alunos cadastrados", students.length, "users"],
    ["Alunos ativos", activeCount, "check"],
    ["Com alerta", alertCount, "alert"],
  ];
  const statsBox = $("#dashboard-stats");
  statsBox.replaceChildren(...stats.map(([label, value, symbol]) => {
    const card = element("article", undefined, "stat-card");
    const title = element("div", undefined, "stat-card-title");
    title.append(element("p", traduzir(label)), element("span", undefined, `stat-icon stat-icon-${symbol}`));
    title.lastElementChild.append(icon(symbol));
    card.append(title, element("strong", value));
    return card;
  }));

  const visualBox = $("#dashboard-visuals");
  if (visualBox) {
    const total = students.length;
    const active = students.filter((student) => student.status === "ativo").length;
    const alerts = situation.filter((row) => Boolean(row.alerta)).length;
    const metrics = [
      ["Fluxo acompanhado", active, total ? Math.round((active / total) * 100) : 0, "icon-access"],
      ["Cadastros", total, Math.min(100, total * 10), "icon-users"],
      ["Atenção necessária", alerts, total ? Math.round((alerts / total) * 100) : 0, "icon-alert"],
    ];
    visualBox.replaceChildren(...metrics.map(([label, value, percent, symbol]) => {
      const card = element("article", undefined, "insight-card");
      const heading = element("div", undefined, "insight-heading");
      heading.append(element("span", traduzir(label)), icon(symbol));
      const valueLine = element("div", undefined, "insight-value");
      valueLine.append(element("strong", value), element("small", `${percent}%`));
      const track = element("div", undefined, "insight-track");
      const fill = element("span", undefined, "insight-fill");
      fill.style.width = `${percent}%`;
      track.append(fill);
      card.append(heading, valueLine, track);
      return card;
    }));
  }

  const list = $("#dashboard-list");
  if (!situation.length) {
    list.className = "list-empty";
    list.textContent = traduzir("Ainda não há alunos para exibir.");
    return;
  }
  list.className = "table-wrap";
  const table = element("table");
  const head = element("thead");
  const headerRow = element("tr");
  ["Aluno", "Situação", "Dias restantes", "Alerta"].forEach((title) => headerRow.append(element("th", traduzir(title))));
  head.append(headerRow);
  const body = element("tbody");
  situation.forEach((row) => {
    const tr = element("tr");
    tr.append(element("td", row.nome), element("td", traduzir(statusLabels[row.status_aluno] || row.status_aluno || "—")));
    tr.append(element("td", row.dias_restantes ?? "—"));
    const alert = element("td");
    const alertLabel = statusLabels[row.alerta] || row.alerta || "Sem alerta";
    const alertTone = row.alerta === "atrasado"
      ? "bad"
      : row.alerta && row.alerta !== "em_dia" ? "warn" : "good";
    alert.append(badge(alertLabel, alertTone));
    tr.append(alert);
    body.append(tr);
  });
  table.append(head, body);
  list.replaceChildren(table);
}

function operationStatusLabel(value) {
  const labels = {
    conectado: "Conectado",
    disponivel: "Disponível",
    desativado: "Desativado",
    nunca_executado: "Nunca executado",
    sucesso: "Concluído",
    falha: "Falhou",
    incompleto: "Incompleto",
    indisponivel: "Indisponível",
    gerenciado_pela_plataforma: "Feito pela Frequency",
  };
  return traduzir(labels[value] || value || "Indisponível");
}

async function loadOperationStatus() {
  const boxes = [$("#operation-status"), $("#backup-page-status")].filter(Boolean);
  if (!boxes.length || !["admin_plataforma", "dono"].includes(state.user?.papel)) return;
  try {
    const status = await api("/operacao/status");
    const basicRows = [
      ["Banco", operationStatusLabel(status.banco)],
      ["Sincronização", status.sincronizacao?.envio_ativado ? traduzir("Disponível") : traduzir("Desativado")],
    ];
    const detailedRows = [...basicRows,
      ["Backup", operationStatusLabel(status.backup?.status)],
      ["Destino", status.backup?.provedor === "local" ? traduzir("Neste computador") : status.backup?.provedor === "plataforma" ? traduzir("Servidor Frequency") : (status.backup?.provedor || traduzir("Indisponível"))],
      ["Agendamento", status.backup?.agendamento_diario ? traduzir("Diário") : traduzir("Desativado")],
    ];
    boxes.forEach((box) => {
      const rows = box.id === "operation-status" ? basicRows : detailedRows;
      box.replaceChildren();
      rows.forEach(([label, value]) => {
        const row = element("div", undefined, "operation-status-row");
        row.append(element("span", traduzir(label)), element("strong", value));
        box.append(row);
      });
      if (box.id !== "operation-status" && status.backup?.ultima_execucao) box.append(element("small", `${traduzir("Última execução")}: ${status.backup.ultima_execucao}`, "field-help"));
      if (box.id !== "operation-status" && Number.isInteger(status.backup?.arquivos_pendentes) && status.backup.arquivos_pendentes > 0) box.append(element("small", `${traduzir("Arquivos pendentes")}: ${status.backup.arquivos_pendentes}`, "field-help"));
    });
  } catch (error) {
    boxes.forEach((box) => box.replaceChildren(element("span", error.message || traduzir("Não foi possível concluir a solicitação. Tente novamente."), "page-error")));
  }
}


$("#sync-pairing-start")?.addEventListener("click", async () => {
  const output = $("#sync-pairing-code");
  try { const result = await api("/sync/pairing/start", { method: "POST" }); if (output) output.textContent = `Código: ${result.codigo} (válido por ${result.validade_minutos} min)`; }
  catch (error) { if (output) output.textContent = error.message || "Não foi possível gerar o código."; }
});
$("#sync-pairing-connect-form")?.addEventListener("submit", async (event) => {
  event.preventDefault(); const status = $("#sync-pairing-status");
  try { await api("/sync/conectar", { method: "POST", body: { codigo: $("#sync-pairing-code-input")?.value || "" } }); if (status) status.textContent = "Instalação conectada. A sincronização será enviada automaticamente."; await loadOperationStatus(); }
  catch (error) { if (status) status.textContent = error.message || "Não foi possível conectar."; }
});
async function loadBackupPage() {
  const config = backupConfig = await api("/operacao/backup-config");
  const input = $("#backup-destination");
  if (input && !input.value) input.value = config.destino || "";
  const folderChooser = $("#backup-choose-folder");
  const folderStatus = $("#backup-destination-status");
  const nativeFolderPickerAvailable = config.seletor_pasta_disponivel !== false;
  // O picker nativo do servidor é apenas uma opção. Em qualquer dispositivo,
  // o usuário pode baixar o arquivo criptografado pelo navegador.
  if (folderChooser) folderChooser.hidden = false;
  if (folderStatus && !nativeFolderPickerAvailable && frequencyDeviceClass === "desktop") {
    folderStatus.textContent = traduzir("O seletor nativo do servidor não está disponível; use o download da cópia criptografada.");
  }
  const cloud = $("#backup-google-status");
  if (cloud) cloud.textContent = config.nuvem?.google_drive?.disponivel ? traduzir("Disponível") : traduzir("Não configurado");
  const cloudCopy = $("#backup-google-copy");
  const driveAvailable = Boolean(config.nuvem?.google_drive?.disponivel);
  const mobileCloud = frequencyDeviceClass !== "desktop";
  if (cloudCopy) {
    cloudCopy.textContent = mobileCloud
      ? driveAvailable
        ? traduzir("O Google Drive do computador que hospeda o Frequency está disponível. Para enviar à sua conta neste dispositivo, use Compartilhar.")
        : traduzir("No celular ou tablet, baixe a cópia e use Compartilhar para enviá-la ao aplicativo Google Drive.")
      : driveAvailable
        ? traduzir("Google Drive detectado no computador que hospeda o Frequency. O próximo backup será salvo na pasta sincronizada.")
        : traduzir("Instale o Google Drive para computador neste equipamento ou baixe a cópia criptografada para enviá-la manualmente.");
  }
  const download = $("#backup-google-download");
  if (download) {
    download.hidden = driveAvailable && !mobileCloud;
    if (mobileCloud) {
      download.href = "https://drive.google.com/drive/my-drive";
      download.textContent = traduzir("Abrir Google Drive");
    }
  }
  const cloudButton = $("#backup-google-login");
  if (cloudButton) {
    cloudButton.hidden = !driveAvailable && !mobileCloud;
    cloudButton.textContent = mobileCloud ? traduzir("Compartilhar última cópia") : traduzir("Usar pasta sincronizada");
  }
  await loadOperationStatus();
}

async function fetchLatestBackupArchive() {
  const headers = new Headers({ Accept: "application/octet-stream", "X-Frequency-Device-Class": frequencyDeviceClass });
  if (state.token) headers.set("Authorization", "Bearer " + state.token);
  const response = await fetchFrequency("/operacao/backup/download", { headers, cache: "no-store" });
  if (!response.ok) {
    let detail = null;
    try { detail = await response.json(); } catch { /* Binary endpoint may not return JSON. */ }
    const error = new Error(response.status === 404 ? traduzir("Nenhum backup criptografado foi encontrado nesta instalação.") : apiMessage(detail?.detail));
    error.detail = detail?.detail;
    error.status = response.status;
    throw error;
  }
  const blob = await response.blob();
  const disposition = response.headers.get("content-disposition") || "";
  const filename = /filename="?([^";]+)"?/i.exec(disposition)?.[1] || "frequency-backup.dump.age";
  return { blob, filename };
}

async function ensureLatestBackupArchive() {
  try {
    return await fetchLatestBackupArchive();
  } catch (error) {
    if (error?.status !== 404) throw error;
  }
  try {
    await api("/operacao/backup", { method: "POST" });
  } catch (error) {
    if (error?.detail !== "backup_em_andamento") throw error;
  }
  showNotice(traduzir("Preparando a cópia criptografada…"));

  for (let attempt = 0; attempt < 60; attempt += 1) {
    await new Promise((resolve) => setTimeout(resolve, 1000));
    try {
      return await fetchLatestBackupArchive();
    } catch (error) {

      if (error?.status !== 404) throw error;
    }
  }
  throw new Error(traduzir("O backup demorou para ficar disponível. Atualize o estado e tente novamente."));
}
function triggerBrowserDownload(blob, filename) {
  const url = URL.createObjectURL(blob);
  const link = document.createElement("a");
  link.href = url;
  link.download = filename;
  link.rel = "noopener";
  document.body.append(link);
  link.click();
  link.remove();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
}

async function saveBackupBlob(blob, filename) {
  if (state.backupDirectoryHandle) {
    const fileHandle = await state.backupDirectoryHandle.getFileHandle(filename, { create: true });
    const writable = await fileHandle.createWritable();
    await writable.write(blob);
    await writable.close();
    showNotice(traduzir("Backup salvo na pasta escolhida."));
    return;
  }
  triggerBrowserDownload(blob, filename);
  showNotice(traduzir("Backup baixado para este dispositivo."));
}

async function downloadLatestBackup() {
  const { blob, filename } = await ensureLatestBackupArchive();
  await saveBackupBlob(blob, filename);
}

async function shareLatestBackupToDevice() {
  const { blob, filename } = await ensureLatestBackupArchive();
  if (typeof File !== "function") {
    triggerBrowserDownload(blob, filename);
    showNotice(traduzir("Backup baixado. Abra o menu Compartilhar para salvar em Arquivos ou Downloads."));
    return;
  }
  const file = new File([blob], filename, { type: "application/octet-stream" });
  let canShareFile = false;
  try { canShareFile = Boolean(navigator.share && navigator.canShare?.({ files: [file] })); } catch { canShareFile = false; }
  if (canShareFile) {
    await navigator.share({ files: [file], title: "Salvar backup Frequency", text: "Escolha Salvar em Arquivos, Files, Downloads ou Google Drive." });
    showNotice(traduzir("Escolha Arquivos, Files, Downloads ou Google Drive para salvar a cópia."));
    return;
  }
  triggerBrowserDownload(blob, filename);
  showNotice(traduzir("Backup baixado. Abra o menu Compartilhar para salvar em Arquivos ou Downloads."));
}

async function shareLatestBackupToCloud() {
  const { blob, filename } = await fetchLatestBackupArchive();
  if (typeof File !== "function") {
    triggerBrowserDownload(blob, filename);
    showNotice(traduzir("Backup baixado. Use Compartilhar para enviá-lo ao Google Drive."));
    return;
  }
  const file = new File([blob], filename, { type: "application/octet-stream" });
  let canShareFile = false;
  try { canShareFile = Boolean(navigator.share && navigator.canShare?.({ files: [file] })); } catch { canShareFile = false; }
  if (canShareFile) {
    await navigator.share({ files: [file], title: "Backup Frequency", text: "Cópia criptografada do Frequency." });
    showNotice(traduzir("Cópia compartilhada. Escolha o Google Drive ou outro destino na janela do dispositivo."));
    return;
  }
  triggerBrowserDownload(blob, filename);
  showNotice(traduzir("Backup baixado. Use Compartilhar para enviá-lo ao Google Drive."));
}

const prospectingStatusLabels = {
  nao_contatado: "Não contatado", mensagem_enviada: "Mensagem enviada", respondeu: "Respondeu",
  demonstracao: "Demonstração", interessado: "Interessado", cliente: "Cliente", nao_interessado: "Não interessado",
};

function prospectingFilters() {
  const params = new URLSearchParams();
  const prioridade = $("#prospecting-priority-filter")?.value;
  const status = $("#prospecting-status-filter")?.value;
  const cidade = $("#prospecting-city-filter")?.value.trim();
  if (prioridade) params.set("prioridade", prioridade);
  if (status) params.set("status", status);
  if (cidade) params.set("cidade", cidade);
  const query = params.toString();
  return query ? `?${query}` : "";
}

function prospectingTone(status) {
  if (status === "cliente") return "good";
  if (["nao_interessado"].includes(status)) return "bad";
  if (["respondeu", "demonstracao", "interessado"].includes(status)) return "warn";
  return "";
}

function renderProspecting(data) {
  state.prospectingLeads = data.leads || [];
  const funnel = data.funil || {};
  const cards = [
    ["Total", funnel.total || 0], ["Prioridade A", funnel.prioridade_a || 0],
    ["Contatados", funnel.mensagem_enviada || 0], ["Demonstrações", funnel.demonstracao || 0],
    ["Interessados", funnel.interessado || 0], ["Clientes", funnel.cliente || 0],
  ];
  $("#prospecting-funnel").replaceChildren(...cards.map(([label, value]) => {
    const card = element("article", null, "prospecting-meter");
    card.append(element("span", traduzir(label)), element("strong", String(value)));
    return card;
  }));
  const body = $("#prospecting-leads");
  $("#prospecting-empty").hidden = state.prospectingLeads.length > 0;
  body.replaceChildren(...state.prospectingLeads.map((lead) => {
    const row = element("tr");
    const academy = element("td"); const select = element("input"); select.type = "checkbox"; select.className = "prospecting-lead-select"; select.dataset.prospectingSelect = String(lead.id); academy.prepend(select);
    academy.append(element("strong", lead.nome), element("small", lead.cidade || "—", "muted"));
    const contact = element("td");
    contact.append(element("span", lead.email || "Sem e-mail"), element("small", lead.telefone || "Sem WhatsApp", "muted"));
    const priority = element("td"); priority.append(badge(lead.prioridade, lead.prioridade === "A" ? "warn" : ""));
    const status = element("td"); status.append(badge(prospectingStatusLabels[lead.status_comercial] || lead.status_comercial, prospectingTone(lead.status_comercial)));
    const actions = element("td", null, "table-actions");
    const email = element("button", "Preparar e-mail", "button button-secondary button-small");
    email.type = "button"; email.dataset.prospectingEmail = String(lead.id); email.disabled = !lead.email;
    const whatsapp = element("button", "Enviar WhatsApp", "button button-quiet button-small");
    whatsapp.type = "button"; whatsapp.dataset.prospectingWhatsapp = String(lead.id); whatsapp.disabled = !lead.telefone || !lead.whatsapp_opt_in;
    const edit = element("button", "Editar", "button button-quiet button-small");
    edit.type = "button"; edit.dataset.prospectingEdit = String(lead.id);
    const remove = element("button", "Excluir", "button button-danger button-small");
    remove.type = "button"; remove.dataset.prospectingDelete = String(lead.id);
    actions.append(email, whatsapp, edit, remove);
    row.append(academy, contact, priority, status, element("td", lead.ultimo_contato || "—"), actions);
    return row;
  }));
}

function selectedProspectingLeads() { const ids = [...document.querySelectorAll("[data-prospecting-select]:checked")].map((input) => String(input.dataset.prospectingSelect)); return state.prospectingLeads.filter((lead) => ids.includes(String(lead.id))); }
function updateProspectingSelection() { const selected = selectedProspectingLeads(); $("#prospecting-selection-count").textContent = `${selected.length} selecionados`; $("#prospecting-bulk-whatsapp").disabled = selected.length === 0; $("#prospecting-bulk-email").disabled = selected.length === 0; }

async function loadProspectingRegions() {
  const box = $("#prospecting-regions"); if (!box) return;
  const regions = await api("/admin/prospeccao/regioes");
  box.replaceChildren(...(regions || []).map((region) => {
    const row = element("div", null, "list-row");
    const info = element("div"); info.append(element("strong", region.nome), element("small", `${region.pais} · ${region.cidade} · ${region.raio_metros} m`, "muted"));
    const button = element("button", "Buscar agora", "button button-secondary button-small"); button.type = "button"; button.dataset.prospectingRegionSearch = String(region.id); button.disabled = !region.ativa;
    const apify = element("button", "Buscar no Apify", "button button-secondary button-small"); apify.type = "button"; apify.dataset.prospectingApifySearch = String(region.id); apify.disabled = !region.ativa; row.append(info, button, apify); return row;
  }));
}
async function criarRegiaoProspeccao(event) {
  event.preventDefault(); const form = event.currentTarget; const values = Object.fromEntries(new FormData(form));
  await api("/admin/prospeccao/regioes", { method: "POST", body: { ...values, latitude: values.latitude ? Number(values.latitude) : null, longitude: values.longitude ? Number(values.longitude) : null, raio_metros: Number(values.raio_metros), ativa: true } });
  form.reset(); form.elements.raio_metros.value = "5000"; await loadProspectingRegions(); showNotice("Região salva.");
}
async function loadProspectingGmailStatus() {
  const target = $("#prospecting-gmail-status");
  if (!target) return;
  try {
    const result = await api("/admin/prospeccao/gmail");
    target.textContent = result.conectado ? `Gmail conectado: ${result.email}` : "Gmail comercial não conectado.";
  } catch (error) {
    target.textContent = error.message || "Não foi possível verificar o Gmail.";
  }
}
async function loadProspecting() {
  const [data, configuration] = await Promise.all([
    api("/admin/prospeccao/leads" + prospectingFilters()),
    api("/admin/prospeccao/configuracao"),
  ]);
  renderProspecting(data);
  state.prospectingConfig = configuration;
  const templateForm = $("#prospecting-template-form");
  ["whatsapp_template", "email_assunto_template", "email_corpo_template"].forEach((field) => {
    if (templateForm.elements[field]) templateForm.elements[field].value = configuration[field] || "";
  });
  await loadProspectingImage(configuration.imagem_cadastrada);
  await loadProspectingRegions();
  await loadProspectingGmailStatus();
}

async function loadProspectingImage(imageRegistered) {
  const image = $("#prospecting-campaign-image");
  const empty = $("#prospecting-campaign-image-empty");
  const open = $("#prospecting-open-image");
  if (state.prospectingImageUrl) URL.revokeObjectURL(state.prospectingImageUrl);
  state.prospectingImageUrl = null;
  image.removeAttribute("src"); image.hidden = true; empty.hidden = false; open.hidden = true;
  if (!imageRegistered) return;
  const response = await fetchFrequency("/admin/prospeccao/imagem", {
    headers: { Authorization: `Bearer ${state.token}`, Accept: "image/*" },
  });
  if (!response.ok) throw new Error("Não foi possível carregar a imagem comercial.");
  state.prospectingImageUrl = URL.createObjectURL(await response.blob());
  image.src = state.prospectingImageUrl; image.hidden = false; empty.hidden = true; open.hidden = false;
}

function resetProspectingForm() {
  const form = $("#prospecting-form");
  form.reset();
  $("#prospecting-lead-id").value = "";
  $("#prospecting-form-title").textContent = traduzir("Novo lead");
  $("#prospecting-cancel-edit").hidden = true;
}

function editProspectingLead(lead) {
  const form = $("#prospecting-form");
  for (const field of ["nome", "cidade", "endereco", "telefone", "email", "site_instagram", "avaliacao", "prioridade", "status_comercial", "ultimo_contato", "observacoes"]) {
    if (form.elements[field]) form.elements[field].value = lead[field] ?? "";
  }
  if (form.elements.whatsapp_opt_in) form.elements.whatsapp_opt_in.checked = Boolean(lead.whatsapp_opt_in);
  $("#prospecting-lead-id").value = String(lead.id);
  $("#prospecting-form-title").textContent = traduzir("Editar lead");
  $("#prospecting-cancel-edit").hidden = false;
  form.scrollIntoView({ behavior: "smooth", block: "start" });
  form.elements.nome.focus();
}

function openProspectingEmail(lead) {
  if (!lead.email) throw new Error("Cadastre um e-mail para este lead.");
  const mailtoUrl = `mailto:${encodeURIComponent(lead.email)}?subject=${encodeURIComponent(lead.email_assunto)}&body=${encodeURIComponent(lead.email_corpo)}`;
  window.location.href = mailtoUrl;
}

function openProspectingWhatsApp(lead) {
  const phone = String(lead.telefone || "").replace(/\D/g, "");
  if (!phone) throw new Error("Cadastre um telefone para este lead.");
  if (!lead.whatsapp_opt_in) throw new Error("Este lead ainda não autorizou contato por WhatsApp.");
  const message = lead.whatsapp_mensagem || "";
  const url = `https://wa.me/${phone}?text=${encodeURIComponent(message)}`;
  const opened = window.open(url, "_blank", "noopener,noreferrer");
  if (!opened) throw new Error("O navegador bloqueou a nova aba. Permita pop-ups para o Frequency.");
  showNotice("WhatsApp aberto com a mensagem preparada. Revise e clique em Enviar.");
}

async function enviarProspeccaoSelecionados(canal, button) {
  const leads = selectedProspectingLeads();
  if (!leads.length) return;
  button.disabled = true;
  try {
    const result = await api("/admin/prospeccao/enviar", { method: "POST", body: { lead_ids: leads.map((lead) => lead.id), canal } });
    const firstFailure = result.falhas?.[0]?.erro;
    const detail = firstFailure ? ` Motivo: ${firstFailure}.` : "";
    showNotice(`${result.enviados.length} enviado(s) em ordem; ${result.ignorados.length} ignorado(s); ${result.falhas.length} falha(s).${detail}`, Boolean(result.falhas?.length));
    await loadProspecting();
  } catch (error) { showNotice(error.message, true); } finally { button.disabled = false; }
}

function parseProspectingCsv(text) {
  const lines = text.replace(/^\uFEFF/, "").split(/\r?\n/).filter((line) => line.trim());
  if (lines.length < 2) throw new Error("O CSV precisa ter cabeçalho e pelo menos um lead.");
  const separator = lines[0].includes(";") ? ";" : ",";
  const parseRow = (line) => {
    const values = []; let value = ""; let quoted = false;
    for (let index = 0; index < line.length; index += 1) {
      const char = line[index];
      if (char === '"' && line[index + 1] === '"') { value += '"'; index += 1; }
      else if (char === '"') quoted = !quoted;
      else if (char === separator && !quoted) { values.push(value.trim()); value = ""; }
      else value += char;
    }
    values.push(value.trim());
    return values;
  };
  const aliases = { nome: "nome", name: "nome", cidade: "cidade", city: "cidade", endereco: "endereco", endereço: "endereco", telefone: "telefone", phone: "telefone", whatsapp: "telefone", email: "email", "e-mail": "email", site_instagram: "site_instagram", site: "site_instagram", instagram: "site_instagram", avaliacao: "avaliacao", avaliação: "avaliacao", rating: "avaliacao", prioridade: "prioridade", status_comercial: "status_comercial", status: "status_comercial", observacoes: "observacoes", observações: "observacoes" };
  const headers = parseRow(lines[0]).map((header) => aliases[header.toLocaleLowerCase("pt-BR").trim()] || "");
  const leads = lines.slice(1).map(parseRow).map((row) => {
    const lead = { prioridade: "C", status_comercial: "nao_contatado" };
    row.forEach((value, index) => { if (headers[index] && value) lead[headers[index]] = value; });
    if (lead.avaliacao) lead.avaliacao = Number(String(lead.avaliacao).replace(",", "."));
    return lead;
  }).filter((lead) => lead.nome);
  if (!leads.length) throw new Error("Nenhuma linha com a coluna nome foi encontrada.");
  return leads;
}

async function loadFrequencyPlans() {
  const plans = await api("/admin/frequency/planos");
  const list = $("#frequency-plans");
  if (!list) return;
  const labels = { essencial: "Essencial", profissional: "Profissional", premium: "Premium" };
  list.replaceChildren(...plans.map((plan) => {
    const card = element("article", undefined, "plan-card");
    const heading = element("div", undefined, "panel-heading");
    heading.append(element("h2", plan.nome));
    heading.append(badge(plan.ativo ? "Ativo" : "Inativo", plan.ativo ? "good" : "bad"));
    card.append(heading);
    card.append(element("p", traduzir(labels[plan.nivel] || plan.nivel || "Essencial"), "plan-category"));
    card.append(element("p", formatMoney(plan.valor, plan.moeda), "plan-price"));
    card.append(element("p", `${plan.duracao_dias} ${traduzir("dias")}`, "plan-duration"));
    card.append(element("p", `Limites: ${Number(plan.max_alunos || 0).toLocaleString("pt-BR")} alunos · ${plan.max_monitores || 0} computadores/telas · ${plan.max_leitores || 0} leitores`, "muted"));
    if (plan.descricao) card.append(element("p", plan.descricao, "muted"));
    const extras = [];
    if (plan.cameras) extras.push(traduzir("Câmeras de segurança"));
    if (plan.youtube) extras.push(traduzir("Controle do YouTube"));
    if (extras.length) card.append(element("p", extras.join(" · "), "plan-features"));
    if (!state.config.somente_consulta) {
      const action = element("button", traduzir(plan.ativo ? "Desativar" : "Ativar"), plan.ativo ? "button button-quiet button-small" : "button button-secondary button-small");
      action.type = "button";
      action.dataset.frequencyPlanStatus = String(plan.id);
      action.dataset.active = String(plan.ativo);
      card.append(action);
    }
    return card;
  }));
}

const NOMES_GRUPO = { peito: "Peito", costas: "Costas", ombros: "Ombros", biceps: "Bíceps", triceps: "Tríceps", antebraco: "Antebraço", abdomen: "Abdômen", lombar: "Lombar", quadriceps: "Quadríceps", posteriores: "Posteriores", gluteos: "Glúteos", panturrilhas: "Panturrilhas" };

async function loadExercises() {
  state.exercises = await api("/academia/exercicios");
  const select = $("#exercises-group");
  const form = $("#exercise-form-group");
  if (select.options.length <= 1) {
    state.exercises.grupos.forEach((g) => { select.add(new Option(traduzir(NOMES_GRUPO[g.grupo] || g.grupo), g.grupo)); form.add(new Option(traduzir(NOMES_GRUPO[g.grupo] || g.grupo), g.grupo)); });
  }
  renderExercises();
}

function renderExercises() {
  const dados = state.exercises; if (!dados) return;
  const resumo = $("#exercises-summary");
  resumo.replaceChildren(...dados.grupos.map((g) => {
    const chip = element("span", `${traduzir(NOMES_GRUPO[g.grupo] || g.grupo)}: ${g.ativos}/${g.total}`, g.aviso ? "badge badge-warn" : "badge badge-good");
    if (g.aviso) chip.title = traduzir("Menos de 10 exercícios ativos neste grupo.");
    return chip;
  }));
  const busca = $("#exercises-search").value.trim().toLowerCase();
  const grupo = $("#exercises-group").value;
  const itens = dados.exercicios.filter((e) => (!grupo || e.grupo === grupo) && (!busca || e.nome.toLowerCase().includes(busca)));
  $("#exercises-empty").hidden = itens.length > 0;
  const tabela = element("table", undefined, "table");
  const cab = element("thead"); const linhaCab = element("tr");
  ["Exercício", "Grupo", "Origem", "Aparece para o aluno"].forEach((t) => linhaCab.append(element("th", traduzir(t))));
  cab.append(linhaCab); tabela.append(cab);
  const corpo = element("tbody");
  itens.forEach((e) => {
    const linha = element("tr");
    linha.append(element("td", e.nome), element("td", traduzir(NOMES_GRUPO[e.grupo] || e.grupo)), element("td", traduzir(e.origem === "catalogo" ? "Catálogo Frequency" : "Sua academia")));
    const celula = element("td");
    const botao = element("button", traduzir(e.oculto ? "Oculto — ativar" : "Ativo — ocultar"), "button button-secondary button-small");
    botao.type = "button"; botao.dataset.syncWrite = "";
    botao.addEventListener("click", async () => {
      botao.disabled = true;
      try { await alternarExercicio(e); } catch (erro) { showNotice(erro.message, true); } finally { botao.disabled = false; }
    });
    celula.append(botao); linha.append(celula); corpo.append(linha);
  });
  tabela.append(corpo);
  $("#exercises-list").replaceChildren(tabela);
}

async function alternarExercicio(e) {
  if (e.origem === "catalogo") {
    await api(`/academia/exercicios/${encodeURIComponent(e.ref.slice(2))}/visibilidade`, { method: "PUT", body: { oculto: !e.oculto } });
  } else if (e.oculto) {
    await api(`/academia/exercicios/${e.ref.slice(2)}`, { method: "PATCH", body: { ativo: true } });
  } else {
    await api(`/academia/exercicios/${e.ref.slice(2)}`, { method: "DELETE" });
  }
  await loadExercises();
}

$("#exercises-search")?.addEventListener("input", renderExercises);
$("#exercises-group")?.addEventListener("change", renderExercises);
$("#exercise-form")?.addEventListener("submit", async (event) => {
  event.preventDefault();
  const form = event.currentTarget; const dados = new FormData(form);
  try {
    await api("/academia/exercicios", { method: "POST", body: { nome: String(dados.get("nome") || "").trim(), grupo: dados.get("grupo"), equipamento: String(dados.get("equipamento") || "").trim(), tempo: dados.get("tempo") === "on" } });
    form.reset(); showNotice("Exercício adicionado."); await loadExercises();
  } catch (erro) { showNotice(erro.message, true); }
});

async function loadKiosks() {
  const dados = await api("/academia/quiosques");
  $("#kiosk-status").replaceChildren(element("span", traduzir(dados.recurso_ligado ? "Quiosque ativo para esta academia." : "O quiosque ainda não está ligado para esta academia. Fale com o suporte Frequency."), dados.recurso_ligado ? "badge badge-good" : "badge badge-warn"));
  $("#kiosk-form").hidden = !dados.recurso_ligado;
  $("#kiosk-empty").hidden = dados.quiosques.length > 0;
  const tabela = element("table", undefined, "table");
  const cab = element("thead"); const lc = element("tr");
  ["Nome", "Estado", "Último uso", ""].forEach((t) => lc.append(element("th", traduzir(t))));
  cab.append(lc); tabela.append(cab);
  const corpo = element("tbody");
  dados.quiosques.forEach((q) => {
    const linha = element("tr");
    linha.append(element("td", q.nome), element("td", traduzir(q.ativo ? "Ativo" : "Revogado")), element("td", q.ultimo_uso ? new Date(q.ultimo_uso).toLocaleString() : "—"));
    const celula = element("td");
    if (q.ativo) {
      const botao = element("button", traduzir("Revogar"), "button button-secondary button-small");
      botao.type = "button"; botao.dataset.syncWrite = "";
      botao.addEventListener("click", async () => {
        if (!confirm(traduzir("Revogar este quiosque? O tablet para de funcionar na hora."))) return;
        try { await api(`/academia/quiosques/${q.id}`, { method: "DELETE" }); await loadKiosks(); } catch (erro) { showNotice(erro.message, true); }
      });
      celula.append(botao);
    }
    linha.append(celula); corpo.append(linha);
  });
  tabela.append(corpo);
  $("#kiosk-list").replaceChildren(tabela);
}

$("#kiosk-form")?.addEventListener("submit", async (event) => {
  event.preventDefault();
  const form = event.currentTarget; const dados = new FormData(form);
  try {
    const r = await api("/academia/quiosques", { method: "POST", body: { nome: String(dados.get("nome") || "").trim() } });
    form.reset();
    $("#kiosk-token").textContent = r.token; $("#kiosk-token-box").hidden = false;
    await loadKiosks();
  } catch (erro) { showNotice(erro.message, true); }
});

async function loadPlans() {
  state.plans = await api("/planos");
  const select = $("#student-plan");
  const selected = select.value;
  select.replaceChildren(new Option(traduzir("Sem plano"), ""));
  state.plans.forEach((plan) => select.add(new Option(`${plan.nome} · ${formatMoney(plan.valor, plan.moeda)}`, plan.id)));
  if (state.plans.some((plan) => String(plan.id) === selected)) select.value = selected;

  const list = $("#plans-list");
  const empty = $("#plans-empty");
  empty.hidden = state.plans.length > 0;
  list.replaceChildren(...state.plans.map((plan) => {
    const card = element("article", undefined, "plan-card");
    card.append(element("h2", plan.nome));
    card.append(element("p", formatMoney(plan.valor, plan.moeda), "plan-price"));
    card.append(element("p", `${plan.duracao_dias} ${traduzir("dias")}`, "plan-duration"));
    if (state.user?.papel === "dono") {
      const remove = element("button", "Apagar plano", "button button-quiet button-small");
      remove.type = "button";
      remove.dataset.deletePlan = String(plan.id);
      card.append(remove);
    }
    return card;
  }));
}

function renderStudents() {
  const query = $("#student-search").value.trim().toLocaleLowerCase(state.user?.idioma || interfaceLocale);
  const students = state.students.filter((student) => {
    if (!query) return true;
    return [student.nome, student.documento, student.bairro].some((value) =>
      String(value || "").toLocaleLowerCase(state.user?.idioma || interfaceLocale).includes(query)
    );
  });
  const body = $("#students-table");
  body.replaceChildren(...students.map((student) => {
    const row = element("tr");
    row.append(element("td", student.nome), element("td", student.documento), element("td", student.bairro || "—"));
    row.append(element("td", student.plano || traduzir("Sem plano")));
    const status = element("td");
    status.append(badge(statusLabels[student.status] || student.status || "—", student.status === "ativo" ? "good" : "warn"));
    row.append(status);
    const actions = element("td", undefined, "table-actions");
    if (student.plano_id || !state.config.somente_consulta) {
      const planAction = element(
        "button",
        traduzir(student.plano_id ? "Pagamentos" : "Selecionar plano"),
        "button button-quiet button-small",
      );
      planAction.type = "button";
      if (student.plano_id) planAction.dataset.studentPayments = String(student.id);
      else planAction.dataset.selectPlan = String(student.id);
      actions.append(planAction);
    }
    if (["dono", "recepcao"].includes(state.user?.papel) && !state.config.somente_consulta) {
      const editButton = element("button", traduzir("Editar"), "button button-secondary button-small");
      editButton.type = "button";
      editButton.dataset.editStudent = String(student.id);
      actions.append(editButton);
    }
    if (state.user?.papel === "dono" && !state.config.somente_consulta) {
      const active = student.status === "ativo";
      const statusButton = element(
        "button",
        traduzir(active ? "Desativar" : "Ativar"),
        active ? "button button-danger button-small" : "button button-secondary button-small",
      );
      statusButton.type = "button";
      statusButton.dataset.toggleStudent = String(student.id);
      statusButton.dataset.active = String(active);
      actions.append(statusButton);
    }
    row.append(actions);
    return row;
  }));
  $("#students-count").textContent = query
    ? `${students.length}/${state.students.length}`
    : String(state.students.length);
  $("#students-empty").hidden = state.students.length > 0;
  $("#students-no-results").hidden = !query || students.length > 0 || !state.students.length;
}

function renderRegionMap(data) {
  const rows = Array.isArray(data?.bairros) ? data.bairros : [];
  const host = $("#student-region-map");
  const empty = $("#region-map-empty");
  if (!host || !empty) return;
  const max = Math.max(1, ...rows.map((row) => Number(row.total || 0)));
  host.replaceChildren(...rows.map((row, index) => {
    const total = Number(row.total || 0);
    const item = element("article", null, "region-map-row");
    const head = element("div", null, "region-map-row-heading");
    head.append(element("strong", row.bairro || traduzir("Sem bairro informado")), element("span", String(total)));
    const track = element("div", null, "region-map-track");
    const fill = element("span", null, "region-map-fill");
    fill.style.width = Math.max(6, (total / max) * 100) + "%";
    track.append(fill);
    item.append(head, track, element("small", total === 1 ? traduzir("aluno ativo") : traduzir("alunos ativos"), "muted"));
    item.setAttribute("role", "listitem");
    item.style.setProperty("--region-order", String(index));
    return item;
  }));
  empty.hidden = rows.length > 0;
}
async function loadRegionMap() {
  const data = await api("/alunos/mapa-regiao");
  const rows = Array.isArray(data.bairros) ? data.bairros : [];
  const known = rows.filter((row) => row.bairro !== "Sem bairro informado");
  const top = known[0] || rows[0];
  const area = [data.regiao?.cidade, data.regiao?.estado].filter(Boolean).join(" · ");
  $("#region-map-area").textContent = area || traduzir("Região da academia");
  statCards("#region-map-stats", [["Alunos ativos", data.total_alunos || 0, "users"], ["Bairros mapeados", known.length, "building"], ["Maior concentração", top ? top.bairro : "—", "chart"]]);
  $("#region-map-description").textContent = area
    ? traduzir("Alunos ativos agrupados pelo bairro informado no cadastro.") + " " + traduzir("Região") + ": " + area + "."
    : traduzir("Alunos ativos agrupados pelo bairro informado no cadastro.");
  renderRegionMap(data);
}

async function loadStudents() {
  const [students, plans] = await Promise.all([api("/alunos"), api("/planos")]);
  state.students = students;
  state.plans = plans;
  const planSelect = $("#student-plan");
  const currentPlan = planSelect.value;
  planSelect.replaceChildren(new Option(traduzir("Sem plano"), ""));
  plans.forEach((plan) => planSelect.add(new Option(`${plan.nome} · ${formatMoney(plan.valor, plan.moeda)}`, plan.id)));
  if (plans.some((plan) => String(plan.id) === currentPlan)) planSelect.value = currentPlan;

  const paymentsSelect = $("#payment-student");
  const currentStudent = paymentsSelect.value;
  paymentsSelect.replaceChildren(new Option(traduzir("Todos os alunos"), ""));
  students.forEach((student) => paymentsSelect.add(new Option(student.nome, student.id)));
  if (students.some((student) => String(student.id) === currentStudent)) paymentsSelect.value = currentStudent;

  renderStudents();

  await loadPayments(paymentsSelect.value);
}

async function loadPayments(studentId = "", filter = $("#payment-filter").value) {
  const body = $("#payments-table");
  const empty = $("#payments-empty");
  body.replaceChildren();
  const params = new URLSearchParams({ filtro: filter || "todos" });
  if (studentId) params.set("aluno_id", studentId);
  const payments = await api(`/pagamentos?${params.toString()}`);
  empty.textContent = payments.length ? "" : traduzir("Nenhuma cobrança encontrada para este filtro.");
  empty.hidden = payments.length > 0;
  payments.forEach((payment) => {
    const row = element("tr");
    row.append(
      element("td", payment.aluno_nome),
      element("td", formatDate(payment.vencimento)),
      element("td", formatMoney(payment.valor, payment.moeda)),
    );
    const statusCell = element("td");
    const paid = payment.status === "pago";
    const label = payment.atrasado ? "Atrasado" : (statusLabels[payment.status] || payment.status || "Pendente");
    statusCell.append(badge(label, paid ? "good" : (payment.atrasado ? "bad" : "warn")));
    row.append(statusCell);
    const actionCell = element("td");
    if (!paid && payment.aluno_plano_id && !state.config.somente_consulta) {
      const payButton = element("button", traduzir("Registrar pagamento"), "button button-primary button-small");
      payButton.type = "button";
      payButton.dataset.payId = String(payment.id);
      actionCell.append(payButton);
    } else if (paid && state.user?.papel === "dono" && !state.config.somente_consulta) {
      const deleteButton = element("button", traduzir("Apagar pagamento"), "button button-danger button-small");
      deleteButton.type = "button";
      deleteButton.dataset.deletePayId = String(payment.id);
      actionCell.append(deleteButton);
    }
    row.append(actionCell);
    body.append(row);
  });
}

async function loadAcademyQr() {
  const image = $("#academy-qr-image");
  const empty = $("#academy-qr-empty");
  const remove = $("#remove-academy-qr");
  const upload = $("#academy-qr-file");
  if (!image || !state.token) return;
  const response = await fetchFrequency("/academia/qr", {
    headers: { Authorization: `Bearer ${state.token}` },
    cache: "no-store",
  });
  if (response.status === 404) {
    if (upload) upload.disabled = false;
    image.hidden = true;
    image.removeAttribute("src");
    empty.hidden = false;
    remove.hidden = true;
  if (state.qrPreviewUrl) URL.revokeObjectURL(state.qrPreviewUrl);
  state.qrPreviewUrl = null;
  if (state.monitorLogoPreviewUrl) URL.revokeObjectURL(state.monitorLogoPreviewUrl);
  state.monitorLogoPreviewUrl = null;
  if (state.academyLogoPreviewUrl) URL.revokeObjectURL(state.academyLogoPreviewUrl);
  state.academyLogoPreviewUrl = null;
    return;
  }
  if (response.status === 401) {
    endSession("Sua sessão expirou. Entre novamente.");
    throw new Error("Sessão encerrada.");
  }
  if (!response.ok) {
    let detail = null;
    try { detail = (await response.json())?.detail; } catch { detail = null; }
    if (response.status === 503 && detail === "migracao_qr_pendente") {
      if (upload) upload.disabled = true;
      image.hidden = true;
      empty.textContent = traduzir(messages.migracao_qr_pendente);
      empty.hidden = false;
      remove.hidden = true;
      return;
    }
    throw new Error("Não foi possível carregar o QR da academia.");
  }
  if (upload) upload.disabled = false;
  const imageBlob = await response.blob();
  if (state.qrPreviewUrl) URL.revokeObjectURL(state.qrPreviewUrl);
  state.qrPreviewUrl = URL.createObjectURL(imageBlob);
  image.src = state.qrPreviewUrl;
  image.hidden = false;
  empty.hidden = true;
  remove.hidden = state.user?.papel !== "dono";
}

async function loadPresencas() {
  const presencas = await api("/presencas?limite=100");
  const body = $("#presencas-table");
  body.replaceChildren(...presencas.map((presenca) => {
    const row = element("tr");
    const dataHora = presenca.data_hora ? new Date(presenca.data_hora) : null;
    const dataFormatada = dataHora && !Number.isNaN(dataHora.getTime())
      ? new Intl.DateTimeFormat(state.user?.idioma || interfaceLocale, { dateStyle: "short", timeStyle: "short" }).format(dataHora)
      : "—";
    const motivo = {
      digital_nao_cadastrada: "Identificação não cadastrada",
      rosto_nao_identificado: "Rosto não identificado",
      aluno_inativo: "Aluno inativo",
      plano_nao_cadastrado: "Plano não cadastrado",
      sem_pagamento_em_aberto: "Sem mensalidade em aberto",
      mensalidade_atrasada: "Mensalidade atrasada",
      academia_inativa: "Academia suspensa",
    }[presenca.motivo] || (presenca.motivo ? presenca.motivo.replaceAll("_", " ") : "—");

    row.append(element("td", dataFormatada));
    row.append(element("td", presenca.nome_aluno || "Identificação desconhecida"));
    const result = element("td");
    result.append(badge(presenca.liberado ? "Liberado" : "Bloqueado", presenca.liberado ? "good" : "bad"));
    row.append(result, element("td", traduzir(motivo)));
    return row;
  }));
  $("#presencas-empty").hidden = presencas.length > 0;
}

async function loadAcademies() {
  const academies = await api("/admin/academias");
  let subscriptions = [];
  try { subscriptions = await api("/admin/frequency/academias"); } catch (_) { /* A lista básica continua disponível se o faturamento estiver em manutenção. */ }
  const subscriptionsByAcademy = new Map(subscriptions.map((item) => [String(item.academia_id), item]));
  state.platformAcademies = academies.map((academy) => ({ ...academy, subscription: subscriptionsByAcademy.get(String(academy.id)) || null }));
  const body = $("#academies-table");
  body.replaceChildren(...state.platformAcademies.map((academy) => {
    const row = element("tr");
    row.append(element("td", academy.nome), element("td", academy.pais), element("td", academy.nome_dono || "—"));
    const statusCell = element("td");
    statusCell.append(badge(academy.ativa ? "Ativa" : "Suspensa", academy.ativa ? "good" : "bad"));
    row.append(statusCell);
    const actions = element("td");
    if (!state.config.somente_consulta) {
      const edit = element("button", traduzir("Editar"), "button button-quiet button-small");
      edit.type = "button";
      edit.dataset.academyEdit = String(academy.id);
      edit.dataset.academyName = academy.nome;
      edit.dataset.academyCountry = academy.pais;
      actions.append(edit);
      const button = element("button", traduzir(academy.ativa ? "Suspender" : "Ativar"), academy.ativa ? "button button-danger button-small" : "button button-secondary button-small");
      button.type = "button";
      button.dataset.academyStatus = String(academy.id);
      button.dataset.active = String(academy.ativa);
      actions.append(button);
    }
    row.append(actions);
    return row;
  }));
  $("#academies-empty").hidden = academies.length > 0;
}

async function editAcademy(academy) {
  const [plans, billingRows] = await Promise.all([
    api("/admin/frequency/planos"),
    api("/admin/frequency/academias"),
  ]);
  const billing = billingRows.find((item) => String(item.academia_id) === String(academy.id)) || academy.subscription;
  const currentPlanId = billing?.plano_id ? String(billing.plano_id) : "";
  const planOptions = [["Sem alteração", ""]].concat(
    plans.filter((plan) => plan.ativo || String(plan.id) === currentPlanId)
      .map((plan) => [plan.nome + " · " + formatMoney(plan.valor, plan.moeda) + " · " + plan.duracao_dias + " " + traduzir("dias"), String(plan.id)]),
  );
  const fields = [
    formField("Nome da academia", "nome_academia", { value: academy.nome, maxLength: 160 }),
    formField("País", "pais", { value: academy.pais, options: [["Brasil", "Brasil"], ["Bolívia", "Bolivia"]] }),
    formField("Cidade", "cidade", { value: academy.cidade || "", maxLength: 120, required: false }),
    formField("Estado / departamento", "estado", { value: academy.estado || "", maxLength: 120, required: false }),
    formField("Endereço", "endereco", { value: academy.endereco || "", maxLength: 300, required: false }),
    formField("Código postal", "codigo_postal", { value: academy.codigo_postal || "", maxLength: 30, required: false }),
    formField("Telefone da academia", "telefone", { value: academy.telefone || "", maxLength: 40, required: false }),
    formField("Nome do dono", "nome_dono", { value: academy.nome_dono || "", maxLength: 160 }),
    formField("E-mail do dono", "email_dono", { value: academy.email_dono || "", type: "email", maxLength: 254 }),
    formField("Plano da academia", "plano_frequency_id", { value: currentPlanId, options: planOptions, required: false }),
    formField("Próximo vencimento", "vencimento_frequency", { value: billing?.proximo_vencimento || "", type: "date", required: false }),
  ];
  openBusinessDialog("Editar academia", "Atualize os dados cadastrais e, se necessário, troque o plano e o próximo vencimento.", fields, async (values) => {
    await api("/admin/academias/" + encodeURIComponent(academy.id), {
      method: "PATCH",
      body: {
        nome_academia: values.nome_academia.trim(),
        pais: values.pais,
        cidade: values.cidade.trim(),
        estado: values.estado.trim(),
        endereco: values.endereco.trim(),
        codigo_postal: values.codigo_postal.trim(),
        telefone: values.telefone.trim(),
        nome_dono: values.nome_dono.trim(),
        email_dono: values.email_dono.trim(),
      },
    });
    const selectedPlanId = values.plano_frequency_id ? Number(values.plano_frequency_id) : null;
    const planChanged = selectedPlanId && String(selectedPlanId) !== currentPlanId;
    const dueChanged = values.vencimento_frequency && values.vencimento_frequency !== (billing?.proximo_vencimento || "");
    if (planChanged || dueChanged) {
      if (!values.vencimento_frequency) throw new Error(traduzir("Informe o próximo vencimento para alterar o plano."));
      if (billing?.assinatura_id) {
        await api("/admin/frequency/assinaturas/" + encodeURIComponent(billing.assinatura_id), {
          method: "PATCH",
          body: { ...(planChanged ? { plano_id: selectedPlanId } : {}), proximo_vencimento: values.vencimento_frequency },
        });
      } else if (planChanged) {
        await api("/admin/frequency/assinaturas", {
          method: "POST",
          body: { academia_id: Number(academy.id), plano_id: selectedPlanId, vencimento: values.vencimento_frequency },
        });
      }
    }
    showNotice("Academia atualizada.");
    await loadAcademies();
  });
}

async function loadReceptionTeam() {
  const users = await api("/usuarios/recepcao");
  const body = $("#reception-table");
  body.replaceChildren(...users.map((user) => {
    const row = element("tr");
    row.append(element("td", user.nome), element("td", user.email));
    const statusCell = element("td");
    statusCell.append(badge(user.ativo ? "Ativo" : "Suspenso", user.ativo ? "good" : "bad"));
    row.append(statusCell);

    const actions = element("td");
    const button = element(
      "button",
      traduzir(user.ativo ? "Suspender" : "Reativar"),
      user.ativo ? "button button-danger button-small" : "button button-secondary button-small",
    );
    button.type = "button";
    button.dataset.receptionStatus = String(user.id);
    button.dataset.active = String(user.ativo);
    actions.append(button);
    row.append(actions);
    return row;
  }));
  $("#reception-empty").hidden = users.length > 0;
}

function formObject(form) {
  return Object.fromEntries(new FormData(form).entries());
}

function renderStudentPhotoPreview() {
  const preview = $("#student-photo-preview");
  const placeholder = $("#student-photo-placeholder");
  const remove = $("#clear-student-photo");
  if (state.studentPhotoBlob && state.studentPhotoPreviewUrl) {
    preview.src = state.studentPhotoPreviewUrl;
    preview.hidden = false;
    placeholder.hidden = true;
    remove.hidden = false;
  } else {
    preview.removeAttribute("src");
    preview.hidden = true;
    placeholder.hidden = false;
    remove.hidden = true;
  }
  [1, 2, 3].forEach((index) => {
    const sample = $(`#student-face-preview-${index}`);
    if (!sample) return;
    const url = state.studentFacePreviewUrls[index - 1];
    sample.hidden = !url;
    if (url) sample.src = url;
    else sample.removeAttribute("src");
  });
}

function stopStudentCamera() {
  if (state.studentCameraStream) {
    state.studentCameraStream.getTracks().forEach((track) => track.stop());
    state.studentCameraStream = null;
  }
  const video = $("#student-camera-video");
  video.pause();
  video.srcObject = null;
  video.hidden = true;
  $(".face-position-guide")?.setAttribute("hidden", "");
  $("#student-face-angle")?.setAttribute("hidden", "");
  $("#capture-student-photo").hidden = true;
  $("#cancel-student-camera").hidden = true;
  $("#start-student-camera").hidden = false;
  renderStudentPhotoPreview();
}

function openStudentPlanDialog(studentId) {
  const student = state.students.find((item) => String(item.id) === String(studentId));
  if (!student) return;
  if (!state.plans.length) {
    showNotice(traduzir("Crie um plano antes de vincular o aluno."), true);
    setPage("planos");
    return;
  }
  const options = state.plans.map((plan) => [
    `${plan.nome} · ${formatMoney(plan.valor, plan.moeda)} · ${plan.duracao_dias} ${traduzir("dias")}`,
    String(plan.id),
  ]);
  openBusinessDialog(
    "Selecionar plano",
    `${traduzir("Escolha o plano de ")} ${student.nome}. ${traduzir("A primeira cobrança ficará disponível depois da seleção.")}`,
    [formField("Plano", "plano_id", { options })],
    async (values) => {
      await api(`/alunos/${encodeURIComponent(student.id)}/plano`, {
        method: "PATCH",
        body: { plano_id: Number(values.plano_id) },
      });
      showNotice("Plano vinculado. A cobrança está pronta para registro.");
      await loadStudents();
      setPage("pagamentos");
      $("#payment-student").value = String(student.id);
      await loadPayments(String(student.id));
    },
    "Selecionar plano",
  );
}

window.addEventListener("pagehide", () => { stopStudentCamera(); stopStudentEditCamera(); });
document.addEventListener("visibilitychange", () => {
  if (document.hidden) { stopStudentCamera(); stopStudentEditCamera(); }
});

function clearStudentPhoto() {
  stopStudentCamera();
  if (state.studentPhotoPreviewUrl) URL.revokeObjectURL(state.studentPhotoPreviewUrl);
  state.studentPhotoPreviewUrl = null;
  state.studentPhotoBlob = null;
  state.studentFacePreviewUrls.forEach((url) => URL.revokeObjectURL(url));
  state.studentFacePreviewUrls = [];
  state.studentFaceSamples = [];
  $("#student-photo-authorized").checked = false;
  $("#student-photo-file").value = "";
  renderStudentPhotoPreview();
  $("#student-face-status").textContent = "Nenhum cadastro facial iniciado.";
}

function setStudentPhoto(blob) {
  if (state.studentPhotoPreviewUrl) URL.revokeObjectURL(state.studentPhotoPreviewUrl);
  state.studentPhotoBlob = blob;
  state.studentPhotoPreviewUrl = URL.createObjectURL(blob);
  renderStudentPhotoPreview();
}

async function photoJpegFromSource(source, width, height) {
  if (!width || !height) throw new Error("Não foi possível preparar essa foto. Tente outra imagem.");
  const scale = Math.min(1, 512 / Math.max(width, height));
  const canvas = document.createElement("canvas");
  canvas.width = Math.max(1, Math.round(width * scale));
  canvas.height = Math.max(1, Math.round(height * scale));
  canvas.getContext("2d", { alpha: false }).drawImage(source, 0, 0, canvas.width, canvas.height);
  const blob = await new Promise((resolve, reject) => {
    canvas.toBlob((result) => {
      if (result) resolve(result);
      else reject(new Error("Não foi possível preparar essa foto. Tente outra imagem."));
    }, "image/jpeg", 0.82);
  });
  if (blob.size > 512 * 1024) {
    throw new Error("Essa foto ficou grande demais. Selecione uma imagem menor.");
  }
  return blob;
}

function blobToBase64(blob) {
  return new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.onerror = () => reject(new Error("Não foi possível preparar essa foto. Tente outra imagem."));
    reader.onload = () => {
      const value = String(reader.result || "");
      const separator = value.indexOf(",");
      if (separator < 0) reject(new Error("Não foi possível preparar essa foto. Tente outra imagem."));
      else resolve(value.slice(separator + 1));
    };
    reader.readAsDataURL(blob);
  });
}

$("#login-form").addEventListener("submit", async (event) => {
  event.preventDefault();
  const form = event.currentTarget;
  const feedback = $("#login-feedback");
  feedback.textContent = traduzir("Entrando…");
  const body = new URLSearchParams(new FormData(form));
  try {
    const response = await fetchFrequency("/login", {
      method: "POST",
      headers: { "Content-Type": "application/x-www-form-urlencoded", Accept: "application/json" },
      body,
    });
    const data = await response.json();
    if (!response.ok) throw new Error(apiMessage(data.detail));
    state.token = data.access_token;
    sessionStorage.setItem(tokenStorageKey, state.token);
    const user = await api("/eu");
    state.config = await carregarConfiguracao();
    form.reset();
    feedback.textContent = "";
    showApplication(user);
  } catch (error) {
    feedback.textContent = traduzir(error.message || "Não foi possível entrar.");
  }
});

$("#forgot-password-action")?.addEventListener("click", () => {
  const email = $("#login-email")?.value.trim() || "";
  const message = email ? `Olá, preciso recuperar o acesso ao Frequency. Meu e-mail de cadastro é ${email}.` : "Olá, preciso recuperar o acesso ao Frequency. Meu e-mail de cadastro é: ";
  if (SALES_WHATSAPP) window.open(`https://wa.me/${SALES_WHATSAPP}?text=${encodeURIComponent(message)}`, "_blank", "noopener,noreferrer");
});

$("#logout-button").addEventListener("click", () => endSession("Você saiu do Frequency."));
$("#facial-events").addEventListener("click", (event) => {
  const card = event.target.closest("[data-student-id]");
  if (!card || !state.user || state.user.bloqueada_frequency) return;
  setPage("alunos");
  void openStudentEditForm(card.dataset.studentId);
});

$$("[data-page]").forEach((button) => button.addEventListener("click", () => setPage(button.dataset.page)));
$$('[data-go="alunos"]').forEach((button) => button.addEventListener("click", () => setPage("alunos")));

$("#refresh-dashboard").addEventListener("click", () => loadDashboard().catch((error) => showNotice(error.message, true)));
$("#refresh-operation-status")?.addEventListener("click", () => loadOperationStatus());
$("#run-backup")?.addEventListener("click", async () => {
  const button = $("#run-backup"); button.disabled = true;
  try {
    await api("/operacao/backup", { method: "POST" });
    showNotice(traduzir("Backup iniciado. O status será atualizado quando terminar."));
    setTimeout(() => loadOperationStatus(), 2000);
  } catch (error) { showNotice(error.message, true); }
  finally { button.disabled = false; }
});

const signupPlanParam = new URLSearchParams(location.search).get("plano");
const signupPlanNames = { essencial: "Essencial", profissional: "Profissional", premium: "Premium" };
function renderSignupPlanContext() {
  const context = $("#signup-plan-context");
  const name = $("#signup-plan-name");
  if (context && name && signupPlanNames[signupPlanParam]) {
    name.textContent = window.FrequencyI18n?.translate(interfaceLocale, signupPlanNames[signupPlanParam]) || signupPlanNames[signupPlanParam];
    context.hidden = false;
  }
}
renderSignupPlanContext();
const signupCountry = $("#signup-country");
const signupPrefix = $("#signup-phone-prefix");
const signupNextActions = $("#signup-next-actions");
const signupCheckoutAction = $("#signup-checkout-action");
const signupWhatsappAction = $("#signup-whatsapp-action");
const signupSuccess = $("#signup-success");
const signupForm = $("#academy-signup-form");
const signupDetails = $("#login-signup-details");
const signupPhonePrefixes = { BO: "+591", BR: "+55", US: "+1", PE: "+51", CL: "+56", AR: "+54" };
const signupCountries = { BO: "Bolivia", BR: "Brasil", US: "United States", PE: "Peru", CL: "Chile", AR: "Argentina" };
const signupWhatsappMessages = {
  "pt-BR": (plan) => `Olá, quero contratar o plano ${plan} do Frequency.`,
  "es-BO": (plan) => `Hola, quiero contratar el plan ${plan} de Frequency.`,
  "en-US": (plan) => `Hello, I want to subscribe to the ${plan} plan from Frequency.`,
  "zh-CN": (plan) => `你好，我想订阅 Frequency 的${plan}套餐。`,
  "hi-IN": (plan) => `नमस्ते, मैं Frequency की ${plan} योजना लेना चाहता हूँ।`,
};
function configureSignupNextActions() {
  if (!signupCheckoutAction || !signupWhatsappAction) return;
  const plan = signupPlanNames[signupPlanParam] ? signupPlanParam : "profissional";
  const planName = signupPlanNames[plan];
  const country = signupCountry?.value || "Brasil";
  const whatsappMessage = (signupWhatsappMessages[interfaceLocale] || signupWhatsappMessages["en-US"])(planName);
  signupCheckoutAction.href = `/app?plano=${encodeURIComponent(plan)}`;
  signupWhatsappAction.hidden = !SALES_WHATSAPP;
  signupWhatsappAction.href = `https://web.whatsapp.com/send/?phone=${SALES_WHATSAPP}&text=${encodeURIComponent(whatsappMessage)}`;
  signupCheckoutAction.classList.toggle("button-primary", country !== "Bolivia");
  signupCheckoutAction.classList.toggle("button-secondary", country === "Bolivia");
  signupWhatsappAction.classList.toggle("button-primary", country === "Bolivia");
  signupWhatsappAction.classList.toggle("button-secondary", country !== "Bolivia");
}

const signupSupportMessages = {
  "pt-BR": "Olá, preciso de ajuda para configurar minha academia no Frequency.",
  "es-BO": "Hola, necesito ayuda para configurar mi gimnasio en Frequency.",
  "en-US": "Hello, I need help setting up my gym in Frequency.",
  "zh-CN": "您好，我需要帮助在 Frequency 中设置我的健身房。",
  "hi-IN": "नमस्ते, मुझे Frequency में अपना जिम सेट करने में मदद चाहिए।",
};
function configureSignupSupportAction() {
  if (!signupSupportAction) return;
  const message = signupSupportMessages[interfaceLocale] || signupSupportMessages["en-US"];
  signupSupportAction.hidden = !SALES_WHATSAPP;
  signupSupportAction.href = `https://web.whatsapp.com/send/?phone=${SALES_WHATSAPP}&text=${encodeURIComponent(message)}`;
}

function syncSignupCountry() {
  if (!signupCountry || !signupPrefix) return;
  signupCountry.value = signupCountries[signupPrefix.value] || signupCountries.BO;
  $("#signup-bob-guarantee")?.toggleAttribute("hidden", signupPrefix.value !== "BO");
  configureSignupNextActions();
}

function showSignupScreen() {
  $("#login-view")?.classList.add("signup-mode");
  signupDetails?.setAttribute("open", "");
  signupForm?.querySelector("input[name=nome_academia]")?.focus({ preventScroll: true });
}

function showLoginScreen() {
  $("#login-view")?.classList.remove("signup-mode");
  signupDetails?.removeAttribute("open");
  signupSuccess?.setAttribute("hidden", "");
  signupForm?.querySelectorAll("label, .signup-benefits, .signup-guarantees, .signup-legal, #academy-signup-submit, #academy-signup-feedback").forEach((node) => { node.hidden = false; });
  signupForm?.removeAttribute("hidden");
}

signupPrefix?.addEventListener("change", syncSignupCountry);
signupCountry?.addEventListener("change", configureSignupNextActions);
signupDetails?.addEventListener("toggle", () => { if (signupDetails.open) $("#login-view")?.classList.add("signup-mode"); });
$("#signup-back-login")?.addEventListener("click", showLoginScreen);
$("#signup-password-toggle")?.addEventListener("click", (event) => {
  const input = $("#signup-password");
  const button = event.currentTarget;
  if (!input) return;
  input.type = input.type === "password" ? "text" : "password";
  button.textContent = input.type === "password" ? "Ver" : "Ocultar";
  button.setAttribute("aria-label", input.type === "password" ? "Mostrar contraseña" : "Ocultar contraseña");
});
$("#login-password-toggle")?.addEventListener("click", (event) => {
  const input = $("#login-password");
  const button = event.currentTarget;
  if (!input || !button) return;
  const mostrar = input.type === "password";
  input.type = mostrar ? "text" : "password";
  button.textContent = mostrar ? "Ocultar" : "Ver";
  button.setAttribute("aria-label", mostrar ? "Ocultar senha" : "Mostrar senha");
});
$("#signup-open-login")?.addEventListener("click", () => {
  const email = signupForm?.elements.email_dono?.value?.trim().toLowerCase();
  showLoginScreen();
  if (email) $("#login-email").value = email;
  $("#login-email")?.focus();
});
configureSignupNextActions();
signupForm?.addEventListener("submit", async (event) => {
  event.preventDefault();
  const form = event.currentTarget;
  const feedback = $("#academy-signup-feedback");
  const button = $("#academy-signup-submit");
  button.disabled = true;
  feedback.className = "feedback";
  feedback.textContent = traduzir("Criando o cadastro…");
  try {
    const values = Object.fromEntries(new FormData(form));
    const digits = String(values.telefone_dono || "").replace(/\D/g, "");
    const prefix = signupPhonePrefixes[signupPrefix?.value] || "+591";
    const signupPayload = { nome_academia: String(values.nome_academia || "").trim(), nome_dono: String(values.nome_dono || "").trim(), email_dono: String(values.email_dono || "").trim().toLowerCase(), senha_dono: values.senha_dono, telefone_dono: `${prefix}${digits}`, pais: signupCountries[signupPrefix?.value] || "Bolivia" };
    await api("/cadastro-academia", { method: "POST", body: signupPayload });
    if (typeof window.fbq === "function" && !form.dataset.registrationTracked) { window.fbq("track", "CompleteRegistration"); form.dataset.registrationTracked = "true"; }
    $("#signup-success")?.removeAttribute("hidden");
    form.querySelectorAll("label, .signup-benefits, .signup-guarantees, .signup-legal, #academy-signup-submit, #academy-signup-feedback").forEach((node) => { node.hidden = true; });
    feedback.textContent = "";
  } catch (error) {
    const message = error.status === 409 || String(error.message).includes("cliente") ? "Este correo ya tiene una cuenta." : error.status === 400 && String(error.message).includes("senha") ? "Usa al menos 8 caracteres." : error.status >= 500 || String(error.message).includes("conectar") ? "No pudimos crear tu cuenta. Revisa tu conexión e inténtalo de nuevo." : traduzir(error.message || "Preencha todos os campos obrigatórios.");
    feedback.className = "feedback error";
    feedback.textContent = message;
    const invalid = [...form.querySelectorAll("input[required]")].find((input) => !String(input.value).trim() || !input.checkValidity());
    invalid?.focus();
  } finally { button.disabled = false; }
});
if (new URLSearchParams(location.search).get("cadastro") === "1") showSignupScreen();
$("#backup-run-page")?.addEventListener("click", async () => {
  const button = $("#backup-run-page");
  button.disabled = true;
  try {
    await api("/operacao/backup", { method: "POST" });
    showNotice(traduzir("Backup iniciado. O status será atualizado quando terminar."));
    setTimeout(() => loadBackupPage().catch(() => {}), 2000);
  } catch (error) { showNotice(error.message, true); }
  finally { button.disabled = false; }
});
$("#refresh-backup-page")?.addEventListener("click", () => loadBackupPage().catch((error) => showNotice(error.message, true)));
$("#backup-download-latest")?.addEventListener("click", async () => {
  const button = $("#backup-download-latest");
  button.disabled = true;
  try {
    if (frequencyDeviceClass !== "desktop") await shareLatestBackupToDevice();
    else await downloadLatestBackup();
  } catch (error) { if (error?.name !== "AbortError") showNotice(error.message, true); }
  finally { button.disabled = false; }
});
$("#backup-choose-folder")?.addEventListener("click", async () => {
  const button = $("#backup-choose-folder");
  const input = $("#backup-destination");
  const status = $("#backup-destination-status");
  button.disabled = true;
  try {
    if (browserDirectoryPickerAvailable()) {
      state.backupDirectoryHandle = await window.showDirectoryPicker({ mode: "readwrite" });
      input.dataset.browserDirectory = "true";
      input.value = `Navegador: ${state.backupDirectoryHandle.name}`;
      status.textContent = traduzir("Pasta do navegador selecionada. Gere o backup e baixe a cópia para salvá-la aqui.");
      return;
    }
    if (frequencyDeviceClass !== "desktop") {
      await shareLatestBackupToDevice();
      status.textContent = traduzir("Escolha a pasta no Arquivos ou Files para salvar a cópia.");
      return;
    }
    const hostFolderPickerAvailable = backupConfig?.seletor_pasta_disponivel === true;
    if (frequencyDeviceClass === "desktop" && !isTouchOnlyDevice() && hostFolderPickerAvailable) {
      const result = await api("/operacao/backup-selecionar-pasta", { method: "POST" });
      if (result.selecionado) input.value = result.destino;
      return;
    }
    status.textContent = traduzir("Este navegador não permite escolher uma pasta diretamente. Use o download da cópia criptografada.");
  } catch (error) {
    if (error?.name !== "AbortError") showNotice(error.message, true);
  } finally { button.disabled = false; }
});
$("#backup-destination-form")?.addEventListener("submit", async (event) => {
  event.preventDefault();
  const form = event.currentTarget;
  const status = $("#backup-destination-status");
  if (frequencyDeviceClass !== "desktop") {
    try {
      await shareLatestBackupToDevice();
      status.textContent = traduzir("Escolha a pasta no Arquivos ou Files para salvar a cópia.");
    } catch (error) {
      if (error?.name !== "AbortError") showNotice(error.message, true);
    }
    return;
  }
  if (form.elements.destino.dataset.browserDirectory === "true") {
    status.textContent = traduzir("Pasta do navegador selecionada. Gere o backup e baixe a cópia para salvá-la aqui.");
    return;
  }
  const button = form.querySelector("button[type=submit]");
  button.disabled = true;
  try {
    const result = await api("/operacao/backup-config", { method: "PUT", body: { destino: form.elements.destino.value.trim() } });
    form.elements.destino.value = result.destino;
    status.textContent = traduzir("Destino salvo. O próximo backup usará esta pasta.");
    await loadOperationStatus();
  } catch (error) { status.textContent = error.message; }
  finally { button.disabled = false; }
});
$("#backup-google-login")?.addEventListener("click", async () => {
  if (frequencyDeviceClass !== "desktop") {
    try { await shareLatestBackupToCloud(); } catch (error) {
      if (error?.name !== "AbortError") showNotice(error.message, true);
    }
    return;
  }
  if (!backupConfig?.nuvem?.google_drive?.disponivel) {
    window.open("https://www.google.com/drive/download/", "_blank", "noopener");
    showNotice(traduzir("Instale e conecte o Google Drive. Depois volte e clique novamente."));
    return;
  }
  const input = $("#backup-destination");
  if (backupConfig.nuvem.google_drive.destino) input.value = backupConfig.nuvem.google_drive.destino;
  $("#backup-destination-form")?.requestSubmit();
});
$("#show-student-form").addEventListener("click", () => {
  closeStudentEditForm();
  clearStudentPhoto();
  const form = $("#student-form");
  form.hidden = false;
  form.removeAttribute("data-write-collapsed");
  form.elements.namedItem("nome").focus();
});
$("#cancel-student-form").addEventListener("click", () => {
  const form = $("#student-form");
  clearStudentPhoto();
  form.reset();
  form.hidden = true;
  form.setAttribute("data-write-collapsed", "");
});
$("#cancel-student-edit-form").addEventListener("click", closeStudentEditForm);
$("#student-search").addEventListener("input", renderStudents);

$("#start-student-camera").addEventListener("click", async () => {
  if (!window.isSecureContext) {
    const localAddress = `${location.protocol}//127.0.0.1:${location.port || "8000"}/app`;
    showNotice(`A webcam é bloqueada neste endereço. No computador da câmera, abra ${localAddress}; em outro aparelho, configure HTTPS.`, true);
    return;
  }
  if (!navigator.mediaDevices?.getUserMedia) {
    showNotice("Esta tela não tem acesso à câmera. Escolha uma imagem do computador.", true);
    return;
  }
  const button = $("#start-student-camera");
  button.disabled = true;
  try {
    const stream = await navigator.mediaDevices.getUserMedia({
      video: { facingMode: "user" },
      audio: false,
    });
    if (!state.user) {
      stream.getTracks().forEach((track) => track.stop());
      return;
    }
    state.studentCameraStream = stream;
    const video = $("#student-camera-video");
    video.srcObject = stream;
    video.hidden = false;
    $(".face-position-guide")?.removeAttribute("hidden");
    $("#student-face-angle")?.removeAttribute("hidden");
    $("#student-photo-preview").hidden = true;
    $("#student-photo-placeholder").hidden = true;
    await video.play();
    button.hidden = true;
    $("#capture-student-photo").hidden = false;
    $("#cancel-student-camera").hidden = false;
    state.studentFaceSamples = [];
    state.studentFacePreviewUrls.forEach((url) => URL.revokeObjectURL(url));
    state.studentFacePreviewUrls = [];
    renderStudentPhotoPreview();
    $("#student-face-angle").textContent = traduzir("Posicione seu rosto no centro");
    $("#student-face-status").textContent = "Olhe de frente e capture a primeira imagem.";
  } catch {
    stopStudentCamera();
    showNotice("Permita o acesso à câmera ou escolha uma imagem do computador.", true);
  } finally {
    button.disabled = false;
  }
});

$("#capture-student-photo").addEventListener("click", async () => {
  const video = $("#student-camera-video");
  try {
    const photo = await photoJpegFromSource(video, video.videoWidth, video.videoHeight);
    state.studentFaceSamples.push(photo);
    state.studentFacePreviewUrls.push(URL.createObjectURL(photo));
    renderStudentPhotoPreview();
    if (!state.studentPhotoBlob) setStudentPhoto(photo);
    const total = state.studentFaceSamples.length;
    if (total >= 3) {
      stopStudentCamera();
      $("#student-face-status").textContent = "Três imagens capturadas. Cadastro facial pronto para validação.";
      $("#student-face-angle").textContent = traduzir("Capturas concluídas");
      $("#student-photo-authorized").focus();
    } else {
      $("#student-face-angle").textContent = traduzir(total === 1 ? "Vire levemente para a esquerda" : "Vire levemente para a direita");
      $("#student-face-status").textContent = total === 1
        ? "Imagem 1 de 3. Vire levemente o rosto para a esquerda."
        : "Imagem 2 de 3. Vire levemente o rosto para a direita.";
    }
    showNotice("");
  } catch (error) {
    showNotice(error.message, true);
  }
});

$("#cancel-student-camera").addEventListener("click", stopStudentCamera);
$("#choose-student-photo").addEventListener("click", () => $("#student-photo-file").click());
$("#clear-student-photo").addEventListener("click", clearStudentPhoto);

$("#student-photo-file").addEventListener("change", async (event) => {
  const file = event.target.files?.[0];
  if (!file) return;
  if (!new Set(["image/jpeg", "image/png", "image/webp"]).has(file.type)) {
    showNotice("Use uma foto JPG, PNG ou WebP.", true);
    event.target.value = "";
    return;
  }
  if (file.size > 5 * 1024 * 1024) {
    showNotice("A foto precisa ter até 5 MB.", true);
    event.target.value = "";
    return;
  }
  let bitmap;
  try {
    stopStudentCamera();
    bitmap = await createImageBitmap(file);
    const photo = await photoJpegFromSource(bitmap, bitmap.width, bitmap.height);
    setStudentPhoto(photo);
    $("#student-photo-authorized").focus();
    showNotice("");
  } catch (error) {
    showNotice(error.message || "Não foi possível preparar essa foto. Tente outra imagem.", true);
  } finally {
    bitmap?.close();
    event.target.value = "";
  }
});

function closeStudentEditForm() {
  const form = $("#student-edit-form");
  state.studentEditRequestId += 1;
  stopStudentEditCamera();
  if (state.studentEditPhotoPreviewUrl) URL.revokeObjectURL(state.studentEditPhotoPreviewUrl);
  state.studentEditPhotoPreviewUrl = null;
  state.studentEditPhotoBlob = null;
  $("#student-edit-photo-file").value = "";
  $("#student-edit-photo-authorized").checked = false;
  $("#student-edit-photo-name").textContent = traduzir("Selecione uma nova foto para substituir a atual.");
  form.reset();
  form.hidden = true;
  form.setAttribute("data-write-collapsed", "");
  state.editingStudentId = null;
}

function stopStudentEditCamera() {
  if (state.studentEditCameraStream) {
    state.studentEditCameraStream.getTracks().forEach((track) => track.stop());
    state.studentEditCameraStream = null;
  }
  const video = $("#student-edit-camera-video");
  if (!video) return;
  video.pause();
  video.srcObject = null;
  video.hidden = true;
  $("#capture-student-edit-photo").hidden = true;
  $("#cancel-student-edit-camera").hidden = true;
  $("#start-student-edit-camera").hidden = false;
}

$("#start-student-edit-camera")?.addEventListener("click", async () => {
  if (!window.isSecureContext || !navigator.mediaDevices?.getUserMedia) {
    showNotice("Esta tela não tem acesso à câmera. Escolha uma imagem do computador.", true);
    return;
  }
  const button = $("#start-student-edit-camera");
  button.disabled = true;
  try {
    const stream = await navigator.mediaDevices.getUserMedia({ video: { facingMode: "user" }, audio: false });
    state.studentEditCameraStream = stream;
    const video = $("#student-edit-camera-video");
    video.srcObject = stream;
    video.hidden = false;
    await video.play();
    button.hidden = true;
    $("#capture-student-edit-photo").hidden = false;
    $("#cancel-student-edit-camera").hidden = false;
  } catch {
    stopStudentEditCamera();
    showNotice("Permita o acesso à câmera ou escolha uma imagem do computador.", true);
  } finally { button.disabled = false; }
});

$("#capture-student-edit-photo")?.addEventListener("click", async () => {
  const video = $("#student-edit-camera-video");
  try {
    const photo = await photoJpegFromSource(video, video.videoWidth, video.videoHeight);
    if (state.studentEditPhotoPreviewUrl) URL.revokeObjectURL(state.studentEditPhotoPreviewUrl);
    state.studentEditPhotoBlob = photo;
    state.studentEditPhotoPreviewUrl = URL.createObjectURL(photo);
    $("#student-edit-photo-name").textContent = traduzir("Nova foto selecionada. Ela substituirá a anterior ao salvar.");
    stopStudentEditCamera();
  } catch (error) { showNotice(error.message, true); }
});
$("#cancel-student-edit-camera")?.addEventListener("click", stopStudentEditCamera);

$("#student-edit-photo-file")?.addEventListener("change", async (event) => {
  const file = event.target.files?.[0];
  if (!file) return;
  if (!new Set(["image/jpeg", "image/png", "image/webp"]).has(file.type)) {
    showNotice("Use uma foto JPG, PNG ou WebP.", true);
    event.target.value = "";
    return;
  }
  if (file.size > 5 * 1024 * 1024) {
    showNotice("A foto precisa ter até 5 MB.", true);
    event.target.value = "";
    return;
  }
  let bitmap;
  try {
    bitmap = await createImageBitmap(file);
    const photo = await photoJpegFromSource(bitmap, bitmap.width, bitmap.height);
    if (state.studentEditPhotoPreviewUrl) URL.revokeObjectURL(state.studentEditPhotoPreviewUrl);
    state.studentEditPhotoBlob = photo;
    state.studentEditPhotoPreviewUrl = URL.createObjectURL(photo);
    $("#student-edit-photo-name").textContent = traduzir("Nova foto selecionada. Ela substituirá a anterior ao salvar.");
  } catch (error) {
    showNotice(error.message || "Não foi possível preparar essa foto. Tente outra imagem.", true);
  } finally {
    bitmap?.close();
    event.target.value = "";
  }
});

const APP_ACCESS_TEXT = {
  sem_email: "Sem e-mail cadastrado: o aluno ainda não pode entrar no app.",
  convidado: "E-mail cadastrado. O aluno cria a senha no primeiro acesso, com um código enviado ao e-mail.",
  ativo: "Acesso ao app ativo.",
};

async function loadStudentAppAccess(studentId, requestId) {
  const box = $("#student-app-access");
  const form = $("#student-edit-form");
  box.hidden = true;
  state.studentAppAccess = null;
  try {
    const info = await api("/alunos/" + encodeURIComponent(studentId) + "/acesso-app");
    if (requestId !== state.studentEditRequestId) return;
    state.studentAppAccess = info;
    form.elements.namedItem("email").value = info.email || "";
    $("#student-app-access-status").textContent = traduzir(APP_ACCESS_TEXT[info.acesso_app] || "") +
      (info.app_ligado ? "" : " " + traduzir("O app do aluno ainda não está ligado nesta academia."));
    $("#student-app-invite").hidden = !(info.app_ligado && info.email);
    $("#student-app-reset").hidden = !(info.app_ligado && info.acesso_app !== "sem_email");
    box.hidden = false;
  } catch (_erro) {
    // migração do e-mail do aluno ainda não aplicada: a seção permanece oculta
  }
}

$("#student-app-invite").addEventListener("click", async () => {
  if (!state.editingStudentId) return;
  try {
    await api("/alunos/" + encodeURIComponent(state.editingStudentId) + "/convite", { method: "POST" });
    showNotice("Convite enviado por e-mail.");
  } catch (error) {
    showNotice(error.message, true);
  }
});

$("#student-app-reset").addEventListener("click", async () => {
  if (!state.editingStudentId) return;
  if (!window.confirm(traduzir("Redefinir o acesso deste aluno ao app? Ele precisará criar uma nova senha."))) return;
  try {
    await api("/alunos/" + encodeURIComponent(state.editingStudentId) + "/redefinir-acesso", { method: "POST" });
    showNotice("Acesso redefinido. Envie um novo convite.");
    await loadStudentAppAccess(state.editingStudentId, state.studentEditRequestId);
  } catch (error) {
    showNotice(error.message, true);
  }
});

const FICHA_TEXT_FIELDS = ["contato_emergencia_nome", "contato_emergencia_telefone", "endereco_rua", "endereco_numero",
  "endereco_cidade", "objetivo", "restricoes_saude", "sexo"];

function fichaFromForm(form) {
  const body = {};
  for (const name of FICHA_TEXT_FIELDS) {
    const el = form.elements.namedItem("ficha_" + name);
    const value = el ? String(el.value || "").trim() : "";
    body[name] = value || null;
  }
  const weight = form.elements.namedItem("ficha_peso_kg").value;
  const height = form.elements.namedItem("ficha_altura_cm").value;
  body.peso_kg = weight ? Number(weight) : null;
  body.altura_cm = height ? Number(height) : null;
  body.atestado_medico = form.elements.namedItem("ficha_atestado_medico").checked;
  return body;
}

function fichaHasData(ficha) {
  return Object.values(ficha).some((value) => value !== null && value !== false);
}

function fillFichaForm(form, ficha) {
  for (const name of FICHA_TEXT_FIELDS) {
    const el = form.elements.namedItem("ficha_" + name);
    if (el) el.value = (ficha && ficha[name]) || "";
  }
  form.elements.namedItem("ficha_peso_kg").value = ficha && ficha.peso_kg != null ? ficha.peso_kg : "";
  form.elements.namedItem("ficha_altura_cm").value = ficha && ficha.altura_cm != null ? ficha.altura_cm : "";
  form.elements.namedItem("ficha_atestado_medico").checked = Boolean(ficha && ficha.atestado_medico);
}

async function saveStudentFicha(studentId, ficha) {
  await api("/alunos/" + encodeURIComponent(studentId) + "/ficha", { method: "PUT", body: ficha });
}

async function openStudentEditForm(studentId) {
  const form = $("#student-edit-form");
  clearStudentPhoto();
  $("#student-form").reset();
  $("#student-form").hidden = true;
  closeStudentEditForm();
  const requestId = state.studentEditRequestId;
  try {
    const student = await api("/alunos/" + encodeURIComponent(studentId) + "?incluir_bairro=true");
    if (requestId !== state.studentEditRequestId || !state.user) return;
    form.elements.namedItem("documento").value = student.documento || "";
    const phoneInput = form.elements.namedItem("telefone");
    phoneInput.value = student.telefone || "";
    syncPhonePrefix(phoneInput);
    form.elements.namedItem("bairro").value = student.bairro || "";
    form.elements.namedItem("data_nascimento").value = student.data_nascimento || "";
    await loadStudentAppAccess(studentId, requestId);
    try {
      fillFichaForm(form, await api("/alunos/" + encodeURIComponent(studentId) + "/ficha"));
    } catch (fichaError) {
      fillFichaForm(form, null);
    }
    state.editingStudentId = Number(studentId);
    form.hidden = false;
    form.removeAttribute("data-write-collapsed");
    form.elements.namedItem("documento").focus();
    form.scrollIntoView({ behavior: window.matchMedia("(prefers-reduced-motion: reduce)").matches ? "auto" : "smooth", block: "start" });
  } catch (error) {
    if (requestId === state.studentEditRequestId && state.user) {
      showNotice(error.message, true);
    }
  }
}

$("#student-form").addEventListener("submit", async (event) => {
  event.preventDefault();
  const form = event.currentTarget;
  const values = formObject(form);
  if (state.studentPhotoBlob && !$("#student-photo-authorized").checked) {
    showNotice("Confirme que a pessoa autorizou o cadastro desta foto.", true);
    $("#student-photo-authorized").focus();
    return;
  }
  const body = {
    nome: values.nome.trim(),
    documento: values.documento.trim(),
    telefone: values.telefone.trim() || null,
    email: (values.email || "").trim() || null,
    bairro: values.bairro.trim() || null,
    data_nascimento: values.data_nascimento || null,
    plano_id: values.plano_id ? Number(values.plano_id) : null,
  };
  try {
    if (state.studentPhotoBlob) {
      body.foto_base64 = await blobToBase64(state.studentPhotoBlob);
      body.foto_media_type = state.studentPhotoBlob.type;
    }
    if (state.studentFaceSamples.length) {
      if (state.studentFaceSamples.length < 3) {
        showNotice("Capture as três imagens do rosto antes de salvar.", true);
        return;
      }
      body.fotos_rosto_base64 = await Promise.all(state.studentFaceSamples.map(blobToBase64));
      body.consentimento_facial = $("#student-photo-authorized").checked;
    }
    const facialEnrollment = state.studentFaceSamples.length >= 3;
    const created = await api("/alunos", { method: "POST", body });
    const ficha = fichaFromForm(form);
    let fichaSalva = true;
    if (fichaHasData(ficha) && created && created.id) {
      try {
        await saveStudentFicha(created.id, ficha);
      } catch (fichaError) {
        fichaSalva = false;
      }
    }
    form.reset();
    clearStudentPhoto();
    form.hidden = true;
    form.setAttribute("data-write-collapsed", "");
    $("#student-search").value = "";
    showNotice(fichaSalva
      ? (created.id_biometria && facialEnrollment ? "Aluno cadastrado com reconhecimento facial." : "Aluno cadastrado.")
      : "Aluno cadastrado, mas a ficha complementar não foi salva. Abra Editar para preenchê-la de novo.", !fichaSalva);
    await loadStudents();
  } catch (error) {
    showNotice(error.message, true);
  }
});

$("#student-edit-form").addEventListener("submit", async (event) => {
  event.preventDefault();
  const form = event.currentTarget;
  if (!state.editingStudentId) {
    showNotice("Não há dados para atualizar.", true);
    return;
  }
  const values = formObject(form);
  if (state.studentEditPhotoBlob && !$("#student-edit-photo-authorized").checked) {
    showNotice("Confirme que a pessoa autorizou a substituição desta foto.", true);
    $("#student-edit-photo-authorized").focus();
    return;
  }
  try {
    const body = {
      documento: values.documento.trim(),
      telefone: values.telefone.trim() || null,
      bairro: values.bairro.trim() || null,
      data_nascimento: values.data_nascimento || null,
    };
    if (state.studentAppAccess) {
      const novoEmail = (values.email || "").trim() || null;
      if (novoEmail !== (state.studentAppAccess.email || null)) {
        await api("/alunos/" + encodeURIComponent(state.editingStudentId) + "/email", {
          method: "PUT",
          body: { email: novoEmail },
        });
      }
    }
    if (state.studentEditPhotoBlob) {
      body.foto_base64 = await blobToBase64(state.studentEditPhotoBlob);
      body.foto_media_type = state.studentEditPhotoBlob.type;
      body.consentimento_foto = true;
    }
    await saveStudentFicha(state.editingStudentId, fichaFromForm(form));
    await api("/alunos/" + encodeURIComponent(state.editingStudentId), {
      method: "PATCH",
      body,
    });
    closeStudentEditForm();
    $("#student-search").value = "";
    showNotice("Dados do aluno atualizados.");
    await loadStudents();
  } catch (error) {
    showNotice(error.message, true);
  }
});

$("#students-table").addEventListener("click", async (event) => {
  const editButton = event.target.closest("[data-edit-student]");
  if (editButton) {
    await openStudentEditForm(editButton.dataset.editStudent);
    return;
  }

  const selectPlanButton = event.target.closest("[data-select-plan]");
  if (selectPlanButton) {
    openStudentPlanDialog(selectPlanButton.dataset.selectPlan);
    return;
  }

  const button = event.target.closest("[data-student-payments]");
  if (button) {
    setPage("pagamentos");
    $("#payment-student").value = button.dataset.studentPayments;
    try {
      await loadPayments(button.dataset.studentPayments);
    } catch (error) {
      showNotice(error.message, true);
    }
    return;
  }

  const statusButton = event.target.closest("[data-toggle-student]");
  if (statusButton) {
    const active = statusButton.dataset.active === "true";
    if (!window.confirm(traduzir(active ? "Desativar este aluno?" : "Ativar este aluno?"))) return;
    try {
      await api(`/alunos/${encodeURIComponent(statusButton.dataset.toggleStudent)}/status`, {
        method: "PATCH",
        body: { ativo: !active },
      });
      showNotice(active ? "Aluno desativado." : "Aluno ativado.");
      await loadStudents();
    } catch (error) {
      showNotice(error.message, true);
    }
  }
});

$("#payment-student").addEventListener("change", (event) => loadPayments(event.target.value).catch((error) => showNotice(error.message, true)));
$("#payment-filter").addEventListener("change", () => loadPayments($("#payment-student").value).catch((error) => showNotice(error.message, true)));
$("#payments-table").addEventListener("click", async (event) => {
  const deleteButton = event.target.closest("[data-delete-pay-id]");
  if (deleteButton) {
    if (!window.confirm(traduzir("Confirmar apagar este pagamento já pago?"))) return;
    try {
      await api(`/pagamentos/${encodeURIComponent(deleteButton.dataset.deletePayId)}`, { method: "DELETE" });
      showNotice(traduzir("Pagamento apagado."));
      await loadPayments($("#payment-student").value);
      await loadDashboard();
    } catch (error) {
      showNotice(error.message, true);
    }
    return;
  }
  const button = event.target.closest("[data-pay-id]");
  if (!button) return;
  if (!window.confirm(traduzir("Confirmar que este pagamento foi recebido?"))) return;
  try {
    await api(`/pagamentos/${encodeURIComponent(button.dataset.payId)}/pagar`, { method: "POST" });
    showNotice("Pagamento registrado.");
    await loadPayments($("#payment-student").value);
    await loadDashboard();
  } catch (error) {
    showNotice(error.message, true);
  }
});

$("#academy-qr-file").addEventListener("change", async (event) => {
  const file = event.target.files?.[0];
  if (!file) return;
  if (!new Set(["image/png", "image/jpeg", "image/webp"]).has(file.type)) {
    showNotice("Envie uma imagem PNG, JPG ou WebP.", true);
    event.target.value = "";
    return;
  }
  if (file.size > 2 * 1024 * 1024) {
    showNotice("A imagem do QR deve ter no máximo 2 MB.", true);
    event.target.value = "";
    return;
  }
  try {
    const response = await fetchFrequency("/academia/qr", {
      method: "PUT",
      headers: {
        Authorization: `Bearer ${state.token}`,
        "Content-Type": file.type,
        Accept: "application/json",
      },
      body: file,
    });
    let result = null;
    try { result = await response.json(); } catch { result = null; }
    if (response.status === 401) {
      endSession("Sua sessão expirou. Entre novamente.");
      return;
    }
    if (!response.ok) throw new Error(apiMessage(result?.detail));
    showNotice("QR de pagamento atualizado.");
    await loadAcademyQr();
  } catch (error) {
    showNotice(error.message, true);
  } finally {
    event.target.value = "";
  }
});

$("#remove-academy-qr").addEventListener("click", async () => {
  if (!window.confirm(traduzir("Remover o QR de pagamento desta academia?"))) return;
  try {
    await api("/academia/qr", { method: "DELETE" });
    showNotice("QR removido.");
    await loadAcademyQr();
  } catch (error) {
    showNotice(error.message, true);
  }
});

$("#package-level")?.addEventListener("change", (event) => {
  const premium = event.currentTarget.value === "premium";
  const extras = $("#package-extras");
  if (extras) extras.disabled = !premium;
  if (!premium) extras?.querySelectorAll("input[type=checkbox]").forEach((input) => { input.checked = false; });
});

$$('[data-package-template]').forEach((button) => button.addEventListener("click", () => {
  const form = $("#frequency-plan-form");
  if (!form) return;
  form.elements.nome.value = button.dataset.packageTemplate;
  form.elements.descricao.value = {
    Essencial: "Gestão essencial da academia.",
    Profissional: "Gestão completa para academias em crescimento.",
    Premium: "Gestão completa com recursos premium.",
  }[button.dataset.packageTemplate] || "";
  form.elements.nivel.value = button.dataset.packageTemplate.toLowerCase();
  form.elements.duracao_dias.value = "30";
  $("#package-level")?.dispatchEvent(new Event("change"));
  $("#package-create")?.setAttribute("open", "");
  form.elements.valor.focus();
}));

$("#frequency-plan-form")?.addEventListener("submit", async (event) => {
  event.preventDefault();
  const form = event.currentTarget;
  const values = formObject(form);
  try {
    await api("/admin/frequency/planos", {
      method: "POST",
      body: {
        nome: values.nome.trim(), descricao: values.descricao.trim(), valor: Number(String(values.valor).replace(",", ".")),
        moeda: values.moeda, duracao_dias: Number(values.duracao_dias), nivel: values.nivel,
        cameras: Boolean(values.cameras), youtube: Boolean(values.youtube),
        max_alunos: Number(values.max_alunos), max_monitores: Number(values.max_monitores), max_leitores: Number(values.max_leitores),
      },
    });
    form.reset();
    $("#package-level")?.dispatchEvent(new Event("change"));
    showNotice("Pacote criado.");
    await loadFrequencyPlans();
  } catch (error) { showNotice(error.message, true); }
});

$("#frequency-plans")?.addEventListener("click", async (event) => {
  const button = event.target.closest("[data-frequency-plan-status]");
  if (!button) return;
  button.disabled = true;
  try {
    await api(`/admin/frequency/planos/${encodeURIComponent(button.dataset.frequencyPlanStatus)}/status`, {
      method: "PATCH", body: { ativo: button.dataset.active !== "true" },
    });
    await loadFrequencyPlans();
  } catch (error) { showNotice(error.message, true); button.disabled = false; }
});

$("#plan-form").addEventListener("submit", async (event) => {
  event.preventDefault();
  const form = event.currentTarget;
  const values = formObject(form);
  try {
    const value = Number(String(values.valor).replace(",", "."));
    await api("/planos", {
      method: "POST",
      body: { nome: values.nome.trim(), valor: value, duracao_dias: Number(values.duracao_dias) },
    });
    form.reset();
    showNotice("Plano criado.");
    await loadPlans();
  } catch (error) {
    showNotice(error.message, true);
  }
});

$("#plans-list").addEventListener("click", async (event) => {
  const button = event.target.closest("[data-delete-plan]");
  if (!button || !window.confirm("Apagar este plano?")) return;
  button.disabled = true;
  try {
    await api(`/planos/${button.dataset.deletePlan}`, { method: "DELETE" });
    showNotice("Plano apagado.");
    await loadPlans();
  } catch (error) {
    showNotice(error.message, true);
    button.disabled = false;
  }
});

$("#reception-form").addEventListener("submit", async (event) => {
  event.preventDefault();
  const form = event.currentTarget;
  const values = formObject(form);
  try {
    await api("/usuarios/recepcao", {
      method: "POST",
      body: { nome: values.nome.trim(), email: values.email.trim(), senha: values.senha },
    });
    form.reset();
    showNotice("Acesso da recepção criado. Compartilhe os dados por um canal seguro.");
    await loadReceptionTeam();
  } catch (error) {
    showNotice(error.message, true);
  }
});

$("#prospecting-region-form")?.addEventListener("submit", criarRegiaoProspeccao);
$("#prospecting-region-refresh")?.addEventListener("click", () => loadProspectingRegions().catch((error) => showNotice(error.message, true)));
if (!$("#prospecting-enrich-contacts")) { const host = $("#prospecting-regions-panel .panel-heading"); if (host) { const button = element("button", "Completar contatos públicos", "button button-secondary"); button.id = "prospecting-enrich-contacts"; button.type = "button"; host.appendChild(button); } }
$("#prospecting-enrich-contacts")?.addEventListener("click", async (event) => { const button = event.currentTarget; const selected = selectedProspectingLeads(); if (!selected.length) { showNotice("Selecione pelo menos um lead.", true); return; } button.disabled = true; try { let tentados = 0; let atualizados = 0; for (const lead of selected.slice(0, 3)) { const result = await api("/admin/prospeccao/enriquecer-contatos?limite=1&ids=" + encodeURIComponent(lead.id), { method: "POST" }); tentados += Number(result.tentados || 0); atualizados += Number(result.atualizados || 0); showNotice(tentados + " leads verificados; " + atualizados + " atualizados."); } await loadProspecting(); } catch (error) { showNotice(error.message, true); } finally { button.disabled = false; } });
if (!$("#prospecting-confirm-whatsapp")) { const host = $("#prospecting-regions-panel .panel-heading"); if (host) { const button = element("button", "Confirmar WhatsApp em lote", "button button-secondary"); button.id = "prospecting-confirm-whatsapp"; button.type = "button"; host.appendChild(button); } }
$("#prospecting-confirm-whatsapp")?.addEventListener("click", async (event) => { if (!window.confirm("Confirmar autorização administrativa para os leads com telefone?")) return; const button = event.currentTarget; button.disabled = true; try { const result = await api("/admin/prospeccao/confirmar-whatsapp-lote", { method: "POST" }); showNotice(`${result.confirmados} leads confirmados para WhatsApp.`); await loadProspecting(); } catch (error) { showNotice(error.message, true); } finally { button.disabled = false; } });
$("#prospecting-regions")?.addEventListener("click", async (event) => { const button = event.target.closest("[data-prospecting-region-search], [data-prospecting-apify-search]"); if (!button) return; button.disabled = true; const apify = button.matches("[data-prospecting-apify-search]"); try { const result = await api(`/admin/prospeccao/regioes/${button.dataset.prospectingRegionSearch || button.dataset.prospectingApifySearch}/${apify ? "buscar-apify" : "buscar"}`, { method: "POST" }); showNotice(`${result.criados} leads criados; ${result.ignorados} duplicados ignorados.`); await loadProspecting(); } catch (error) { showNotice(error.message, true); } finally { button.disabled = false; } });
$("#prospecting-form")?.addEventListener("submit", async (event) => {
  event.preventDefault();
  const form = event.currentTarget;
  const values = formObject(form);
  const id = values.id;
  const body = {
    nome: values.nome.trim(), cidade: values.cidade.trim(), endereco: values.endereco.trim(),
    telefone: values.telefone.trim(), email: values.email.trim(), whatsapp_opt_in: Boolean(form.elements.whatsapp_opt_in?.checked), site_instagram: values.site_instagram.trim(),
    observacoes: values.observacoes.trim(), prioridade: values.prioridade, status_comercial: values.status_comercial,
  };
  if (values.avaliacao) body.avaliacao = Number(String(values.avaliacao).replace(",", "."));
  if (values.ultimo_contato) body.ultimo_contato = values.ultimo_contato;
  try {
    await api(id ? `/admin/prospeccao/leads/${encodeURIComponent(id)}` : "/admin/prospeccao/leads", {
      method: id ? "PATCH" : "POST", body,
    });
    resetProspectingForm();
    showNotice(id ? "Lead atualizado." : "Lead criado.");
    await loadProspecting();
  } catch (error) { showNotice(error.message, true); }
});

$("#prospecting-cancel-edit")?.addEventListener("click", resetProspectingForm);

$("#prospecting-gmail-connect")?.addEventListener("click", async () => { try { const result = await api("/auth/google/gmail/start?format=json&alvo=prospeccao"); if (!result.url) throw new Error("Não foi possível iniciar a autorização do Gmail."); window.location.assign(result.url); } catch (error) { showNotice(error.message, true); } });
$("#prospecting-template-form")?.addEventListener("submit", async (event) => {
  event.preventDefault();
  const form = event.currentTarget;
  const values = formObject(form);
  const image = $("#prospecting-image-file").files?.[0];
  if (image && (!new Set(["image/jpeg", "image/png", "image/webp"]).has(image.type) || image.size > 5 * 1024 * 1024)) {
    showNotice("Envie uma imagem JPG, PNG ou WebP de até 5 MB.", true);
    return;
  }
  try {
    await api("/admin/prospeccao/configuracao", { method: "PATCH", body: {
      whatsapp_template: values.whatsapp_template.trim(), email_assunto_template: values.email_assunto_template.trim(),
      email_corpo_template: values.email_corpo_template.trim(),
    }});
    if (image) await api("/admin/prospeccao/imagem", { method: "PUT", body: image, headers: { "Content-Type": image.type } });
    $("#prospecting-image-file").value = "";
    showNotice("Mensagens comerciais salvas.");
    await loadProspecting();
  } catch (error) { showNotice(error.message, true); }
});

$("#prospecting-leads")?.addEventListener("change", updateProspectingSelection);
$("#prospecting-select-all")?.addEventListener("change", (event) => { document.querySelectorAll("[data-prospecting-select]").forEach((input) => { input.checked = event.currentTarget.checked; }); updateProspectingSelection(); });
$("#prospecting-bulk-whatsapp")?.addEventListener("click", () => enviarProspeccaoSelecionados("whatsapp", $("#prospecting-bulk-whatsapp")));
$("#prospecting-bulk-email")?.addEventListener("click", () => enviarProspeccaoSelecionados("email", $("#prospecting-bulk-email")));$("#prospecting-leads")?.addEventListener("click", async (event) => {
  const action = event.target.closest("[data-prospecting-email], [data-prospecting-whatsapp], [data-prospecting-edit], [data-prospecting-delete]");
  if (!action) return;
  const id = action.dataset.prospectingEmail || action.dataset.prospectingWhatsapp || action.dataset.prospectingEdit || action.dataset.prospectingDelete;
  const lead = state.prospectingLeads.find((item) => String(item.id) === String(id));
  if (!lead) return;
  try {
    if (action.dataset.prospectingEmail) openProspectingEmail(lead);
    else if (action.dataset.prospectingWhatsapp) openProspectingWhatsApp(lead);
    else if (action.dataset.prospectingEdit) editProspectingLead(lead);
    else if (action.dataset.prospectingDelete) {
      if (!window.confirm(`Excluir o lead ${lead.nome}? Ele ficará arquivado para auditoria.`)) return;
      await api(`/admin/prospeccao/leads/${encodeURIComponent(lead.id)}`, { method: "DELETE" });
      showNotice("Lead excluído do painel.");
      await loadProspecting();
    }
  } catch (error) { showNotice(error.message, true); }
});

$("#prospecting-priority-filter")?.addEventListener("change", () => loadProspecting().catch((error) => showNotice(error.message, true)));
$("#prospecting-status-filter")?.addEventListener("change", () => loadProspecting().catch((error) => showNotice(error.message, true)));
$("#prospecting-city-filter")?.addEventListener("change", () => loadProspecting().catch((error) => showNotice(error.message, true)));
$("#refresh-prospecting")?.addEventListener("click", () => loadProspecting().catch((error) => showNotice(error.message, true)));
$("#prospecting-open-image")?.addEventListener("click", () => {
  if (state.prospectingImageUrl) window.open(state.prospectingImageUrl, "_blank", "noopener");
});
$("#prospecting-csv")?.addEventListener("change", async (event) => {
  const file = event.currentTarget.files?.[0];
  if (!file) return;
  try {
    const leads = parseProspectingCsv(await file.text());
    const result = await api("/admin/prospeccao/importar", { method: "POST", body: { leads } });
    $("#prospecting-import-result").textContent = `${result.criados.length} lead(s) importado(s); ${result.ignorados} duplicado(s) ignorado(s).`;
    event.currentTarget.value = "";
    await loadProspecting();
  } catch (error) { showNotice(error.message, true); }
});

$("#academy-form").addEventListener("submit", async (event) => {
  event.preventDefault();
  const form = event.currentTarget;
  const submitButton = form.querySelector("button[type=submit]");
  if (form.dataset.submitting === "true") return;
  form.dataset.submitting = "true";
  if (submitButton) submitButton.disabled = true;
  const values = formObject(form);
  const logo = $("#academy-logo-file").files?.[0];
  if (logo && (!new Set(["image/jpeg", "image/png", "image/webp"]).has(logo.type) || logo.size > 5 * 1024 * 1024)) {
    form.dataset.submitting = "false";
    if (submitButton) submitButton.disabled = false;
    showNotice("Envie uma imagem JPG, PNG ou WebP de até 5 MB.", true);
    return;
  }
  try {
    const body = {
      nome_academia: values.nome_academia.trim(),
      pais: values.pais.trim(),
      nome_dono: values.nome_dono.trim(),
      email_dono: values.email_dono.trim(),
      telefone_dono: values.telefone_dono.trim(),
      senha_dono: values.senha_dono,
    };
    if (logo) {
      body.logo_monitor_base64 = await blobToBase64(logo);
      body.logo_monitor_media_type = logo.type;
    }
    await api("/admin/academias", {
      method: "POST",
      body,
    });
    form.reset();
    showNotice("Academia criada com acesso do dono.");
    await loadAcademies();
  } catch (error) {
    showNotice(error.message, true);
  } finally {
    form.dataset.submitting = "false";
    if (submitButton) submitButton.disabled = false;
  }
});

$("#academies-table").addEventListener("click", async (event) => {
  const edit = event.target.closest("[data-academy-edit]");
  if (edit) {
    const academy = state.platformAcademies.find((item) => String(item.id) === edit.dataset.academyEdit);
    if (!academy) return;
    try { await editAcademy(academy); } catch (error) { showNotice(error.message, true); }
    return;
  }
  const button = event.target.closest("[data-academy-status]");
  if (!button) return;
  const active = button.dataset.active === "true";
  const action = active ? "suspender" : "ativar";
  const prompt = action === "suspender" ? "Confirma suspender esta academia?" : "Confirma ativar esta academia?";
  if (!window.confirm(traduzir(prompt))) return;
  try {
    await api(`/admin/academias/${encodeURIComponent(button.dataset.academyStatus)}/status`, {
      method: "PATCH",
      body: { ativa: !active },
    });
    showNotice(active ? "Academia suspensa." : "Academia ativada.");
    await loadAcademies();
  } catch (error) {
    showNotice(error.message, true);
  }
});

$("#reception-table").addEventListener("click", async (event) => {
  const button = event.target.closest("[data-reception-status]");
  if (!button) return;
  const active = button.dataset.active === "true";
  const action = active ? "suspender" : "reativar";
  const prompt = action === "suspender"
    ? "Confirma suspender o acesso desta pessoa da recepção?"
    : "Confirma reativar o acesso desta pessoa da recepção?";
  if (!window.confirm(traduzir(prompt))) return;
  try {
    await api(
      "/usuarios/recepcao/" + encodeURIComponent(button.dataset.receptionStatus) + "/status",
      { method: "PATCH", body: { ativo: !active } },
    );
    showNotice(active ? "Acesso da recepção suspenso." : "Acesso da recepção reativado.");
    await loadReceptionTeam();
  } catch (error) {
    showNotice(error.message, true);
  }
});

$("#refresh-reception").addEventListener("click", () => loadReceptionTeam().catch((error) => showNotice(error.message, true)));
$("#refresh-academies").addEventListener("click", () => loadAcademies().catch((error) => showNotice(error.message, true)));
$("#refresh-presencas").addEventListener("click", () => loadPresencas().catch((error) => showNotice(error.message, true)));
$("#refresh-region-map")?.addEventListener("click", () => setPage("mapa-regiao"));

$("#generate-monitor-key").addEventListener("click", async () => {
  const currentCode = $("#monitor-key-value")?.value?.trim() || "";
  const renovar = Boolean(currentCode);
  if (renovar && !window.confirm(traduzir("Confirma gerar outro código? O monitor atual será desconectado."))) return;
  try {
    const result = await api("/academia/tela-acesso/chaves", { method: "POST", body: { nome: "Código compartilhado", renovar } });
    $("#monitor-key-value").value = result.chave;
    $("#monitor-key-wrap").hidden = false;
    $("#copy-monitor-key").hidden = false;
    $("#monitor-key-status").textContent = traduzir("O código foi mostrado uma única vez. Copie-o somente para esta tela.");
    showNotice("Código compartilhado gerado. Use-o em todas as telas.");
    await loadMonitorSettings();
  } catch (error) {
    showNotice(error.message, true);
  }
});

$("#monitor-list").addEventListener("click", async (event) => {
  const sessionButton = event.target.closest("button[data-monitor-session]");
  if (sessionButton) {
    sessionButton.disabled = true;
    try {
      await api(`/academia/monitor-sessoes/${encodeURIComponent(sessionButton.dataset.sessionId)}`, { method: "DELETE" });
      await loadMonitorSettings();
      showNotice(traduzir("Tela encerrada. O computador precisará conectar novamente."));
    } catch (error) {
      sessionButton.disabled = false;
      showNotice(error.message, true);
    }
    return;
  }
  const button = event.target.closest("[data-monitor-id]");
  if (!button) return;
  if (!window.confirm(traduzir("Desconectar esta tela? Ela deixará de receber novos acessos."))) return;
  try {
    await api(`/academia/monitores/${encodeURIComponent(button.dataset.monitorId)}`, { method: "DELETE" });
    showNotice("Tela desconectada.");
    await loadMonitorSettings();
  } catch (error) {
    showNotice(error.message, true);
  }
});

$("#copy-monitor-key").addEventListener("click", async () => {
  const input = $("#monitor-key-value");
  try {
    await navigator.clipboard.writeText(input.value);
    showNotice("Código copiado.");
  } catch {
    input.focus();
    input.select();
    showNotice("Não foi possível copiar automaticamente. Selecione e copie o código.", true);
  }
});

$("#monitor-logo-file").addEventListener("change", async (event) => {
  const file = event.target.files?.[0];
  if (!file) return;
  if (!new Set(["image/jpeg", "image/png", "image/webp"]).has(file.type) || file.size > 5 * 1024 * 1024) {
    showNotice("Envie uma imagem JPG, PNG ou WebP de até 5 MB.", true);
    event.target.value = "";
    return;
  }
  try {
    await api("/academia/tela-acesso/logo", {
      method: "PUT",
      body: { foto_base64: await blobToBase64(file), foto_media_type: file.type },
    });
    showNotice("Logo da tela atualizada.");
    await loadMonitorSettings();
  } catch (error) {
    showNotice(error.message, true);
  } finally {
    event.target.value = "";
  }
});

$("#academy-logo-file").addEventListener("change", (event) => {
  const file = event.target.files?.[0];
  if (!file) return;
  if (!new Set(["image/jpeg", "image/png", "image/webp"]).has(file.type) || file.size > 5 * 1024 * 1024) {
    showNotice("Envie uma imagem JPG, PNG ou WebP de até 5 MB.", true);
    event.target.value = "";
  }
});

$("#remove-monitor-logo").addEventListener("click", async () => {
  if (!window.confirm(traduzir("Confirma remover a logo da segunda tela?"))) return;
  try {
    await api("/academia/tela-acesso/logo", { method: "DELETE" });
    showNotice("Logo removida.");
    await loadMonitorSettings();
  } catch (error) {
    showNotice(error.message, true);
  }
});

// O instalador é grande e protegido: pedimos um link assinado de curta duração
// e deixamos o navegador baixar nativamente (sem carregar o arquivo na memória).
$("#installer-download")?.addEventListener("click", async (event) => {
  event.preventDefault();
  const filename = event.currentTarget.dataset.installer;
  try {
    const result = await api(`/downloads/${encodeURIComponent(filename)}/link`, { method: "POST" });
    window.location.assign(result.url);
  } catch (error) {
    showNotice(error.message, true);
  }
});

async function resumeSession() {
  const googleToken = new URLSearchParams(location.hash.replace(/^#/, "")).get("google_token");
  if (googleToken) {
    state.token = googleToken;
    sessionStorage.setItem(tokenStorageKey, state.token);
    history.replaceState({}, document.title, `${location.pathname}${location.search}`);
  }
  const googleParams = new URLSearchParams(location.search);
  // Resultado do retorno do Google: mostrado uma vez e removido da barra de endereço.
  const oauthError = googleParams.get("google_error") || googleParams.get("gmail_error");
  const oauthMessage = oauthError ? apiMessage(oauthError) : googleParams.get("gmail_connected") === "1" ? traduzir("Gmail conectado com sucesso.") : "";
  if (oauthMessage) {
    ["google_error", "gmail_error", "gmail_connected"].forEach((key) => googleParams.delete(key));
    const rest = googleParams.toString();
    history.replaceState({}, document.title, `${location.pathname}${rest ? `?${rest}` : ""}`);
  }
  const googleEmail = googleParams.get("google_email");
  const googleName = googleParams.get("google_name");
  if (googleEmail) {
    const emailField = document.querySelector('#academy-signup-form input[name="email_dono"]');
    if (emailField) emailField.value = googleEmail;
    const nameField = document.querySelector('#academy-signup-form input[name="nome_dono"]');
    if (nameField && googleName) nameField.value = googleName;
    document.querySelector(".login-signup")?.setAttribute("open", "");
  }
  state.token = sessionStorage.getItem(tokenStorageKey);
  if (!state.token) {
    if (oauthMessage && $("#login-feedback")) $("#login-feedback").textContent = oauthMessage;
    return;
  }
  try {
    state.config = await carregarConfiguracao();
    const user = await api("/eu");
    showApplication(user);
    if (oauthMessage) showNotice(oauthMessage, Boolean(oauthError));
  } catch (error) {
    endSession(error.message || "Entre novamente para continuar.");
  }
}

const phonePrefixes = { BR: "+55", BO: "+591", US: "+1", CA: "+1", MX: "+52", AR: "+54", CL: "+56", CO: "+57", PE: "+51", UY: "+598", PY: "+595", VE: "+58", EC: "+593", GB: "+44", PT: "+351", ES: "+34", FR: "+33", DE: "+49", IT: "+39", NL: "+31", BE: "+32", CH: "+41", AT: "+43", IE: "+353", SE: "+46", NO: "+47", DK: "+45", FI: "+358", PL: "+48", CZ: "+420", RO: "+40", GR: "+30", RU: "+7", UA: "+380", IN: "+91", PK: "+92", BD: "+880", CN: "+86", JP: "+81", KR: "+82", ID: "+62", MY: "+60", SG: "+65", TH: "+66", VN: "+84", PH: "+63", AU: "+61", NZ: "+64", ZA: "+27", AO: "+244", MZ: "+258", NG: "+234", KE: "+254", EG: "+20", MA: "+212", IL: "+972", AE: "+971", SA: "+966", TR: "+90" };
const regionForLocale = (locale) => String(locale || "").split("-")[1]?.toUpperCase() || "BR";
const flagForRegion = (region) => [...region].map((char) => String.fromCodePoint(127397 + char.charCodeAt(0))).join("");
function regionForPhoneValue(value) {
  const raw = String(value || "").trim();
  if (!raw) return null;
  const normalized = raw.startsWith("+") ? raw : `+${raw.replace(/\D/g, "")}`;
  return Object.entries(phonePrefixes)
    .filter(([, dial]) => normalized.startsWith(dial))
    .sort((a, b) => b[1].length - a[1].length)[0]?.[0] || null;
}
function syncPhonePrefix(input) {
  const select = input?.parentElement?.querySelector(".phone-prefix-select");
  if (!select) return;
  const detected = regionForPhoneValue(input.value);
  if (detected) {
    select.value = detected;
    delete select.dataset.userSelected;
  }
}
function populateCountryOptions() {
  const names = new Intl.DisplayNames([interfaceLocale || "pt-BR"], { type: "region" });
  let regions = [];
  try { regions = Intl.supportedValuesOf("region").filter((code) => /^[A-Z]{2}$/.test(code)); } catch { regions = ["BR", "BO", "US", "PT", "ES"]; }
  ["#signup-country", "#academy-country", "#preferences-country"].forEach((selector) => {
    const select = $(selector); if (!select) return;
    if (select.tagName !== "SELECT") return;
    const current = select.value || (regionForLocale(interfaceLocale) === "BO" ? "Bolivia" : "Brasil");
    select.replaceChildren(...regions.sort((a, b) => String(names.of(a)).localeCompare(String(names.of(b)))).map((code) => {
      const option = new Option(`${flagForRegion(code)} ${names.of(code)}`, code);
      option.dataset.region = code; if ((code === "BR" && ["Brasil", "BR"].includes(current)) || (code === "BO" && ["Bolivia", "BO"].includes(current)) || current === code || current === names.of(code)) option.selected = true;
      return option;
    }));
  });
}
function preparePhoneFields() {
  const region = regionForLocale(interfaceLocale);
  const prefix = phonePrefixes[region] || "+";
  $$('input[name="telefone"], input[name="telefone_dono"], input[name="contato_telefone"]').forEach((input) => {
    if (input.closest(".signup-phone-field")) return;
    if (input.dataset.phoneReady) {
      const select = input.parentElement?.querySelector(".phone-prefix-select");
      if (select && !select.dataset.userSelected) {
        syncPhonePrefix(input);
        if (!regionForPhoneValue(input.value)) select.value = region;
      }
      return;
    }
    input.dataset.phoneReady = "true";
    const select = document.createElement("select");
    select.className = "phone-prefix-select";
    select.setAttribute("aria-label", traduzir("Prefixo do país"));
    let regions = [];
    try { regions = Intl.supportedValuesOf("region").filter((code) => /^[A-Z]{2}$/.test(code)); } catch { regions = Object.keys(phonePrefixes); }
    const names = new Intl.DisplayNames([interfaceLocale || "pt-BR"], { type: "region" });
    const principal = [region, "BR", "BO", "US", "PT", "ES", "GB", "CA", "AR", "CL", "CO", "MX"];
    regions.sort((a, b) => (principal.indexOf(a) - principal.indexOf(b)) || String(names.of(a)).localeCompare(String(names.of(b))));
    regions.forEach((code) => {
      const dial = phonePrefixes[code] || "—";
      const option = new Option(`${flagForRegion(code)} ${names.of(code)} (${dial})`, code);
      select.append(option);
    });
    select.value = region;
    select.addEventListener("change", () => {
      select.dataset.userSelected = "true";
      const selectedPrefix = phonePrefixes[select.value] || "";
      if (input.value.trim()) input.value = input.value.trim().replace(/^\+\d+\s*/, "").replace(/^/, `${selectedPrefix} `).trim();
    });
    input.parentElement?.insertBefore(select, input);
    input.addEventListener("input", () => {
      if (!select.dataset.userSelected) syncPhonePrefix(input);
    });
    input.addEventListener("blur", () => {
      const value = input.value.trim();
      const selectedPrefix = phonePrefixes[select.value] || prefix;
      if (value && !value.startsWith("+")) input.value = `${selectedPrefix} ${value}`;
    });
    syncPhonePrefix(input);
  });
}

document.addEventListener("DOMContentLoaded", () => {
  window.FrequencyI18n.captureStatic();
  populateCountryOptions();
  preparePhoneFields();
  initBusinessUI();
  traduzirDocumento(interfaceLocale);
  resumeSession();
});






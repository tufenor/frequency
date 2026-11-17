const tokenStorageKey = "frequency.access_token";
const state = { token: null, user: null, students: [], plans: [], config: { somente_consulta: false }, qrPreviewUrl: null, monitorLogoPreviewUrl: null, academyLogoPreviewUrl: null, editingStudentId: null, studentEditRequestId: 0, studentPhotoBlob: null, studentPhotoPreviewUrl: null, studentCameraStream: null };
let interfaceLocale = navigator.language?.toLowerCase().startsWith("es") ? "es-BO" : "pt-BR";

const $ = (selector, root = document) => root.querySelector(selector);
const $$ = (selector, root = document) => Array.from(root.querySelectorAll(selector));

const roleNames = {
  admin_plataforma: "Administrador da plataforma",
  dono: "Dono da academia",
  recepcao: "Recepção",
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
  "EXPERIÊNCIA NA ENTRADA": "EXPERIENCIA DE ACCESO",
  "Configure o segundo monitor, o som de acesso e a identidade visual da academia.": "Configura el segundo monitor, el sonido de acceso y la identidad visual del gimnasio.",
  "Abrir segunda tela": "Abrir segunda pantalla",
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
};

function traduzir(texto) {
  if (typeof texto !== "string") return texto;
  if ((state.user?.idioma || interfaceLocale) === "es-BO") return traducoesEs[texto] || texto;
  const original = Object.entries(traducoesEs).find(([, espanhol]) => espanhol === texto);
  return original ? original[0] : texto;
}

function traduzirDocumento(idioma) {
  interfaceLocale = idioma || "pt-BR";
  document.documentElement.lang = interfaceLocale;
  document.title = traduzir("Frequency — gestão da academia");
  const walker = document.createTreeWalker(document.body, NodeFilter.SHOW_TEXT);
  const nodes = [];
  while (walker.nextNode()) nodes.push(walker.currentNode);
  nodes.forEach((node) => {
    const match = node.nodeValue.match(/^(\s*)([\s\S]*?)(\s*)$/);
    if (!match || !match[2]) return;
    node.nodeValue = `${match[1]}${traduzir(match[2])}${match[3]}`;
  });
  document.querySelectorAll("[placeholder], [aria-label], [title]").forEach((node) => {
    ["placeholder", "aria-label", "title"].forEach((attribute) => {
      const value = node.getAttribute(attribute);
      if (value) node.setAttribute(attribute, traduzir(value));
    });
  });
}

const messages = {
  email_ou_senha_incorretos: "E-mail ou senha incorretos.",
  login_temporariamente_limitado: "Muitas tentativas de acesso. Aguarde alguns minutos e tente novamente.",
  token_invalido: "Sua sessão expirou. Entre novamente.",
  usuario_invalido: "Esta conta não está ativa. Fale com o administrador.",
  sem_permissao: "Sua conta não tem permissão para esta ação.",
  email_ja_cadastrado: "Este e-mail já está cadastrado.",
  academia_ou_email_ja_cadastrado: "Esta academia ou o e-mail informado já está cadastrado. Confira os dados.",
  documento_ou_biometria_ja_cadastrado: "Documento ou biometria já cadastrados.",
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
  plano_nao_cadastrado: "O aluno não tem um plano cadastrado.",
  academia_invalida: "Não foi possível associar o cadastro à academia. Atualize a tela e tente novamente.",
  academia_inativa: "A academia está suspensa. Fale com o administrador.",
  sem_pagamento_em_aberto: "Não há mensalidade em aberto para este aluno.",
  pagamento_ja_pago: "Este pagamento já foi registrado como pago.",
  pagamento_nao_encontrado: "Pagamento não encontrado.",
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
  foto_nao_cadastrada: "Este aluno ainda não tem foto.",
  logo_nao_cadastrada: "Nenhuma logo foi cadastrada.",
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
  try {
    return await fetch(input, init);
  } catch {
    throw new Error("Não foi possível conectar ao Frequency. Verifique a conexão e tente novamente.");
  }
}

async function api(path, options = {}) {
  const headers = new Headers(options.headers || {});
  headers.set("Accept", "application/json");
  if (state.token) headers.set("Authorization", `Bearer ${state.token}`);

  let body = options.body;
  if (body && typeof body === "object" && !(body instanceof FormData) && !(body instanceof URLSearchParams)) {
    headers.set("Content-Type", "application/json");
    body = JSON.stringify(body);
  }

  const response = await fetchFrequency(path, { ...options, headers, body });
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
  if (!response.ok) throw new Error(apiMessage(data?.detail));
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
  sessionStorage.removeItem("frequency.spotify.session");
  sessionStorage.removeItem("frequency.spotify.pending");

  const loginLocale = state.user?.idioma || interfaceLocale;
  sessionStorage.removeItem(tokenStorageKey);
  state.token = null;
  state.user = null;
  state.config = { somente_consulta: false };
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
  const settings = await api("/academia/tela-acesso");
  $("#monitor-key-status").textContent = settings.chave_ativa
    ? "Código ativo. Abra /monitor no segundo computador e informe o código gerado."
    : "A tela ainda não tem um código ativo.";
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

function badge(text, tone = "") {
  const tones = { good: "badge badge-good", warn: "badge badge-warn", bad: "badge badge-bad" };
  return element("span", traduzir(text || "—"), tones[tone] || "badge");
}

function setPage(pageName) {
  const pageRoles = {
    equipe: ["dono"],
    academias: ["admin_plataforma"],
    presencas: ["dono", "recepcao"],
    "tela-aluno": ["dono"],
  };
  if (pageRoles[pageName] && !pageRoles[pageName].includes(state.user?.papel)) {
    showNotice("Sua conta não tem acesso a esta área.", true);
    return;
  }
  if (pageName === "equipe" && state.config.somente_consulta) {
    showNotice("A equipe não faz parte da cópia de consulta na nuvem.", true);
    return;
  }

  $$("[data-view]").forEach((page) => { page.hidden = page.dataset.view !== pageName; });
  $$("[data-page]").forEach((button) => button.classList.toggle("active", button.dataset.page === pageName));
  showNotice("");

  const loaders = {
    dashboard: loadDashboard,
    alunos: loadStudents,
    pagamentos: async () => {
      await loadStudents();
      await loadAcademyQr();
    },
    presencas: loadPresencas,
    planos: loadPlans,
    academias: loadAcademies,
    equipe: loadReceptionTeam,
    "tela-aluno": loadMonitorSettings,
  };
  if (loaders[pageName]) loaders[pageName]().catch((error) => showNotice(error.message, true));
}

function showApplication(user) {
  state.user = { ...user, idioma: user.idioma || "pt-BR", moeda: user.moeda || "BRL" };
  user = state.user;
  traduzirDocumento(user.idioma);
  $("#login-view").hidden = true;
  $("#app-view").hidden = false;
  $("#account-name").textContent = user.nome || "Usuário";
  $("#account-role").textContent = traduzir(roleNames[user.papel] || "Usuário");
  $("#plan-value-label").textContent = `${traduzir("Valor")} (${user.moeda}) *`;
  const somenteConsulta = state.config.somente_consulta;
  $("#sync-mode-pill").hidden = !somenteConsulta;

  $$('[data-role]').forEach((node) => { node.hidden = node.dataset.role !== user.papel; });
  $$('[data-roles]').forEach((node) => {
    node.hidden = !node.dataset.roles.split(/\s+/).includes(user.papel);
  });
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
  setPage(user.papel === "admin_plataforma" ? "academias" : "dashboard");
}

async function loadDashboard() {
  const [students, situation] = await Promise.all([
    api("/alunos"),
    api("/alunos/situacao"),
  ]);
  state.students = students;

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
    card.append(element("p", `${plan.duracao_dias} ${state.user?.idioma === "es-BO" ? "días" : "dias"}`, "plan-duration"));
    return card;
  }));
}

function renderStudents() {
  const query = $("#student-search").value.trim().toLocaleLowerCase(state.user?.idioma || interfaceLocale);
  const students = state.students.filter((student) => {
    if (!query) return true;
    return [student.nome, student.documento].some((value) =>
      String(value || "").toLocaleLowerCase(state.user?.idioma || interfaceLocale).includes(query)
    );
  });
  const body = $("#students-table");
  body.replaceChildren(...students.map((student) => {
    const row = element("tr");
    row.append(element("td", student.nome), element("td", student.documento));
    row.append(element("td", student.plano || traduzir("Sem plano")));
    const status = element("td");
    status.append(badge(statusLabels[student.status] || student.status || "—", student.status === "ativo" ? "good" : "warn"));
    row.append(status);
    const actions = element("td", undefined, "table-actions");
    const paymentsButton = element("button", traduzir("Pagamentos"), "button button-quiet button-small");
    paymentsButton.type = "button";
    paymentsButton.dataset.studentPayments = String(student.id);
    actions.append(paymentsButton);
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
    if (!paid && !state.config.somente_consulta) {
      const payButton = element("button", traduzir("Registrar pagamento"), "button button-primary button-small");
      payButton.type = "button";
      payButton.dataset.payId = String(payment.id);
      actionCell.append(payButton);
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
      digital_nao_cadastrada: "Biometria não cadastrada",
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
  const body = $("#academies-table");
  body.replaceChildren(...academies.map((academy) => {
    const row = element("tr");
    row.append(element("td", academy.nome), element("td", academy.pais));
    const statusCell = element("td");
    statusCell.append(badge(academy.ativa ? "Ativa" : "Suspensa", academy.ativa ? "good" : "bad"));
    row.append(statusCell);
    const actions = element("td");
    if (!state.config.somente_consulta) {
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
  $("#capture-student-photo").hidden = true;
  $("#cancel-student-camera").hidden = true;
  $("#start-student-camera").hidden = false;
  renderStudentPhotoPreview();
}

function clearStudentPhoto() {
  stopStudentCamera();
  if (state.studentPhotoPreviewUrl) URL.revokeObjectURL(state.studentPhotoPreviewUrl);
  state.studentPhotoPreviewUrl = null;
  state.studentPhotoBlob = null;
  $("#student-photo-authorized").checked = false;
  $("#student-photo-file").value = "";
  renderStudentPhotoPreview();
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

$("#logout-button").addEventListener("click", () => endSession("Você saiu do Frequency."));

$$("[data-page]").forEach((button) => button.addEventListener("click", () => setPage(button.dataset.page)));
$$('[data-go="alunos"]').forEach((button) => button.addEventListener("click", () => setPage("alunos")));

$("#refresh-dashboard").addEventListener("click", () => loadDashboard().catch((error) => showNotice(error.message, true)));
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
    $("#student-photo-preview").hidden = true;
    $("#student-photo-placeholder").hidden = true;
    await video.play();
    button.hidden = true;
    $("#capture-student-photo").hidden = false;
    $("#cancel-student-camera").hidden = false;
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
    stopStudentCamera();
    setStudentPhoto(photo);
    $("#student-photo-authorized").focus();
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
  form.reset();
  form.hidden = true;
  form.setAttribute("data-write-collapsed", "");
  state.editingStudentId = null;
}

async function openStudentEditForm(studentId) {
  const form = $("#student-edit-form");
  clearStudentPhoto();
  $("#student-form").reset();
  $("#student-form").hidden = true;
  closeStudentEditForm();
  const requestId = state.studentEditRequestId;
  try {
    const student = await api("/alunos/" + encodeURIComponent(studentId));
    if (requestId !== state.studentEditRequestId || !state.user) return;
    form.elements.namedItem("documento").value = student.documento || "";
    form.elements.namedItem("telefone").value = student.telefone || "";
    form.elements.namedItem("data_nascimento").value = student.data_nascimento || "";
    state.editingStudentId = Number(studentId);
    form.hidden = false;
    form.removeAttribute("data-write-collapsed");
    form.elements.namedItem("documento").focus();
    form.scrollIntoView({ behavior: "smooth", block: "start" });
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
    data_nascimento: values.data_nascimento || null,
    plano_id: values.plano_id ? Number(values.plano_id) : null,
    id_biometria: values.id_biometria ? Number(values.id_biometria) : null,
  };
  try {
    if (state.studentPhotoBlob) {
      body.foto_base64 = await blobToBase64(state.studentPhotoBlob);
      body.foto_media_type = state.studentPhotoBlob.type;
    }
    await api("/alunos", { method: "POST", body });
    form.reset();
    clearStudentPhoto();
    form.hidden = true;
    form.setAttribute("data-write-collapsed", "");
    $("#student-search").value = "";
    showNotice("Aluno cadastrado.");
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
  try {
    await api("/alunos/" + encodeURIComponent(state.editingStudentId), {
      method: "PATCH",
      body: {
        documento: values.documento.trim(),
        telefone: values.telefone.trim() || null,
        data_nascimento: values.data_nascimento || null,
      },
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

$("#plan-form").addEventListener("submit", async (event) => {
  event.preventDefault();
  const form = event.currentTarget;
  const values = formObject(form);
  try {
    await api("/planos", {
      method: "POST",
      body: { nome: values.nome.trim(), valor: Number(values.valor), duracao_dias: Number(values.duracao_dias) },
    });
    form.reset();
    showNotice("Plano criado.");
    await loadPlans();
  } catch (error) {
    showNotice(error.message, true);
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

$("#academy-form").addEventListener("submit", async (event) => {
  event.preventDefault();
  const form = event.currentTarget;
  const values = formObject(form);
  const logo = $("#academy-logo-file").files?.[0];
  if (logo && (!new Set(["image/jpeg", "image/png", "image/webp"]).has(logo.type) || logo.size > 5 * 1024 * 1024)) {
    showNotice("Envie uma imagem JPG, PNG ou WebP de até 5 MB.", true);
    return;
  }
  try {
    const body = {
      nome_academia: values.nome_academia.trim(),
      pais: values.pais.trim(),
      nome_dono: values.nome_dono.trim(),
      email_dono: values.email_dono.trim(),
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
  }
});

$("#academies-table").addEventListener("click", async (event) => {
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

$("#generate-monitor-key").addEventListener("click", async () => {
  if (!window.confirm(traduzir("Confirma gerar outro código? O monitor atual será desconectado."))) return;
  try {
    const result = await api("/academia/tela-acesso/chave", { method: "POST" });
    $("#monitor-key-value").value = result.chave;
    $("#monitor-key-wrap").hidden = false;
    $("#copy-monitor-key").hidden = false;
    $("#monitor-key-status").textContent = traduzir("O código foi mostrado uma única vez. Guarde-o apenas no computador do monitor.");
    showNotice("Código gerado. Copie-o para o computador do monitor.");
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

async function resumeSession() {
  state.token = sessionStorage.getItem(tokenStorageKey);
  if (!state.token) return;
  try {
    state.config = await carregarConfiguracao();
    const user = await api("/eu");
    showApplication(user);
  } catch (error) {
    endSession(error.message || "Entre novamente para continuar.");
  }
}

traduzirDocumento(interfaceLocale);
resumeSession();

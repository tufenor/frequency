import getpass

from psycopg import errors

from database import get_connection
from seguranca import gerar_hash


with get_connection() as conn:
    academias = conn.execute(
        "SELECT id, nome, ativa FROM academias ORDER BY id"
    ).fetchall()

if not academias:
    raise SystemExit("Não há academias cadastradas. Crie a academia antes do dono.")

print("Academias cadastradas (use o ID numérico da primeira coluna):")
for academia in academias:
    situacao = "ativa" if academia["ativa"] else "inativa"
    print(f"ID {academia['id']}: {academia['nome']} ({situacao})")

try:
    academia_id = int(input("ID da academia do dono: ").strip())
except ValueError:
    raise SystemExit("Digite o ID numérico exibido na lista.")

academia = next((item for item in academias if item["id"] == academia_id), None)
if academia is None:
    raise SystemExit("Esse ID não corresponde a uma academia cadastrada.")
if not academia["ativa"]:
    raise SystemExit("A academia está inativa; nenhum dono foi criado.")

nome = input("Nome do dono: ").strip()
email = input("E-mail: ").strip().lower()
senha = getpass.getpass("Senha (não aparece enquanto digita): ")

if not nome or not email:
    raise SystemExit("Nome e e-mail são obrigatórios.")
if len(email) > 254:
    raise SystemExit("O e-mail não pode ter mais de 254 caracteres.")
if not 8 <= len(senha) <= 256:
    raise SystemExit("A senha precisa ter entre 8 e 256 caracteres.")

try:
    with get_connection() as conn:
        dono_ativo = conn.execute(
            "SELECT id FROM usuarios "
            "WHERE academia_id = %s AND papel = 'dono' AND ativo IS TRUE",
            (academia_id,),
        ).fetchone()
    if dono_ativo is not None:
        confirmacao = input(
            "Já existe dono ativo nesta academia. "
            "Para criar outro, digite CRIAR: "
        ).strip()
        if confirmacao != "CRIAR":
            raise SystemExit("Nenhum dono foi criado.")

    with get_connection() as conn:
        email_existente = conn.execute(
            "SELECT id FROM usuarios WHERE email = %s",
            (email,),
        ).fetchone()
        if email_existente is not None:
            raise SystemExit("Esse e-mail já está cadastrado. Use outro e-mail.")

        dono = conn.execute(
            "INSERT INTO usuarios "
            "(academia_id, nome, email, senha_hash, papel, ativo) "
            "VALUES (%s, %s, %s, %s, 'dono', TRUE) RETURNING id",
            (academia_id, nome, email, gerar_hash(senha)),
        ).fetchone()
except errors.UniqueViolation:
    raise SystemExit("Esse e-mail já está cadastrado. Use outro e-mail.")

print(f"Dono criado para a academia selecionada. ID: {dono['id']}")

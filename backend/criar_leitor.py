import hashlib
import secrets

from database import get_connection


with get_connection() as conn:
    academias = conn.execute(
        "SELECT id, nome, ativa FROM academias ORDER BY id"
    ).fetchall()

if not academias:
    raise SystemExit("Não há academias cadastradas. Crie a academia antes do leitor.")

print("Academias cadastradas (use o ID numérico da primeira coluna):")
for academia in academias:
    situacao = "ativa" if academia["ativa"] else "inativa"
    print(f"ID {academia['id']}: {academia['nome']} ({situacao})")

try:
    academia_id = int(input("ID da academia deste leitor: ").strip())
except ValueError:
    raise SystemExit("Digite o ID numérico exibido na lista.")

academia = next((item for item in academias if item["id"] == academia_id), None)
if academia is None:
    raise SystemExit("Esse ID não corresponde a uma academia cadastrada.")
if not academia["ativa"]:
    raise SystemExit("A academia está inativa; nenhum leitor foi criado.")

nome = input("Nome deste leitor/catraca: ").strip()
if not nome:
    raise SystemExit("Digite um nome para o leitor.")
if len(nome) > 160:
    raise SystemExit("O nome do leitor não pode ter mais de 160 caracteres.")

with get_connection() as conn:
    leitor_existente = conn.execute(
        "SELECT id FROM leitores "
        "WHERE academia_id = %s AND lower(btrim(nome)) = lower(%s)",
        (academia_id, nome),
    ).fetchone()

if leitor_existente is not None:
    raise SystemExit(
        "Já existe um leitor com esse nome nesta academia. Nenhum duplicado foi criado."
    )

chave = secrets.token_urlsafe(32)
chave_hash = hashlib.sha256(chave.encode("utf-8")).hexdigest()

with get_connection() as conn:
    leitor = conn.execute(
        "INSERT INTO leitores (academia_id, nome, chave_hash) "
        "VALUES (%s, %s, %s) RETURNING id",
        (academia_id, nome, chave_hash),
    ).fetchone()

print(f"Leitor criado. ID: {leitor['id']}")
print("COPIE E GUARDE ESTA CHAVE; ela será exibida apenas agora:")
print(chave)

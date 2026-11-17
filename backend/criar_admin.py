import getpass

from database import get_connection
from seguranca import gerar_hash


nome = input("Nome do administrador: ").strip()
email = input("E-mail do administrador: ").strip().lower()
senha = getpass.getpass("Senha (não aparece enquanto você digita): ")

if not nome or not email:
    raise SystemExit("Digite o nome e o e-mail do administrador.")

if len(email) > 254:
    raise SystemExit("O e-mail não pode ter mais de 254 caracteres.")

if not 8 <= len(senha) <= 256:
    raise SystemExit("A senha precisa ter entre 8 e 256 caracteres.")

with get_connection() as conn:
    existente = conn.execute(
        "SELECT id FROM usuarios WHERE email = %s",
        (email,),
    ).fetchone()

    if existente is not None:
        raise SystemExit("Esse e-mail já está cadastrado. Use outro e-mail.")

    administrador = conn.execute(
        "INSERT INTO usuarios "
        "(academia_id, nome, email, senha_hash, papel, ativo) "
        "VALUES (NULL, %s, %s, %s, 'admin_plataforma', TRUE) "
        "RETURNING id",
        (nome, email, gerar_hash(senha)),
    ).fetchone()

print(f"Administrador criado. ID: {administrador['id']}")

import getpass

from database import get_connection
from seguranca import gerar_hash


email = input("E-mail do administrador da plataforma: ").strip().lower()
nova_senha = getpass.getpass("Nova senha (não aparece enquanto digita): ")

if not email:
    raise SystemExit("Digite o e-mail do administrador.")

if not 8 <= len(nova_senha) <= 256:
    raise SystemExit("A senha precisa ter entre 8 e 256 caracteres.")

with get_connection() as conn:
    administrador = conn.execute(
        "UPDATE usuarios "
        "SET senha_hash = %s "
        "WHERE email = %s AND papel = 'admin_plataforma' AND ativo "
        "RETURNING id",
        (gerar_hash(nova_senha), email),
    ).fetchone()

if administrador is None:
    raise SystemExit(
        "Não encontrei uma conta ativa de administrador com esse e-mail."
    )

print("Senha do administrador atualizada.")

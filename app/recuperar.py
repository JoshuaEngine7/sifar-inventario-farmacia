"""Recuperación de acceso desde la PC servidor (cuando se olvidan las contraseñas,
incluso la del admin). Solo reescribe el hash de la contraseña: NUNCA toca
productos, movimientos ni ningún otro dato.

Uso:
  python -m app.recuperar                 → lista los usuarios
  python -m app.recuperar "Nombre exacto" → resetea a ese usuario
  python -m app.recuperar 1               → resetea al usuario número 1 de la lista

Al usuario reseteado se le asigna una contraseña temporal (que imprime en pantalla)
y se le exige cambiarla en su próximo inicio de sesión.
"""
import secrets
import sys

from .auth import hash_password
from .db import SessionLocal
from .models import Usuario


def _password_temporal() -> str:
    return "Acceso-" + secrets.token_hex(3)


def _usuarios(session) -> list[Usuario]:
    return session.query(Usuario).filter(Usuario.nombre != "Migración Excel").order_by(Usuario.id).all()


def listar(session) -> None:
    print("Usuarios del sistema:\n")
    for i, u in enumerate(_usuarios(session), start=1):
        estado = "activo" if u.activo else "INACTIVO"
        print(f"  {i}. {u.nombre}  ({u.rol}, {estado})")
    print("\nPara resetear:  python -m app.recuperar \"Nombre exacto\"   (o el número)")


def resetear(session, seleccion: str) -> None:
    usuarios = _usuarios(session)
    objetivo = None
    if seleccion.isdecimal() and 1 <= int(seleccion) <= len(usuarios):
        objetivo = usuarios[int(seleccion) - 1]
    else:
        objetivo = next((u for u in usuarios if u.nombre == seleccion), None)

    if objetivo is None:
        print(f"No se encontró un usuario con '{seleccion}'.\n")
        listar(session)
        sys.exit(1)

    temporal = _password_temporal()
    objetivo.password_hash = hash_password(temporal)
    objetivo.debe_cambiar_password = True
    objetivo.activo = True  # reactivar por si estaba desactivado y es el único admin
    session.commit()
    print("\n==============================================")
    print(f"  Acceso restablecido para: {objetivo.nombre}")
    print(f"  Contraseña temporal:      {temporal}")
    print("  (deberá cambiarla al iniciar sesión)")
    print("==============================================")


def run(seleccion: str | None) -> None:
    with SessionLocal() as session:
        if seleccion is None:
            listar(session)
        else:
            resetear(session, seleccion)


if __name__ == "__main__":
    run(sys.argv[1] if len(sys.argv) > 1 else None)

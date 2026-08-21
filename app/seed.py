"""Crea las tablas y siembra catálogos y usuarios iniciales. Idempotente."""
import secrets

import bcrypt

from .db import Base, SessionLocal, engine
from .models import Causa, Tipo, Ubicacion, Usuario

TIPOS = [
    "Medicamento", "Antibiótico", "Antibiótico inyectable", "Inyectable",
    "Medicamento controlado", "Material", "Material RPBI", "Material dental",
]
UBICACIONES = [
    "Farmacia", "Farmacia controlado", "Consultorio dental",
    "Carro rojo P1", "Carro rojo P2", "Carro rojo P3", "Carro rojo P4", "Carro rojo P5",
]
CAUSAS = [
    "Tratamiento / receta a paciente", "Caducidad", "Donación",
    "Devolución", "Ajuste por conteo", "Traslado entre áreas",
]

# Usuarios de demostración; debe_cambiar_password obliga a definir una
# contraseña propia en el primer inicio de sesión (igual que en producción).
USUARIOS = [
    ("Admin Demo", "admin", "demo1234", True, True),
    ("Dra. Médico Demo", "medico", "demo1234", True, True),
    ("Enf. Enfermería Demo", "enfermeria", "demo1234", True, True),
    # Usuario del sistema para atribuir el historial migrado; nunca inicia sesión.
    ("Migración Excel", "admin", secrets.token_urlsafe(32), False, False),
]


def hash_password(plain: str) -> str:
    return bcrypt.hashpw(plain.encode(), bcrypt.gensalt()).decode()


def run() -> None:
    Base.metadata.create_all(engine)
    with SessionLocal() as session:
        for model, nombres in ((Tipo, TIPOS), (Ubicacion, UBICACIONES), (Causa, CAUSAS)):
            existentes = {n for (n,) in session.query(model.nombre)}
            session.add_all(model(nombre=n) for n in nombres if n not in existentes)

        existentes = {n for (n,) in session.query(Usuario.nombre)}
        for nombre, rol, password, cambiar, activo in USUARIOS:
            if nombre not in existentes:
                session.add(Usuario(
                    nombre=nombre, rol=rol, password_hash=hash_password(password),
                    debe_cambiar_password=cambiar, activo=activo,
                ))
        session.commit()


if __name__ == "__main__":
    run()
    print("seed ok")

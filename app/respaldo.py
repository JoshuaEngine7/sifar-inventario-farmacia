"""Respaldo consistente de la BD (funciona aunque la app esté corriendo).

Uso: python -m app.respaldo [carpeta_destino]
"""
import sqlite3
import sys
from datetime import datetime
from pathlib import Path

from .db import DB_PATH


def run(destino: str = "respaldo") -> Path:
    # Relativo a la carpeta de la BD, no al directorio de trabajo: si se ejecuta
    # desde otra ruta, el respaldo debe quedar junto a la base que protege.
    carpeta = Path(destino)
    if not carpeta.is_absolute():
        carpeta = DB_PATH.parent / carpeta
    carpeta.mkdir(parents=True, exist_ok=True)
    salida = carpeta / f"farmacia_{datetime.now():%Y-%m-%d_%H%M}.db"
    # VACUUM INTO crea una copia íntegra sin detener el servidor.
    sqlite3.connect(DB_PATH).execute("VACUUM INTO ?", (str(salida),))
    return salida


if __name__ == "__main__":
    ruta = run(sys.argv[1] if len(sys.argv) > 1 else "respaldo")
    print(f"Respaldo creado: {ruta}")

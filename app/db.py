from pathlib import Path

from sqlalchemy import create_engine, event
from sqlalchemy.orm import DeclarativeBase, sessionmaker

DB_PATH = Path(__file__).resolve().parent.parent / "farmacia.db"

engine = create_engine(f"sqlite:///{DB_PATH}", connect_args={"check_same_thread": False})


@event.listens_for(engine, "connect")
def _set_sqlite_pragmas(dbapi_connection, connection_record):
    # WAL: lectores no bloquean al escritor; clave para el multiusuario en LAN.
    # foreign_keys: SQLite no las aplica por defecto.
    cursor = dbapi_connection.cursor()
    cursor.execute("PRAGMA journal_mode=WAL")
    cursor.execute("PRAGMA foreign_keys=ON")
    cursor.execute("PRAGMA busy_timeout=5000")
    cursor.close()


# Nota sobre transacciones: el driver pysqlite abre la transacción al primer INSERT
# (no antes de un SAVEPOINT). Por eso las operaciones masivas que deben ser
# todo-o-nada NO usan savepoints: van en una sola transacción y hacen rollback
# completo ante cualquier error (ver app/reset_stock.py).


SessionLocal = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)


class Base(DeclarativeBase):
    pass


def get_session():
    session = SessionLocal()
    try:
        yield session
    finally:
        session.close()

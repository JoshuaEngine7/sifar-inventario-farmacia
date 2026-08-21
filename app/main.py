from fastapi import FastAPI
from fastapi.responses import RedirectResponse
from starlette.middleware.sessions import SessionMiddleware

from . import (alertas, api, auth, captura, config, historial, inventario, mantenimiento,
               productos, reporte, services, traslado, usuarios)
from .db import Base, SessionLocal, engine
from .models import Causa, Configuracion
from .seed import CAUSAS

# Al actualizar la app sobre una BD existente: crea tablas nuevas (create_all
# solo agrega tablas, no columnas), agrega columnas que falten y siembra config.
Base.metadata.create_all(engine)
with engine.connect() as _c:
    _cols = {fila[1] for fila in _c.exec_driver_sql("PRAGMA table_info(usuarios)")}
    if "puede_crear_productos" not in _cols:
        _c.exec_driver_sql(
            "ALTER TABLE usuarios ADD COLUMN puede_crear_productos BOOLEAN NOT NULL DEFAULT 0")
        _c.commit()
with SessionLocal() as _s:
    _existentes = {c.clave for c in _s.query(Configuracion)}
    for _clave, _valor in services.CONFIG_DEFECTOS.items():
        if _clave not in _existentes:
            _s.add(Configuracion(clave=_clave, valor=_valor))
    # Causas nuevas del catálogo también llegan a las BD ya desplegadas.
    _causas = {c.nombre for c in _s.query(Causa)}
    _s.add_all(Causa(nombre=n) for n in CAUSAS if n not in _causas)
    _s.commit()

app = FastAPI(title=f"{config.APP_NOMBRE} — Sistema de Inventario de Farmacia")
app.add_middleware(SessionMiddleware, secret_key=auth.get_secret_key(), max_age=8 * 3600)

app.include_router(auth.router)
app.include_router(usuarios.router)
app.include_router(captura.router)
app.include_router(inventario.router)
app.include_router(alertas.router)
app.include_router(reporte.router)
app.include_router(api.router)
app.include_router(productos.router)
app.include_router(traslado.router)
app.include_router(historial.router)
app.include_router(mantenimiento.router)


@app.get("/health")
def health():
    return {"status": "ok"}


@app.get("/")
def index():
    return RedirectResponse(url="/inventario", status_code=302)

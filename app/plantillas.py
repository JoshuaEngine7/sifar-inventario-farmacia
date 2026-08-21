"""Instancia única de Jinja2Templates.

Vive en su propio módulo para que los routers la importen directamente,
sin el import circular hacia main (antes: `from .main import templates`
dentro de cada función).
"""
from pathlib import Path

from fastapi.templating import Jinja2Templates

from . import config, services

templates = Jinja2Templates(directory=Path(__file__).resolve().parent / "templates")
templates.env.globals["APP_NOMBRE"] = config.APP_NOMBRE
templates.env.globals["UNIDAD"] = config.UNIDAD
# Callable: cada página renderizada lee el valor vigente configurado por el admin.
templates.env.globals["minutos_inactividad"] = services.minutos_inactividad

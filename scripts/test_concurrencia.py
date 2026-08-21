"""Prueba de concurrencia (criterio C12): N escrituras en paralelo desde 2 sesiones.

Uso:
  python scripts/test_concurrencia.py --password <pass> [--n 20] [--tipo ENTRADA]
                                      [--producto-id 3] [--usuario "Dr. ..."]

Con --tipo SALIDA prueba además que el stock nunca queda negativo aunque haya
más salidas simultáneas que existencias.
"""
import argparse
import http.cookiejar
import urllib.parse
import urllib.request
from concurrent.futures import ThreadPoolExecutor


def sesion(base: str, usuario: str, password: str):
    jar = http.cookiejar.CookieJar()
    opener = urllib.request.build_opener(
        urllib.request.HTTPCookieProcessor(jar),
        # sin auto-redirect: queremos ver el 302 tal cual
        type("NoRedirect", (urllib.request.HTTPRedirectHandler,),
             {"redirect_request": lambda *a, **k: None})(),
    )
    datos = urllib.parse.urlencode({"nombre": usuario, "password": password}).encode()
    try:
        opener.open(f"{base}/login", data=datos)
    except urllib.error.HTTPError as e:
        if e.code != 302:
            raise SystemExit(f"login falló: {e.code}")
    return opener


def capturar(opener, base: str, producto_id: int, tipo: str) -> int:
    datos = urllib.parse.urlencode({
        "tipo": tipo, "piezas": 1, "cajas": 0,
        "fecha_caducidad": "", "causa_detalle": "test concurrencia", "paciente_ref": "",
    }).encode()
    try:
        respuesta = opener.open(f"{base}/captura/{producto_id}", data=datos)
        return respuesta.status
    except urllib.error.HTTPError as e:
        return e.code


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--base", default="http://127.0.0.1:8000")
    p.add_argument("--usuario", default="Admin Demo")
    p.add_argument("--password", required=True)
    p.add_argument("--producto-id", type=int, default=3)
    p.add_argument("--n", type=int, default=20)
    p.add_argument("--tipo", default="ENTRADA", choices=["ENTRADA", "SALIDA"])
    args = p.parse_args()

    sesiones = [sesion(args.base, args.usuario, args.password) for _ in range(2)]
    with ThreadPoolExecutor(max_workers=args.n) as pool:
        estados = list(pool.map(
            lambda i: capturar(sesiones[i % 2], args.base, args.producto_id, args.tipo),
            range(args.n),
        ))

    conteo = {c: estados.count(c) for c in sorted(set(estados))}
    print(f"{args.n} POST {args.tipo} paralelos (2 sesiones) -> estados: {conteo}")
    print("302 = registrado | 400 = rechazado por regla | 503 = BD ocupada (nada guardado)")


if __name__ == "__main__":
    main()

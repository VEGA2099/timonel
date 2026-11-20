"""
End-to-end tests for Timonel (Playwright for Python) · Pruebas de punta a punta de Timonel.

    pip install playwright && playwright install chromium
    python -m unittest tests/test_timonel.py -v

Arranca una COPIA del tablero en una carpeta temporal, en el puerto 3998, con servicios
falsos en 41xx. Nunca toca tu config.json real.
Opcional: AXE_JS=ruta/a/axe.min.js para el escaneo de accesibilidad; CHROME=ruta a Chrome.
"""
import concurrent.futures
import json
import os
import shutil
import subprocess
import sys
import tempfile
import threading
import time
import unittest
import urllib.error
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from playwright.sync_api import sync_playwright

RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PUERTO = 3998
B = f"http://localhost:{PUERTO}"
SECRETO = "CLAVE-SUPER-SECRETA-123"


# ---------- servicios falsos ----------
class Falso(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def do_GET(self):
        p = self.server.server_port
        if p == 4104 and self.path.startswith("/api/ps"):   # imita Ollama
            cuerpo = json.dumps({"models": [{"name": "qwen2.5:7b", "size_vram": 3435973837}, {"name": "nomic-embed-text", "size_vram": 1048576}]}).encode()
            self.send_response(200); self.send_header("Content-Type", "application/json"); self.send_header("Content-Length", str(len(cuerpo))); self.end_headers(); self.wfile.write(cuerpo); return
        if p == 4104 and self.path.startswith("/api/v3/calendar?start=20"):
            cuerpo = json.dumps([{"series": {"title": "Frieren"}, "airDateUtc": "2026-11-20T15:30:00Z"},
                                 {"series": {"title": "Dandadan"}, "airDateUtc": "2026-11-21T16:00:00Z"}]).encode()
            self.send_response(200); self.send_header("Content-Type", "application/json"); self.send_header("Content-Length", str(len(cuerpo))); self.end_headers(); self.wfile.write(cuerpo); return
        if p == 4104:                                    # imita Sonarr: clave desde config.xml
            if self.headers.get("X-Api-Key") != "ARR-KEY-XML":
                self.send_response(401); self.end_headers(); return
            datos = {"/api/v3/queue/status": {"totalCount": 3}, "/api/v3/health": [{"type": "warning"}],
                     "/api/v3/wanted/missing?pageSize=1": {"totalRecords": 12}}.get(self.path, {})
            cuerpo = json.dumps(datos).encode(); tipo = "application/json"
            self.send_response(200); self.send_header("Content-Type", tipo); self.send_header("Content-Length", str(len(cuerpo))); self.end_headers(); self.wfile.write(cuerpo); return
        if p == 4103:                                    # API con clave
            if self.headers.get("X-Api-Key") != SECRETO:
                self.send_response(401); self.end_headers(); return
            cuerpo = json.dumps({"usuarios": 5, "errores": [1, 2], "estado": {"cola": 0}}).encode()
            tipo = "application/json"
        else:
            cuerpo = ("<title>Mi App viva</title>" if p == 4101 else "<title>Otra cosa</title>").encode()
            tipo = "text/html"
        self.send_response(200)
        self.send_header("Content-Type", tipo)
        self.send_header("Content-Length", str(len(cuerpo)))
        self.end_headers()
        self.wfile.write(cuerpo)

    do_HEAD = do_GET


FALSOS = {}


def levantar(puerto):
    s = ThreadingHTTPServer(("127.0.0.1", puerto), Falso)
    threading.Thread(target=s.serve_forever, daemon=True).start()
    FALSOS[puerto] = s


def config_semilla():
    return {
        "version": 2, "idioma": "es", "titulo": "Timonel de Prueba", "puerto": PUERTO, "discos": "auto",
        "buscador": "http://127.0.0.1:4101/buscar?q=", "intervalo_s": 5,
        "barra": [{"tipo": "reloj"}, {"tipo": "saludo", "nombre": "Ana"}, {"tipo": "sistema"},
                  {"tipo": "clima", "lugar": "Lisboa", "lat": 38.72, "lon": -9.14}],
        "proveedores": {"falso": {"url": "http://127.0.0.1:4103", "cabeceras": {"X-Api-Key": SECRETO}},
                        "sonarr": {"url": "http://127.0.0.1:4104", "claveDesde": "sonarr-config.xml"}},
        "mcp": {"activo": True, "escritura": False},
        "tema": {"encabezado": "caja", "tarjeta": "filete"},
        "grupos": [
            {"nombre": "Servicios", "pestana": "Taller", "items": [
                {"id": "vivo", "nombre": "Mi App", "desc": "servicio que responde", "url": "http://127.0.0.1:4101", "vigilar": True},
                {"id": "otro", "nombre": "ComfyUI falso", "url": "http://127.0.0.1:4102", "vigilar": True, "contiene": "ComfyUI"},
                {"id": "caido", "nombre": "Apagado", "url": "http://127.0.0.1:4199", "vigilar": True, "lanzar": "C:\\no\\existe.exe"},
                {"id": "api", "nombre": "Con API", "url": "http://127.0.0.1:4101", "vigilar": True,
                 "widget": {"tipo": "api", "url": "/datos", "proveedor": "falso",
                            "mapeo": {"Usuarios": "usuarios", "Errores": "errores.length", "Cola": "estado.cola"},
                            "resaltar": {"Errores": [{"cuando": "gt", "valor": 0, "nivel": "peligro"}]}}},
                {"id": "ping", "nombre": "Router", "ping": "127.0.0.1", "vigilar": True},
                {"id": "ollama", "nombre": "Ollama", "url": "http://127.0.0.1:4104", "vigilar": True,
                 "widget": {"tipo": "api", "consultas": [{"url": "/api/ps", "mapeo": {"En memoria": "models.length"},
                            "lista": {"de": "models", "texto": "name", "detalle": "size_vram", "formato": "bytes"}}]}},
                {"id": "detenible", "nombre": "Servicio de prueba", "url": "http://127.0.0.1:4107", "vigilar": True, "lanzar": "C:\\no\\existe.exe"},
                {"id": "sonarr", "nombre": "Sonarr", "url": "http://127.0.0.1:4101", "vigilar": True,
                 "widget": {"tipo": "api", "proveedor": "sonarr", "consultas": [
                     {"url": "/api/v3/wanted/missing?pageSize=1", "mapeo": {"Faltan": "totalRecords"}},
                     {"url": "/api/v3/queue/status", "mapeo": {"En cola": "totalCount"}},
                     {"url": "/api/v3/health", "mapeo": {"Avisos": "length"}},
                     {"url": "/api/v3/calendar?start={hoy}&end={en7dias}", "lista": {"etiqueta": "Próximos", "texto": "series.title", "detalle": "airDateUtc", "formato": "fecha"}}],
                     "resaltar": {"Avisos": [{"cuando": "gt", "valor": 0, "nivel": "aviso"}]}}},
            ], "grupos": [
                {"nombre": "Subgrupo", "items": [
                    {"id": "punto", "nombre": "Estilo punto", "url": "http://127.0.0.1:4101", "vigilar": True, "estadoEstilo": "punto"},
                    {"id": "basico", "nombre": "Estilo básico", "url": "http://127.0.0.1:4101", "vigilar": True, "estadoEstilo": "basico"}]}]},
            {"nombre": "Raros", "pestana": "Taller", "items": [
                {"id": "acentos", "nombre": "Ñandú 🦤 Camión " + "largo " * 20, "url": "https://ejemplo.com"},
                {"id": "xss", "nombre": "<img src=x onerror=window.__xss=1>", "url": "https://ejemplo.com"},
                {"id": "propio", "nombre": "El propio Timonel", "url": "http://localhost:3998"}]},
            {"nombre": "Juegos", "pestana": "Ocio", "compacto": True, "items": [
                {"id": "retro", "nombre": "RetroBat", "url": "https://ejemplo.com/retro"}]},
        ]}


class Navegador(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        for p in (4101, 4102, 4103, 4104):
            levantar(p)
        cls.dir = tempfile.mkdtemp(prefix="timonel-prueba-")
        for f in ("timonel.py", "index.html"):
            shutil.copy(os.path.join(RAIZ, f), cls.dir)
        cls.cfg = os.path.join(cls.dir, "config.json")
        with open(os.path.join(cls.dir, "sonarr-config.xml"), "w") as f:
            f.write("<Config>\n  <Port>8989</Port>\n  <ApiKey>ARR-KEY-XML</ApiKey>\n</Config>")
        cls.escribir(config_semilla())
        cls.srv = subprocess.Popen([sys.executable, "timonel.py", "--no-browser"], cwd=cls.dir,
                                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        for _ in range(50):
            try:
                urllib.request.urlopen(B + "/api/config", timeout=1); break
            except Exception:
                time.sleep(0.2)
        cls.pw = sync_playwright().start()
        cls.nav = cls.pw.chromium.launch(executable_path=os.environ.get("CHROME") or None, args=["--no-sandbox"])
        cls.axe = open(os.environ["AXE_JS"], encoding="utf-8").read() if os.environ.get("AXE_JS") else None

    @classmethod
    def tearDownClass(cls):
        cls.nav.close(); cls.pw.stop()
        try:                                             # si una prueba reinició el servidor, cerrar el nuevo
            with urllib.request.urlopen(B + "/api/config", timeout=2) as r:
                pid = json.loads(r.read())["_pid"]
            if pid != cls.srv.pid:
                os.kill(pid, 15)
        except Exception:
            pass
        cls.srv.terminate(); cls.srv.wait(5)
        shutil.rmtree(cls.dir, ignore_errors=True)

    @classmethod
    def escribir(cls, cfg):
        with open(cls.cfg, "w", encoding="utf-8") as f:
            json.dump(cfg, f, ensure_ascii=False, indent=2)

    def leer(self):
        with open(self.cfg, encoding="utf-8") as f:
            return json.load(f)

    def setUp(self):
        self.escribir(config_semilla())
        self.errores = []
        self.ctx = self.nav.new_context(viewport={"width": 1400, "height": 900})
        self.pg = self.ctx.new_page()
        self.pg.on("pageerror", lambda e: self.errores.append("JS: " + str(e)))
        self.pg.on("response", lambda r: self.errores.append(f"{r.status} {r.url}") if r.status >= 500 and r.url.startswith(B) else None)
        self.pg.on("dialog", lambda d: d.accept())

    def tearDown(self):
        self.ctx.close()
        self.assertEqual(self.errores, [], "errores de JS o respuestas 5xx")

    def abrir(self, ruta="/"):
        self.pg.goto(B + ruta)
        self.pg.wait_for_selector(".tile")
        self.pg.wait_for_function("() => document.querySelector('.tile[data-id=vivo]') && document.querySelector('.tile[data-id=vivo]').classList.contains('arriba')", timeout=10000)

    def tile(self, ident):
        return self.pg.locator(f'.tile[data-id="{ident}"]')

    def api(self, ruta, datos=None, cab=None):
        req = urllib.request.Request(B + ruta, data=json.dumps(datos).encode() if datos is not None else None,
                                     headers={"Content-Type": "application/json", **(cab or {})})
        try:
            with urllib.request.urlopen(req, timeout=10) as r:
                return r.status, json.loads(r.read() or b"null")
        except urllib.error.HTTPError as e:
            return e.code, None

    def escanear_axe(self):
        if not self.axe:
            return
        self.pg.add_script_tag(content=self.axe)
        r = self.pg.evaluate("async () => (await axe.run(document, {resultTypes: ['violations']})).violations"
                             ".filter(v => ['serious','critical'].includes(v.impact)).map(v => v.id + ': ' + v.nodes.length + ' nodos')")
        self.assertEqual(r, [], "accesibilidad")

    # ---------- F01 ----------
    def test_F01_H1_abre_en_pestana_nueva(self):
        self.abrir()
        t = self.tile("vivo")
        self.assertEqual(t.get_attribute("target"), "_blank")
        self.assertEqual(t.get_attribute("rel"), "noopener")
        with self.ctx.expect_page() as nueva:
            t.click()
        self.assertTrue(nueva.value.url.startswith("http://127.0.0.1:4101"))
        self.escanear_axe()

    def test_F01_E1_teclado(self):
        self.abrir()
        self.tile("vivo").focus()
        with self.ctx.expect_page() as nueva:
            self.pg.keyboard.press("Enter")
        self.assertIn("4101", nueva.value.url)

    def test_F01_E2_movil(self):
        self.pg.set_viewport_size({"width": 390, "height": 844})
        self.abrir()
        self.assertFalse(self.pg.evaluate("document.documentElement.scrollWidth > innerWidth"), "desborde horizontal")
        self.assertTrue(self.pg.get_by_role("button", name="Buscar", exact=True).is_visible())
        self.escanear_axe()

    def test_F01_E3_nombre_largo_y_xss(self):
        self.abrir()
        caja = self.tile("acentos").bounding_box()
        self.assertLess(caja["height"], 140)
        self.assertIsNone(self.pg.evaluate("window.__xss"))
        self.assertIn("<img", self.tile("xss").inner_text())

    def test_F01_N1_sin_ruta(self):
        self.abrir()
        b = self.tile("caido").get_by_role("button")
        self.assertTrue(b.is_disabled())
        self.assertEqual(b.inner_text().strip().lower(), "sin ruta")

    # ---------- F02 ----------
    def test_F02_H1_E1_estados(self):
        self.abrir()
        self.pg.wait_for_function("() => document.querySelector('.tile[data-id=caido]').classList.contains('caido')")
        self.assertIn("en línea", self.tile("vivo").inner_text())
        self.assertRegex(self.tile("vivo").locator(".ms").inner_text(), r"\d+ ms")
        self.assertIn("apagado", self.tile("caido").inner_text())
        self.assertIn("puerto ocupado", self.tile("otro").inner_text())

    def test_F02_E2_un_fallo_aislado_no_lo_tira(self):
        cfg = config_semilla()
        cfg["grupos"][0]["items"].append({"id": "fragil", "nombre": "Frágil", "url": "http://127.0.0.1:4105", "vigilar": True})
        self.escribir(cfg)
        levantar(4105)
        self.api("/api/estado?ahora=1")
        _, e = self.api("/api/estado?ahora=1")
        self.assertEqual(e["fragil"]["estado"], "arriba")
        FALSOS.pop(4105).shutdown(); time.sleep(0.3)
        _, e = self.api("/api/estado?ahora=1")
        self.assertEqual(e["fragil"]["estado"], "arriba", "primer fallo: todavía arriba (dudoso)")
        self.assertTrue(e["fragil"].get("dudoso"))
        _, e = self.api("/api/estado?ahora=1")
        self.assertEqual(e["fragil"]["estado"], "caido", "segundo fallo: caído")

    def test_F02_E3_conteo_con_subgrupos(self):
        self.abrir()
        self.pg.wait_for_timeout(500)
        cuenta = self.pg.locator("section.grupo").first.locator(":scope > .grupo-cab .cuenta").inner_text()
        self.assertRegex(cuenta, r"^\d+ / 10 en línea$")

    def test_F02_E4_ping_sin_url(self):
        _, e = self.api("/api/estado?ahora=1")
        self.assertIn(e["ping"]["estado"], ("arriba", "caido"))

    # ---------- F03 ----------
    def test_F03_H1_buscar_y_abrir(self):
        self.abrir()
        self.pg.keyboard.press("/")
        self.assertEqual(self.pg.evaluate("document.activeElement.id"), "q")
        self.pg.keyboard.type("mi app")
        self.assertIn("Mi App", self.pg.locator("#pista").inner_text())
        with self.ctx.expect_page() as nueva:
            self.pg.keyboard.press("Enter")
        self.assertIn("4101", nueva.value.url)

    def test_F03_E1_busqueda_web(self):
        self.abrir()
        self.pg.get_by_role("searchbox", name="Buscar").fill("zzz nada")
        with self.ctx.expect_page() as nueva:
            self.pg.keyboard.press("Enter")
        self.assertIn("/buscar?q=zzz%20nada", nueva.value.url)

    def test_F03_E2_direccion_tecleada(self):
        self.abrir()
        q = self.pg.get_by_role("searchbox", name="Buscar")
        q.fill("127.0.0.1:4101/hola")
        self.assertIn("http://127.0.0.1:4101/hola", self.pg.locator("#pista").inner_text())
        with self.ctx.expect_page() as nueva:
            self.pg.keyboard.press("Enter")
        self.assertEqual(nueva.value.url, "http://127.0.0.1:4101/hola")

    def test_F03_E3_acentos(self):
        self.abrir()
        q = self.pg.get_by_role("searchbox", name="Buscar")
        q.fill("nandu")
        self.assertTrue(self.tile("acentos").is_visible(), "'nandu' debe encontrar 'Ñandú'")
        q.fill("camion")
        self.assertTrue(self.tile("acentos").is_visible(), "'camion' debe encontrar 'Camión'")
        q.fill("básico")
        self.assertTrue(self.tile("basico").is_visible())

    def test_F03_E4_escape(self):
        self.abrir()
        q = self.pg.get_by_role("searchbox", name="Buscar")
        q.fill("mi app")
        self.assertFalse(self.tile("caido").is_visible())
        q.press("Escape")
        self.assertEqual(q.input_value(), "")
        self.assertTrue(self.tile("caido").is_visible())

    def test_F03_E5_E6_busca_en_otras_pestanas_y_plegados(self):
        self.abrir()
        self.pg.locator("section.grupo", has_text="Servicios").first.locator(".grupo-cab").first.click()
        self.pg.get_by_role("searchbox", name="Buscar").fill("retro")
        self.assertTrue(self.tile("retro").is_visible(), "busca en la pestaña Ocio estando en Taller")
        self.pg.get_by_role("searchbox", name="Buscar").fill("mi app")
        self.assertTrue(self.tile("vivo").is_visible(), "busca dentro de un grupo plegado")

    # ---------- F04 ----------
    def agregar(self, nombre, doble=False):
        self.pg.get_by_role("button", name="+ Agregar").click()
        self.pg.get_by_label("Nombre", exact=True).fill(nombre)
        self.pg.get_by_label("Dirección").fill("ejemplo.org")
        self.pg.get_by_label("Ícono (opcional)").fill("mdi-robot")
        b = self.pg.get_by_role("button", name="Guardar")
        if doble:
            b.dblclick()
        else:
            b.click()

    def test_F04_H1_agregar(self):
        self.abrir()
        self.agregar("Nueva página")
        self.pg.wait_for_selector('.tile[data-id="nueva-pagina"]')
        it = [i for g in self.leer()["grupos"] for i in g.get("items", []) if i["id"] == "nueva-pagina"][0]
        self.assertEqual(it["url"], "https://ejemplo.org")
        self.assertEqual(it["icono"], "mdi-robot")
        self.assertTrue(os.path.exists(self.cfg + ".bak"))

    def test_F04_E1_nombre_vacio(self):
        self.abrir()
        self.pg.get_by_role("button", name="+ Agregar").click()
        self.pg.get_by_label("Dirección").fill("ejemplo.org")
        self.pg.get_by_role("button", name="Guardar").click()
        self.assertTrue(self.pg.locator("#dlg").evaluate("d => d.open"))

    def test_F04_E2_doble_clic(self):
        self.abrir()
        self.agregar("Doble", doble=True)
        self.pg.wait_for_selector('.tile[data-id="doble"]')
        self.pg.wait_for_timeout(800)
        ids = [i["id"] for g in self.leer()["grupos"] for i in g.get("items", [])]
        self.assertEqual([i for i in ids if i.startswith("doble")], ["doble"], "doble clic agregó dos veces")

    def test_F04_E3_altas_simultaneas(self):
        with concurrent.futures.ThreadPoolExecutor(10) as ex:
            list(ex.map(lambda n: self.api("/api/agregar", {"nombre": "Paralelo", "url": "https://x.org", "grupo": "Carrera"}), range(10)))
        cfg = self.leer()
        ids = [i["id"] for g in cfg["grupos"] if g["nombre"] == "Carrera" for i in g["items"]]
        self.assertEqual(len(ids), 10)
        self.assertEqual(len(set(ids)), 10)

    def test_F04_N1_quitar(self):
        self.abrir()
        self.pg.get_by_role("button", name="Editar").click()
        self.pg.get_by_role("button", name="Quitar Router", exact=True).click()
        self.pg.wait_for_selector('.tile[data-id="ping"]', state="detached")
        ids = [i["id"] for g in self.leer()["grupos"] for i in g.get("items", [])]
        self.assertNotIn("ping", ids)

    def test_F04_N2_error_de_sintaxis_y_recuperacion(self):
        self.abrir()
        with open(self.cfg, encoding="utf-8") as f:
            bueno = f.read()
        lineas = bueno.split("\n")
        lineas[3] = lineas[3] + ","                         # coma de más
        with open(self.cfg, "w", encoding="utf-8") as f:
            f.write("\n".join(lineas))
        self.pg.reload(); self.pg.wait_for_selector(".aviso")
        aviso = self.pg.locator(".aviso").inner_text()
        self.assertRegex(aviso, r"línea \d+, columna \d+")
        self.assertTrue(self.tile("vivo").is_visible(), "sigue con la última versión buena")
        with open(self.cfg, "w", encoding="utf-8") as f:
            f.write(bueno)
        self.pg.wait_for_selector(".aviso", state="detached", timeout=15000)

    def test_F04_N3_id_repetido(self):
        cfg = config_semilla()
        cfg["grupos"][1]["items"].append({"id": "vivo", "nombre": "Duplicado", "url": "https://x.org"})
        self.escribir(cfg)
        self.abrir()
        self.pg.wait_for_selector(".aviso")
        self.assertIn("vivo", self.pg.locator(".aviso").inner_text())
        self.assertRegex(self.pg.locator(".aviso").inner_text(), r"línea \d+")

    # ---------- F05 ----------
    def test_F05_pestanas(self):
        self.abrir()
        tabs = self.pg.get_by_role("navigation", name="Pestañas")
        self.assertTrue(self.tile("vivo").is_visible())
        self.assertFalse(self.tile("retro").is_visible())
        tabs.get_by_role("link", name="Ocio").click()
        self.pg.wait_for_url("**#Ocio")
        self.tile("retro").wait_for(state="visible")
        self.assertFalse(self.tile("vivo").is_visible())
        self.pg.goto(B + "/#NoExiste"); self.pg.reload(); self.pg.wait_for_selector(".tile", state="attached")
        self.assertTrue(self.tile("vivo").is_visible())
        self.escanear_axe()

    def test_F05_E1_hash_directo(self):
        self.pg.goto(B + "/#Ocio"); self.pg.wait_for_selector(".tile", state="attached")
        self.assertTrue(self.tile("retro").is_visible())

    # ---------- F06 ----------
    def test_F06_plegar_y_recordar(self):
        self.ctx.clear_cookies()
        pg = self.pg
        pg.goto(B + "/"); pg.wait_for_selector(".tile")
        boton = pg.locator("section.grupo", has_text="Raros").locator(".plegar").first
        self.assertEqual(boton.get_attribute("aria-expanded"), "true")
        boton.click()
        self.assertEqual(boton.get_attribute("aria-expanded"), "false")
        self.assertFalse(self.tile("xss").is_visible())
        pg.evaluate("location.reload()"); pg.wait_for_selector(".tile")
        self.assertFalse(self.tile("xss").is_visible(), "el plegado se conserva al recargar")

    # ---------- F07 ----------
    def test_F07_apariencia(self):
        self.abrir()
        clases = self.pg.evaluate("document.body.className")
        self.assertIn("h-caja", clases); self.assertIn("t-filete", clases)
        self.pg.wait_for_function("() => document.querySelector('.tile[data-id=basico]').classList.contains('arriba')")
        self.assertFalse(self.tile("punto").locator(".txt-estado").is_visible())
        self.assertEqual(self.tile("basico").locator(".txt-estado").inner_text(), "ARRIBA")
        self.pg.goto(B + "/#Ocio"); self.pg.wait_for_selector(".tile", state="attached")
        self.assertFalse(self.tile("retro").locator(".desc").is_visible(), "compacto: sin descripción")

    # ---------- F08 MCP ----------
    def test_F08_mcp(self):
        token = open(os.path.join(self.dir, "mcp_token.txt"), encoding="utf-8").read().strip()
        cab = {"Authorization": "Bearer " + token}
        c, _ = self.api("/api/mcp", {"jsonrpc": "2.0", "id": 1, "method": "tools/list"})
        self.assertEqual(c, 401)
        c, r = self.api("/api/mcp", {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {"protocolVersion": "2025-06-18"}}, cab)
        self.assertEqual(r["result"]["serverInfo"]["name"], "timonel")
        _, r = self.api("/api/mcp", {"jsonrpc": "2.0", "id": 2, "method": "tools/list"}, cab)
        self.assertEqual(len(r["result"]["tools"]), 5)
        _, r = self.api("/api/mcp", {"jsonrpc": "2.0", "id": 3, "method": "tools/call", "params": {"name": "leer_config"}}, cab)
        self.assertNotIn(SECRETO, r["result"]["content"][0]["text"])
        _, r = self.api("/api/mcp", {"jsonrpc": "2.0", "id": 4, "method": "tools/call", "params": {"name": "agregar_servicio", "arguments": {"nombre": "x", "url": "https://x.org"}}}, cab)
        self.assertTrue(r["result"]["isError"], "escritura apagada")
        cfg = config_semilla(); cfg["mcp"]["activo"] = False; self.escribir(cfg)
        c, _ = self.api("/api/mcp", {"jsonrpc": "2.0", "id": 5, "method": "tools/list"}, cab)
        self.assertEqual(c, 404)


    # ---------- v2.1 ----------
    def test_V21_1_teclear_en_cualquier_parte(self):
        self.abrir()
        self.pg.locator("body").click(position={"x": 5, "y": 5})
        self.pg.keyboard.type("mi app")
        self.assertEqual(self.pg.get_by_role("searchbox", name="Buscar").input_value(), "mi app")
        self.assertIn("Mi App", self.pg.locator("#pista").inner_text())
        self.pg.get_by_role("button", name="+ Agregar").click()
        self.pg.get_by_label("Nombre", exact=True).type("xy")
        self.assertEqual(self.pg.get_by_label("Nombre", exact=True).input_value(), "xy", "en el formulario no se roba el foco")

    def test_V21_2_widget_varias_consultas_clave_desde_xml(self):
        self.abrir()
        w = self.tile("sonarr").locator(".wcampos")
        w.locator(".wcampo").first.wait_for()
        t = w.inner_text()
        self.assertIn("Faltan 12", t); self.assertIn("En cola 3", t); self.assertIn("Avisos 1", t)
        self.assertIn("n-aviso", w.locator(".wcampo", has_text="Avisos").get_attribute("class"))
        _, d = self.api("/api/config")
        self.assertNotIn("ARR-KEY-XML", json.dumps(d))

    def test_V21_3_clave_xml_faltante(self):
        cfg = config_semilla(); cfg["proveedores"]["sonarr"]["claveDesde"] = "no-existe.xml"; self.escribir(cfg)
        _, r = self.api("/api/widget/sonarr")
        self.assertIn("no-existe.xml", r["error"])

    def test_V21_4_version_y_reinicio(self):
        self.abrir()
        self.assertRegex(self.pg.locator("#version").inner_text(), r"Timonel v\d+\.\d+")
        self.assertFalse(self.pg.locator("#btn-reiniciar").is_visible())
        os.utime(os.path.join(self.dir, "timonel.py"))          # simula que timonel.py cambió
        self.pg.reload(); self.pg.wait_for_selector(".tile", state="attached")
        self.pg.wait_for_selector("#btn-reiniciar", state="visible")
        pid_antes = self.__class__.srv.pid
        self.pg.locator("#btn-reiniciar").click()
        self.pg.wait_for_function("() => document.querySelector('#version').textContent.includes('encendido')", timeout=20000)
        self.pg.wait_for_selector("#btn-reiniciar", state="hidden", timeout=20000)
        _, d = self.api("/api/config")
        self.assertNotEqual(d["_pid"], pid_antes, "el servidor se reinició en otro proceso")
        self.assertFalse(d["_reiniciar"])


    # ---------- v2.2 ----------
    def test_V22_1_editar_desde_la_pagina(self):
        self.abrir()
        self.pg.get_by_role("button", name="Editar", exact=True).click()
        self.pg.get_by_role("button", name="Editar Mi App", exact=True).click()
        self.assertEqual(self.pg.get_by_label("Nombre", exact=True).input_value(), "Mi App")
        self.pg.get_by_label("Nombre", exact=True).fill("Mi App renombrada")
        self.pg.get_by_label("Grupo", exact=True).select_option("Raros")
        self.pg.get_by_role("button", name="Guardar").click()
        self.pg.wait_for_function("() => document.querySelector('.tile[data-id=vivo] .nombre').textContent === 'Mi App renombrada'")
        cfg = self.leer()
        raros = next(g for g in cfg["grupos"] if g["nombre"] == "Raros")
        it = next(i for i in raros["items"] if i["id"] == "vivo")
        self.assertEqual((it["nombre"], it["url"], it.get("vigilar")), ("Mi App renombrada", "http://127.0.0.1:4101", True))
        self.assertTrue(self.pg.evaluate("document.body.classList.contains('editando')"), "sigue en modo edición")

    def test_V22_2_arrastrar_para_reordenar_y_mover(self):
        self.pg.set_viewport_size({"width": 1400, "height": 1800})     # Playwright no arrastra con desplazamiento
        self.abrir()
        self.pg.get_by_role("button", name="Editar", exact=True).click()
        self.tile("otro").drag_to(self.tile("vivo"), target_position={"x": 5, "y": 20})
        self.pg.wait_for_timeout(800)
        ids = [i["id"] for i in self.leer()["grupos"][0]["items"]]
        self.assertLess(ids.index("otro"), ids.index("vivo"), "otro quedó antes de vivo")
        self.tile("caido").drag_to(self.tile("acentos"), target_position={"x": 5, "y": 20})
        self.pg.wait_for_timeout(800)
        raros = next(g for g in self.leer()["grupos"] if g["nombre"] == "Raros")
        self.assertEqual([i["id"] for i in raros["items"]][0], "caido", "se movió a otro grupo, al principio")

    def test_V22_3_listas_en_widget_con_fechas(self):
        self.abrir()
        l = self.tile("sonarr").locator(".wlista")
        l.first.wait_for()
        t = l.inner_text()
        self.assertIn("Frieren", t); self.assertIn("Dandadan", t)
        self.assertRegex(t, r"\d\d/11 \d\d:\d\d", "fecha con formato")

    def test_V22_4_widget_ollama_bytes(self):
        self.abrir()
        w = self.tile("ollama")
        w.locator(".wlista").first.wait_for()
        self.assertIn("En memoria 2", w.locator(".wcampos").inner_text())
        self.assertIn("3.2 GB", w.locator(".wlista").inner_text())
        self.assertIn("qwen2.5:7b", w.locator(".wlista").inner_text())

    def test_V22_5_detener_un_servicio(self):
        proc = subprocess.Popen([sys.executable, "-m", "http.server", "4107", "--bind", "127.0.0.1"],
                                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        try:
            time.sleep(0.8)
            self.abrir()
            self.pg.wait_for_function("() => document.querySelector('.tile[data-id=detenible]').classList.contains('arriba')", timeout=15000)
            b = self.tile("detenible").get_by_role("button", name="Detener")
            b.click()
            proc.wait(10)
            self.assertIsNotNone(proc.returncode, "el proceso del puerto 4107 se cerró")
            self.pg.wait_for_function("() => document.querySelector('.tile[data-id=detenible]').classList.contains('caido')", timeout=15000)
            # vuelve a su estado previo: "Sin ruta", porque el programa de prueba no existe
            self.assertEqual(self.tile("detenible").get_by_role("button").first.inner_text().strip().lower(), "sin ruta")
            c, r = self.api("/api/detener", {"id": "propio"})
            self.assertEqual(c, 400, "nunca se detiene al propio Timonel")
        finally:
            if proc.poll() is None:
                proc.kill()

    # ---------- Widgets y barra ----------
    def test_W_widget_api(self):
        self.abrir()
        w = self.tile("api").locator(".wcampos")
        w.locator(".wcampo").first.wait_for()
        texto = w.inner_text()
        self.assertIn("Usuarios 5", texto); self.assertIn("Errores 2", texto); self.assertIn("Cola 0", texto)
        self.assertIn("n-peligro", w.locator(".wcampo", has_text="Errores").get_attribute("class"))

    def test_W_N1_widget_sin_servicio(self):
        cfg = config_semilla()
        cfg["proveedores"]["falso"]["url"] = "http://127.0.0.1:4198"
        self.escribir(cfg)
        self.abrir()
        w = self.tile("api").locator(".wcampos")
        w.locator(".wcampo").first.wait_for()
        self.assertIn("Sin datos", w.inner_text())

    def test_W_H2_barra(self):
        self.abrir()
        self.pg.wait_for_function("() => /Memoria RAM/i.test(document.querySelector('#telemetria').innerText)", timeout=15000)
        self.assertIn("Ana", self.pg.locator("#saludo").inner_text())
        barra = self.pg.locator("#telemetria").inner_text()
        for t in ("MEMORIA RAM", "PROCESADOR", "UNIDADES", "CLIMA"):
            self.assertIn(t, barra.upper())

    # ---------- Seguridad ----------
    def test_SEG_1_sin_secretos(self):
        _, d = self.api("/api/config")
        crudo = json.dumps(d)
        self.assertNotIn(SECRETO, crudo)
        self.assertNotIn("proveedores", d)

    def test_SEG_2_origen_y_host(self):
        c, _ = self.api("/api/lanzar", {"id": "caido"}, {"Origin": "https://malo.com"})
        self.assertEqual(c, 403)
        req = urllib.request.Request(B + "/api/config", headers={"Host": "malo.com"})
        with self.assertRaises(urllib.error.HTTPError) as e:
            urllib.request.urlopen(req, timeout=5)
        self.assertEqual(e.exception.code, 403)

    def test_SEG_3_traversal(self):
        for ruta in ("/iconos/..%2fconfig.json", "/iconos/../config.json", "/local/acentos/..%2f..%2fconfig.json"):
            c, _ = self.api(ruta)
            self.assertEqual(c, 404, ruta)

    # ---------- Idioma y config en inglés ----------
    def test_I18N_1_cambiar_a_ingles(self):
        self.abrir()
        self.assertEqual(self.pg.locator("#btn-agregar").inner_text().strip().upper(), "+ AGREGAR")
        self.pg.click("#cambiar-idioma")
        self.assertEqual(self.pg.locator("#btn-agregar").inner_text().strip().upper(), "+ ADD")
        self.pg.wait_for_function("() => document.querySelector('.tile[data-id=vivo] .txt-estado').textContent === 'online'")
        self.assertEqual(self.pg.evaluate("document.documentElement.lang"), "en")
        msj = self.pg.evaluate("async () => (await (await fetch('/api/agregar', {method: 'POST', headers: {'Content-Type': 'application/json'}, body: '{}'})).json()).mensaje")
        self.assertEqual(msj, "The name is missing.")
        self.pg.reload(); self.pg.wait_for_selector(".tile")
        self.assertEqual(self.pg.locator("#cambiar-idioma").inner_text(), "Español", "la elección se recuerda")

    def test_I18N_2_config_en_ingles_se_queda_en_ingles(self):
        self.escribir({"language": "en", "title": "English test", "port": PUERTO, "interval_s": 5,
                       "bar": [{"type": "clock"}], "groups": [{"name": "Services", "items": [
                           {"id": "vivo", "name": "My App", "description": "up", "url": "http://127.0.0.1:4101", "watch": True}]}]})
        self.abrir()
        self.assertEqual(self.tile("vivo").locator(".txt-estado").inner_text(), "online")
        self.assertIn("SERVICES", self.pg.locator("section.grupo h2").first.inner_text().upper())
        c, d = self.api("/api/agregar", {"nombre": "Nuevo", "url": "https://n.org", "grupo": "Services"})
        self.assertEqual((c, d["mensaje"]), (200, "Added Nuevo to Services."))
        cfg = self.leer()
        self.assertIn("groups", cfg); self.assertNotIn("grupos", cfg)
        nuevo = cfg["groups"][0]["items"][-1]
        self.assertEqual(nuevo["name"], "Nuevo"); self.assertNotIn("nombre", nuevo)
        self.assertEqual(cfg["groups"][0]["items"][0]["watch"], True)

    def test_I18N_3_mcp_en_ingles(self):
        token = open(os.path.join(self.dir, "mcp_token.txt"), encoding="utf-8").read().strip()
        cab = {"Authorization": "Bearer " + token}
        cfg = config_semilla(); cfg["mcp"]["escritura"] = True; self.escribir(cfg)
        _, r = self.api("/api/mcp", {"jsonrpc": "2.0", "id": 1, "method": "tools/list"}, cab)
        self.assertIn("add_shortcut", [x["name"] for x in r["result"]["tools"]])
        _, r = self.api("/api/mcp", {"jsonrpc": "2.0", "id": 2, "method": "tools/call", "params": {
            "name": "add_shortcut", "arguments": {"name": "Desde IA", "url": "https://ia.org", "group": "Raros"}}}, cab)
        self.assertFalse(r["result"]["isError"], r)
        nombres = [i["nombre"] for g in self.leer()["grupos"] for i in g.get("items", [])]
        self.assertIn("Desde IA", nombres)

    def test_TEMA_claro(self):
        cfg = config_semilla(); cfg["tema"]["paleta"] = "claro"; self.escribir(cfg)
        self.abrir()
        self.assertIn("claro", self.pg.evaluate("document.body.className"))
        self.escanear_axe()


class Unidad(unittest.TestCase):
    """Pruebas del servidor sin navegador."""

    def setUp(self):
        import importlib.util
        spec = importlib.util.spec_from_file_location("timonel_prueba", os.path.join(RAIZ, "timonel.py"))
        self.h = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(self.h)
        self.tmp = tempfile.mkdtemp()
        self.path = os.environ.get("PATH", "")

    def tearDown(self):
        os.environ["PATH"] = self.path
        shutil.rmtree(self.tmp, ignore_errors=True)

    def falso_nvidia(self, espera, linea="NVIDIA GeForce RTX 4050 Laptop GPU, 7, 512, 6141, 45"):
        exe = os.path.join(self.tmp, "nvidia-smi")
        with open(exe, "w") as f:
            f.write(f"#!/bin/sh\nsleep {espera}\necho '{linea}'\n")
        os.chmod(exe, 0o755)
        os.environ["PATH"] = self.tmp + os.pathsep + self.path

    def test_GPU_1_tarjeta_dormida_lenta(self):
        """Con Optimus la GPU duerme y nvidia-smi tarda en despertarla: no debe perderse la tarjeta."""
        self.falso_nvidia(4)
        g = None
        for _ in range(30):                       # la lectura puede llegar en segundo plano
            g = self.h.gpu()
            if g:
                break
            time.sleep(0.5)
        self.assertIsNotNone(g, "la GPU lenta debe reportarse")
        self.assertEqual(g["vram_total"], 6141)

    def test_GPU_3_decimales_y_na(self):
        """Visto en la Dell G15: nvidia-smi devolvió '57.06'; otros drivers dan '[N/A]'."""
        self.falso_nvidia(0, "NVIDIA GeForce RTX 4050 Laptop GPU, 57.06, 512.5, 6141, [N/A]")
        g = None
        for _ in range(20):
            g = self.h.gpu()
            if g:
                break
            time.sleep(0.3)
        self.assertIsNotNone(g)
        self.assertEqual((g["uso"], g["vram_usada"], g["temp"]), (57, 512, None))


    def test_AVISO_1_notifica_caida_y_regreso(self):
        self.h.ULTIMA_BUENA["cfg"] = {"idioma": "es"}
        avisos = []
        self.h.notificar = lambda t, x: avisos.append(t)
        cfg = {"grupos": [{"nombre": "g", "items": [{"id": "a", "nombre": "ComfyUI", "url": "http://127.0.0.1:4198", "vigilar": True, "avisar": True},
                                                    {"id": "b", "nombre": "Sin aviso", "url": "http://127.0.0.1:4197", "vigilar": True}]}]}
        for i in ("a", "b"):
            self.h.ESTADO[i] = {"estado": "arriba", "ms": 1}
        self.h.ronda(cfg)                         # primer fallo: dudoso, sin aviso
        self.assertEqual(avisos, [])
        self.h.ronda(cfg)                         # confirmado
        self.assertEqual(avisos, ["ComfyUI se cayó"])
        self.h.SILENCIO["a"] = time.time()        # detenido a propósito: no avisa
        self.h.AVISADOS.clear(); self.h.ESTADO["a"] = {"estado": "arriba", "ms": 1}; self.h.FALLOS["a"] = 1
        self.h.ronda(cfg)
        self.assertEqual(avisos, ["ComfyUI se cayó"])

    def test_GPU_2_no_bloquea_ni_despierta_a_cada_rato(self):
        self.falso_nvidia(0)
        self.h.gpu(); time.sleep(0.5)
        inicio = time.time()
        for _ in range(5):
            self.h.gpu()
        self.assertLess(time.time() - inicio, 0.5, "las lecturas repetidas salen del caché")

    # ---------- Timonel público ----------
    def test_CFG_1_ingles_ida_y_vuelta(self):
        semilla = config_semilla()
        en = self.h.convertir(semilla, False)
        self.assertIn("groups", en); self.assertIn("providers", en)
        self.assertEqual(en["providers"]["sonarr"]["keyFrom"], "sonarr-config.xml")
        api = en["groups"][0]["items"][3]["widget"]
        self.assertIn("Usuarios", api["mapping"], "las etiquetas tuyas no se traducen")
        self.assertEqual(api["highlight"]["Errores"][0]["level"], "danger")
        self.assertEqual(self.h.convertir(en, True), semilla)

    def test_CFG_2_primer_arranque_en_tu_idioma(self):
        for lang, clave in (("en", "groups"), ("es", "grupos")):
            self.h.CONFIG = os.path.join(self.tmp, f"config-{lang}.json")
            self.h.idioma_sistema = lambda l=lang: l
            self.h.crear_config_si_falta()
            with open(self.h.CONFIG, encoding="utf-8") as f:
                crudo = json.load(f)
            self.assertIn(clave, crudo)
            cfg = self.h.cargar_config()
            self.assertTrue(all(it.get("id") and it.get("nombre") for it in self.h.todos_los_items(cfg)))

    @unittest.skipUnless(sys.platform.startswith("linux"), "Linux")
    def test_SO_1_inicio_automatico_linux(self):
        os.environ["XDG_CONFIG_HOME"] = self.tmp
        try:
            self.h.autostart(True)
            ruta = os.path.join(self.tmp, "autostart", "timonel.desktop")
            self.assertIn("timonel.py", open(ruta, encoding="utf-8").read())
            self.h.autostart(False)
            self.assertFalse(os.path.exists(ruta))
        finally:
            del os.environ["XDG_CONFIG_HOME"]

    def test_SO_2_sistema_fuera_de_windows(self):
        self.assertIn("/" if os.name != "nt" else "C:\\", self.h.unidades())
        self.assertIsNotNone(self.h.memoria())
        self.assertTrue(self.h._png(48).startswith(b"\x89PNG"))


if __name__ == "__main__":
    unittest.main(verbosity=2)

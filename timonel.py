"""
Timonel — a dashboard for the apps and services on your own computer.
Timonel — un tablero para las apps y servicios de tu propia computadora.

Python 3.8+ standard library only. Listens on 127.0.0.1 only.
Solo usa la biblioteca estándar de Python 3.8+. Escucha únicamente en 127.0.0.1.

Run / Uso:   python timonel.py          (Windows: Timonel.bat · Linux: ./timonel.sh · macOS: Timonel.command)
Config:      config.json (created on first run · se crea al primer arranque)
Docs:        README.md · README.es.md · config.schema.json · Log: timonel.log
"""
import base64
import collections
import http.cookiejar
import json
import locale
import logging
import mimetypes
import os
import re
import secrets
import shutil
import socket
import string
import subprocess
import sys
import threading
import time
import unicodedata
import urllib.error
import urllib.request
import webbrowser
from concurrent.futures import ThreadPoolExecutor
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from logging.handlers import RotatingFileHandler
from urllib.parse import parse_qs, quote, unquote, urlparse

BASE = os.path.dirname(os.path.abspath(__file__))
CONFIG = os.path.join(BASE, "config.json")
INDEX = os.path.join(BASE, "index.html")
RUTAS = os.path.join(BASE, "rutas_encontradas.json")
ES_WINDOWS = os.name == "nt"
ES_MAC = sys.platform == "darwin"
SIN_VENTANA = 0x08000000 if ES_WINDOWS else 0
CANDADO = threading.Lock()
ICONOS = os.path.join(BASE, "iconos")
TOKEN_MCP = os.path.join(BASE, "mcp_token.txt")
VERSION = "1.0.0"
INICIO = time.time()
SRV = {"s": None}
# Campos que jamás se mandan al navegador
SECRETOS = {"clave", "usuario", "key", "password", "token", "cabeceras", "headers"}
ULTIMA_BUENA = {"cfg": None}
ESTADO = {}
HIST = collections.defaultdict(lambda: collections.deque(maxlen=60))
FALLOS = collections.defaultdict(int)
VISTO = {"t": 0.0}
CACHE = {}
DESPERTAR = threading.Event()

log = logging.getLogger("timonel")
try:
    _h = RotatingFileHandler(os.path.join(BASE, "timonel.log"), maxBytes=1_000_000, backupCount=2, encoding="utf-8")
    _h.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s"))
    log.addHandler(_h)
    log.setLevel(logging.INFO)
except Exception:
    pass


# ---------- Idioma / Language ----------
# Español e inglés. El navegador manda X-Idioma; los avisos en segundo plano usan config.json o el idioma del sistema.

IDIOMA = threading.local()


def idioma_sistema():
    for v in ("LC_ALL", "LC_MESSAGES", "LANG", "LANGUAGE"):
        if os.environ.get(v):
            return "es" if os.environ[v].lower().startswith("es") else "en"
    try:
        if ES_WINDOWS:
            import ctypes
            return "es" if ctypes.windll.kernel32.GetUserDefaultUILanguage() & 0x3FF == 0x0A else "en"
        if ES_MAC:
            r = subprocess.run(["defaults", "read", "-g", "AppleLocale"], capture_output=True, text=True, timeout=3)
            return "es" if r.stdout.lower().startswith("es") else "en"
        return "es" if (locale.getlocale()[0] or "").lower().startswith("es") else "en"
    except Exception:
        return "en"


def idioma():
    v = getattr(IDIOMA, "v", None)
    if v in ("es", "en"):
        return v
    c = (ULTIMA_BUENA["cfg"] or {}).get("idioma")
    return c if c in ("es", "en") else idioma_sistema()


def T(es, en):
    return es if idioma() == "es" else en


# ---------- Claves de config.json en español o en inglés ----------
# Por dentro todo usa las claves en español; si tu config.json está en inglés, se lee y se guarda en inglés.

CLAVES_EN = {
    "titulo": "title", "grupos": "groups", "grupo": "group", "puerto": "port", "idioma": "language",
    "buscador": "searchEngine", "intervalo_s": "interval_s", "barra": "bar", "tema": "theme", "pestana": "tab",
    "estadoEstilo": "statusStyle", "destino": "target", "proveedores": "providers", "avisos": "alerts",
    "discos": "disks", "saludo": "greeting", "anchoTotal": "fullWidth", "gruposPlegados": "groupsCollapsed",
    "sinPlegar": "noCollapse", "nombre": "name", "estilo": "style", "columnas": "columns", "compacto": "compact",
    "colapsado": "collapsed", "icono": "icon", "nota": "note", "desc": "description", "lanzar": "launch",
    "archivo": "file", "vigilar": "watch", "avisar": "notify", "revisar": "check", "contiene": "contains",
    "buscar": "find", "servicio": "service", "detener": "stop", "abrir_pagina": "openPage", "liberar": "freeMemory",
    "tipo": "type", "proveedor": "provider", "consultas": "queries", "mapeo": "mapping", "lista": "list",
    "campos": "fields", "formatos": "formats", "resaltar": "highlight", "cabeceras": "headers",
    "ocultarErrores": "hideErrors", "alto": "height", "de": "from", "texto": "text", "detalle": "detail",
    "etiqueta": "label", "formato": "format", "formatoTexto": "textFormat", "cuando": "when", "valor": "value",
    "nivel": "level", "negar": "negate", "lugar": "place", "unidades": "units", "procesos": "processes",
    "claveDesde": "keyFrom", "cabeceraClave": "keyHeader", "usuario": "user", "clave": "password",
    "activo": "active", "escritura": "write", "encabezado": "header", "tarjeta": "card", "fondo": "background",
    "imagen": "image", "brillo": "brightness", "saturacion": "saturation", "opacidad": "opacity",
    "paleta": "palette", "buscarDescripciones": "searchDescriptions", "abrirUrls": "openUrls",
}
CLAVES_ES = {v: k for k, v in CLAVES_EN.items()}
_FORMATOS = {"fecha": "date"}
VALORES_EN = {
    "tipo": {"clima": "weather", "sistema": "system", "reloj": "clock", "saludo": "greeting"},
    "estilo": {"columna": "column"}, "estadoEstilo": {"detalle": "detail", "punto": "dot", "basico": "basic"},
    "nivel": {"bien": "good", "aviso": "warning", "peligro": "danger"}, "cuando": {"incluye": "includes"},
    "formato": _FORMATOS, "formatoTexto": _FORMATOS, "avisos": {"todos": "all"},
    "encabezado": {"caja": "box", "limpio": "clean"}, "tarjeta": {"filete": "outline"},
    "paleta": {"noche": "night", "claro": "light"}, "unidades": {"metrico": "metric"},
}
VALORES_ES = {k: {b: a for a, b in m.items()} for k, m in VALORES_EN.items()}
FORMATO = {"en": False}


def _valor(clave_es, v, a_es):
    m = (VALORES_ES if a_es else VALORES_EN).get(clave_es)
    return m.get(v, v) if m and isinstance(v, str) else v


def convertir(o, a_es, padre=None):
    """a_es=True: claves en inglés -> español. a_es=False: español -> inglés. Las etiquetas tuyas no se tocan."""
    if isinstance(o, list):
        return [convertir(x, a_es, padre) for x in o]
    if not isinstance(o, dict):
        return o
    out = {}
    for k, v in o.items():
        if padre in ("mapeo", "cabeceras"):              # nombres que tú inventaste
            out[k] = v
        elif padre == "formatos":
            out[k] = _valor("formato", v, a_es)
        elif padre in ("resaltar", "proveedores"):
            out[k] = convertir(v, a_es)
        else:
            ks = CLAVES_ES.get(k, k) if a_es else k
            out[ks if a_es else CLAVES_EN.get(k, k)] = _valor(ks, convertir(v, a_es, ks), a_es)
    return out


def en_ingles(cfg):
    return isinstance(cfg, dict) and any(k in cfg for k in ("groups", "title", "bar", "language"))


def config_inicial(lang):
    """config.json de ejemplo para el primer arranque, en el idioma de tu sistema."""
    es = lang == "es"
    g = lambda a, b: a if es else b
    grupos = [
        {"nombre": g("Favoritos", "Favorites"), "items": [
            {"id": "timonel", "nombre": "Timonel", "desc": g("Ayuda y novedades", "Help and updates"),
             "url": "https://github.com/VEGA2099/timonel", "icono": "mdi-ship-wheel"},
            {"id": "duckduckgo", "nombre": "DuckDuckGo", "url": "https://duckduckgo.com"},
            {"id": "youtube", "nombre": "YouTube", "url": "https://www.youtube.com"}]},
        {"nombre": g("Servicios locales", "Local services"),
         "nota": g("ejemplos: cámbialos o bórralos", "examples: change or delete them"), "items": [
            {"id": "ollama", "nombre": "Ollama", "desc": g("Modelos de IA locales", "Local AI models"),
             "url": "http://127.0.0.1:11434", "vigilar": True, "contiene": "ollama", "icono": "mdi-robot-outline"},
            {"id": "comfyui", "nombre": "ComfyUI", "desc": g("Imágenes con IA", "AI images"),
             "url": "http://127.0.0.1:8188", "vigilar": True, "icono": "mdi-image-filter-hdr"},
            {"id": "jellyfin", "nombre": "Jellyfin", "desc": g("Tu cine en casa", "Your home theater"),
             "url": "http://127.0.0.1:8096", "vigilar": True, "icono": "mdi-movie-open-outline"}]},
    ]
    if ES_WINDOWS:
        grupos.append({"nombre": g("Programas", "Programs"), "items": [
            {"id": "notepad", "nombre": g("Bloc de notas", "Notepad"), "lanzar": r"%WINDIR%\system32\notepad.exe", "icono": "mdi-note-text-outline"},
            {"id": "calc", "nombre": g("Calculadora", "Calculator"), "lanzar": r"%WINDIR%\system32\calc.exe", "icono": "mdi-calculator"}]})
    elif ES_MAC:
        grupos.append({"nombre": g("Programas", "Programs"), "items": [
            {"id": "calc", "nombre": g("Calculadora", "Calculator"), "lanzar": "/System/Applications/Calculator.app", "icono": "mdi-calculator"}]})
    cfg = {"version": 2, "idioma": "auto", "titulo": g("Mi computadora", "My computer"), "puerto": 3000,
           "buscador": "https://duckduckgo.com/?q=", "intervalo_s": 15,
           "barra": [{"tipo": "saludo"}, {"tipo": "reloj"}, {"tipo": "sistema"}], "grupos": grupos}
    return cfg if es else convertir(cfg, False)


# ---------- Config ----------

def crear_config_si_falta():
    if not os.path.exists(CONFIG):
        with open(CONFIG, "w", encoding="utf-8") as f:
            json.dump(config_inicial(idioma_sistema()), f, ensure_ascii=False, indent=2)
        log.info("config.json creado con el ejemplo inicial")


def cargar_config():
    with open(CONFIG, "r", encoding="utf-8") as f:
        crudo = json.load(f)
    FORMATO["en"] = en_ingles(crudo)
    cfg = convertir(crudo, True) if FORMATO["en"] else crudo
    ULTIMA_BUENA["cfg"] = cfg
    return cfg


def cargar_config_tolerante():
    """Si config.json tiene un error, sigue usando la última versión buena y devuelve dónde está el error."""
    try:
        return cargar_config(), None
    except json.JSONDecodeError as e:
        err = {"linea": e.lineno, "columna": e.colno, "mensaje": e.msg}
    except OSError as e:
        err = {"linea": 0, "columna": 0, "mensaje": str(e)}
    return (ULTIMA_BUENA["cfg"] or {"grupos": []}), err


def guardar_config(cfg):
    if os.path.exists(CONFIG):
        shutil.copy2(CONFIG, CONFIG + ".bak")   # respaldo antes de cada cambio hecho desde la página
    tmp = CONFIG + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(convertir(cfg, False) if FORMATO["en"] else cfg, f, ensure_ascii=False, indent=2)
    os.replace(tmp, CONFIG)


def todos_los_grupos(grupos):
    for g in grupos or []:
        yield g
        yield from todos_los_grupos(g.get("grupos"))


def todos_los_items(cfg):
    for g in todos_los_grupos(cfg.get("grupos")):
        for it in g.get("items") or []:
            yield it


def sin_secretos(o):
    if isinstance(o, dict):
        return {k: sin_secretos(v) for k, v in o.items() if k not in SECRETOS and k != "proveedores"}
    if isinstance(o, list):
        return [sin_secretos(x) for x in o]
    return o


def validar_config():
    """Revisa config.json: sintaxis, ids repetidos y valores que no existen. Todo con línea y columna."""
    try:
        with open(CONFIG, "r", encoding="utf-8") as f:
            texto = f.read()
    except OSError as e:
        return {"ok": False, "errores": [{"linea": 0, "columna": 0, "mensaje": str(e)}]}
    try:
        cfg = json.loads(texto)
    except json.JSONDecodeError as e:
        return {"ok": False, "errores": [{"linea": e.lineno, "columna": e.colno, "mensaje": e.msg}]}
    ingles = en_ingles(cfg)
    if ingles:
        cfg = convertir(cfg, True)

    def donde(fragmento, n=1):
        pos = -1
        for _ in range(n):
            pos = texto.find(fragmento, pos + 1)
            if pos < 0:
                return 0, 0
        return texto.count("\n", 0, pos) + 1, pos - texto.rfind("\n", 0, pos)

    errores, vistos = [], collections.Counter()
    for g in todos_los_grupos(cfg.get("grupos")):
        if not g.get("nombre"):
            errores.append({"linea": 0, "columna": 0, "mensaje": T("hay un grupo sin nombre", "a group has no name")})
    for it in todos_los_items(cfg):
        ident = it.get("id")
        if not ident:
            errores.append({"linea": 0, "columna": 0, "mensaje": T(f"«{it.get('nombre', '?')}» no tiene id", f"“{it.get('nombre', '?')}” has no id")})
            continue
        vistos[ident] += 1
        if vistos[ident] == 2:
            l, c = donde(f'"id": "{ident}"', 2)
            errores.append({"linea": l, "columna": c, "mensaje": T(f"el id «{ident}» está repetido", f"the id “{ident}” is used twice")})
        if not it.get("nombre"):
            l, c = donde(f'"id": "{ident}"')
            errores.append({"linea": l, "columna": c, "mensaje": T(f"«{ident}» no tiene nombre", f"“{ident}” has no name")})
    validos = {"estadoEstilo": {"detalle", "punto", "basico"}, "destino": {"_blank", "_self", "_top"}}
    for campo, ok in validos.items():
        for obj in [cfg] + list(todos_los_items(cfg)):
            v = obj.get(campo)
            if v is not None and v not in ok:
                l, c = donde(f'"{CLAVES_EN[campo]}": "{_valor(campo, v, False)}"' if ingles else f'"{campo}": "{v}"')
                errores.append({"linea": l, "columna": c,
                                "mensaje": T(f"{campo} = «{v}» no existe; usa {', '.join(sorted(ok))}",
                                             f"{CLAVES_EN.get(campo, campo)} = “{_valor(campo, v, False)}” doesn't exist; use {', '.join(sorted(_valor(campo, x, False) for x in ok))}")})
    return {"ok": not errores, "errores": errores}


def buscar_item(cfg, ident):
    return next((it for it in todos_los_items(cfg) if it.get("id") == ident), None)


def correr(args, timeout=5):
    try:
        return subprocess.run(args, capture_output=True, text=True, timeout=timeout,
                              creationflags=SIN_VENTANA, errors="replace")
    except Exception:
        return None


# ---------- Búsqueda automática de programas en todos los discos ----------

OMITIR = {"windows", "$recycle.bin", "system volume information", "node_modules", ".git", "venv",
          "site-packages", "windowsapps", "__pycache__", "winsxs", "recovery", "$windows.~bt",
          "roms", "saves", "downloads", "steamapps"}
ENCONTRADAS = {}
BUSCANDO = {"activo": False}


def cargar_rutas():
    try:
        with open(RUTAS, "r", encoding="utf-8") as f:
            return {k: v for k, v in json.load(f).items() if os.path.exists(v)}
    except Exception:
        return {}


def unidades():
    if ES_WINDOWS:
        import ctypes
        m = ctypes.windll.kernel32.GetLogicalDrives()
        return [f"{l}:\\" for i, l in enumerate(string.ascii_uppercase) if m >> i & 1]
    if ES_MAC:
        vols = []
        try:
            vols = [os.path.join("/Volumes", v) for v in sorted(os.listdir("/Volumes"))
                    if os.path.ismount(os.path.join("/Volumes", v)) and os.path.realpath(os.path.join("/Volumes", v)) != "/"]
        except OSError:
            pass
        return ["/"] + vols
    # Linux: la raíz y los discos montados de verdad (no los sistemas virtuales)
    reales = {"ext2", "ext3", "ext4", "btrfs", "xfs", "zfs", "f2fs", "ntfs", "ntfs3", "fuseblk", "vfat", "exfat", "hfsplus"}
    salida = []
    try:
        with open("/proc/mounts") as f:
            for linea in f:
                c = linea.split()
                punto = c[1].replace("\\040", " ")
                if len(c) > 2 and c[2] in reales and punto not in salida and (
                        punto in ("/", "/home") or punto.startswith(("/mnt/", "/media/", "/run/media/"))):
                    salida.append(punto)
    except OSError:
        pass
    return salida or ["/"]


def raices_busqueda():
    casa = os.path.expanduser("~")
    if ES_MAC:
        return [("/Applications", 2), (os.path.join(casa, "Applications"), 2), (casa, 4)]
    if not ES_WINDOWS:
        return [(casa, 4), ("/opt", 3), ("/usr/local/bin", 0), ("/usr/bin", 0)]
    raices = []
    for v in ("ProgramFiles", "ProgramFiles(x86)", "ProgramData", "LOCALAPPDATA", "APPDATA"):
        p = os.environ.get(v)
        if p:
            raices.append((p, 4))
    raices.append(("C:\\", 2))
    for d in unidades():
        if not d.upper().startswith("C"):
            raices.append((d, 4))
    return raices


def explorar(raiz, prof, faltan, hallados):
    if prof < 0 or not faltan - set(hallados):
        return
    try:
        with os.scandir(raiz) as it:
            subdirs = []
            for e in it:
                n = e.name.lower()
                if e.is_file(follow_symlinks=False) and n in faltan and n not in hallados:
                    hallados[n] = e.path
                elif e.is_dir(follow_symlinks=False) and n not in OMITIR and not n.startswith("."):
                    subdirs.append(e.path)
    except Exception:
        return
    for s in subdirs:
        explorar(s, prof - 1, faltan, hallados)


def nombres_buscados(it):
    b = it.get("buscar") or []
    return [x.lower() for x in (b if isinstance(b, list) else [b])]


def buscar_programas():
    if BUSCANDO["activo"]:
        return
    BUSCANDO["activo"] = True
    try:
        cfg = cargar_config()
        faltan = set()
        for it in todos_los_items(cfg):
            if not ruta_directa(it):
                faltan.update(n for n in nombres_buscados(it) if n not in ENCONTRADAS)
        if not faltan:
            return
        hallados = {}
        for raiz, prof in raices_busqueda():
            explorar(raiz, prof, faltan, hallados)
            if not faltan - set(hallados):
                break
        ENCONTRADAS.update(hallados)
        with open(RUTAS, "w", encoding="utf-8") as f:
            json.dump(ENCONTRADAS, f, ensure_ascii=False, indent=2)
    except Exception:
        pass
    finally:
        BUSCANDO["activo"] = False


def ruta_directa(it):
    r = os.path.expandvars(it.get("lanzar", "") or "")
    return r if r and os.path.exists(r) else None


def resolver_ruta(it):
    r = ruta_directa(it)
    if r:
        return r
    for n in nombres_buscados(it):
        if n in ENCONTRADAS and os.path.exists(ENCONTRADAS[n]):
            return ENCONTRADAS[n]
    return None


# ---------- Estado de servicios ----------

def revisar(item):
    url = item.get("revisar") or item.get("url")
    huella = (item.get("contiene") or "").lower()
    inicio = time.perf_counter()
    try:
        r = urllib.request.urlopen(urllib.request.Request(url, headers={"User-Agent": "Timonel"}), timeout=2)
        ms = round((time.perf_counter() - inicio) * 1000)
        # Huella: confirma que en ese puerto responde la app correcta y no otra
        if huella and huella not in r.read(200000).decode("utf-8", "ignore").lower():
            return "otro", ms
        return "arriba", ms
    except urllib.error.HTTPError:
        return "arriba", round((time.perf_counter() - inicio) * 1000)
    except Exception:
        pass
    p = urlparse(url)
    try:
        with socket.create_connection((p.hostname, p.port or (443 if p.scheme == "https" else 80)), timeout=1.5):
            return "arriba", round((time.perf_counter() - inicio) * 1000)
    except Exception:
        return "caido", None


QB = {"opener": None}


def qbittorrent(item):
    """Velocidades y torrents activos vía la API web de qBittorrent."""
    base = urlparse(item["url"])
    base = f"{base.scheme}://{base.netloc}"
    conf = item.get("qbittorrent", {})
    if QB["opener"] is None:
        QB["opener"] = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(http.cookiejar.CookieJar()))
    op = QB["opener"]
    cab = {"Referer": base, "Origin": base}

    def pedir(ruta):
        return json.loads(op.open(urllib.request.Request(base + ruta, headers=cab), timeout=2).read())

    try:
        try:
            info = pedir("/api/v2/transfer/info")
        except urllib.error.HTTPError as e:
            if e.code != 403 or not conf.get("usuario"):
                return {"error": T("La interfaz web pide contraseña: ponla en config.json o activa 'Omitir autenticación para localhost'.",
                                       "The web UI asks for a password: put it in config.json or enable 'Bypass authentication for clients on localhost'.")}
            datos = f"username={conf['usuario']}&password={conf.get('clave', '')}".encode()
            op.open(urllib.request.Request(base + "/api/v2/auth/login", data=datos, headers=cab), timeout=2)
            info = pedir("/api/v2/transfer/info")
        activos = pedir("/api/v2/torrents/info?filter=active")
        return {"bajada": info.get("dl_info_speed", 0), "subida": info.get("up_info_speed", 0),
                "activos": len(activos)}
    except Exception:
        return {"error": T("Sin datos: activa la interfaz web en qBittorrent (Opciones › Interfaz web).", "No data: turn on the Web UI in qBittorrent (Options › Web UI).")}


def ping_host(host):
    """Ping de verdad si Windows lo permite; si no, prueba los puertos 80 y 443."""
    inicio = time.perf_counter()
    exe = shutil.which("ping")
    if exe:
        args = [exe, "-n", "1", "-w", "1000", host] if ES_WINDOWS else [exe, "-c", "1", "-W", "1", host]
        r = correr(args, 3)
        # En Windows el código de salida miente con "host inaccesible": se busca TTL= (igual en todos los idiomas)
        if r is not None and r.returncode == 0 and (not ES_WINDOWS or "TTL=" in r.stdout.upper()):
            m = re.search(r"[=<]\s*(\d+(?:[.,]\d+)?)\s*ms", r.stdout)
            ms = round(float(m.group(1).replace(",", "."))) if m else round((time.perf_counter() - inicio) * 1000)
            return "arriba", ms
    for puerto in (80, 443):
        try:
            with socket.create_connection((host, puerto), timeout=1):
                return "arriba", round((time.perf_counter() - inicio) * 1000)
        except Exception:
            pass
    return "caido", None


def es_qb(it):
    w = it.get("widget")
    return w == "qbittorrent" or (isinstance(w, dict) and w.get("tipo") == "qbittorrent")


def objetivos(cfg):
    return [it for it in todos_los_items(cfg) if it.get("vigilar") and (it.get("url") or it.get("ping"))]


def medir(it):
    try:
        e, ms = revisar(it) if it.get("url") else ping_host(it["ping"])
        r = {"estado": e, "ms": ms}
        if it.get("url") and it.get("ping"):
            r["ping"] = ping_host(it["ping"])[0]
        if e == "arriba" and es_qb(it):
            r["qb"] = qbittorrent(it)
        return r
    except Exception:
        log.exception("monitor %s", it.get("id"))
        return {"estado": "caido", "ms": None}


SILENCIO = {}          # id -> hora en que se detuvo a propósito (no avisar)
AVISADOS = set()       # ids de los que ya se avisó que se cayeron


def notificar(titulo, texto):
    """Notificación del sistema sin instalar nada: Windows (PowerShell), macOS (osascript), Linux (notify-send)."""
    log.info("Aviso: %s · %s", titulo, texto)
    try:
        if ES_MAC:
            subprocess.Popen(["osascript", "-e", "on run argv", "-e",
                              "display notification (item 2 of argv) with title (item 1 of argv)", "-e", "end run",
                              titulo, texto], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            return
        if not ES_WINDOWS:
            if shutil.which("notify-send"):
                subprocess.Popen(["notify-send", "-a", "Timonel", titulo, texto],
                                 stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            return
    except OSError:
        log.exception("notificación")
        return
    t, x = titulo.replace("'", "''"), texto.replace("'", "''")
    ps = ("[Windows.UI.Notifications.ToastNotificationManager, Windows.UI.Notifications, ContentType = WindowsRuntime] > $null;"
          "$t = [Windows.UI.Notifications.ToastNotificationManager]::GetTemplateContent([Windows.UI.Notifications.ToastTemplateType]::ToastText02);"
          "$e = $t.GetElementsByTagName('text');"
          f"$e.Item(0).AppendChild($t.CreateTextNode('{t}')) > $null; $e.Item(1).AppendChild($t.CreateTextNode('{x}')) > $null;"
          "[Windows.UI.Notifications.ToastNotificationManager]::CreateToastNotifier("
          "'{1AC14E77-02E7-4E5D-B744-2EB1AE5198B7}\\WindowsPowerShell\\v1.0\\powershell.exe').Show("
          "[Windows.UI.Notifications.ToastNotification]::new($t))")
    cod = base64.b64encode(ps.encode("utf-16-le")).decode()
    try:
        subprocess.Popen(["powershell", "-NoProfile", "-WindowStyle", "Hidden", "-EncodedCommand", cod],
                         creationflags=SIN_VENTANA, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    except OSError:
        log.exception("notificación")


def debe_avisar(it, cfg):
    if time.time() - SILENCIO.get(it["id"], 0) < 300:
        return False
    return bool(it.get("avisar")) or (cfg.get("avisos") == "todos" and it.get("avisar") is not False)


def ronda(cfg, solo=None):
    lista = [it for it in objetivos(cfg) if solo is None or it["id"] == solo]
    with ThreadPoolExecutor(max_workers=24) as ex:
        resultados = list(ex.map(medir, lista))
    ahora = time.time()
    for it, r in zip(lista, resultados):
        i = it["id"]
        previo = ESTADO.get(i)
        if solo is None and r["estado"] != "arriba" and previo and previo["estado"] == "arriba" and FALLOS[i] == 0:
            FALLOS[i] = 1                      # un fallo aislado no lo marca caído: se confirma en 5 s
            r = dict(previo, dudoso=True)
        else:
            FALLOS[i] = 0
            if r.get("ms") is not None:
                HIST[i].append(r["ms"])
            if previo and previo["estado"] == "arriba" and r["estado"] != "arriba" and debe_avisar(it, cfg):
                AVISADOS.add(i)
                notificar(T(f"{it['nombre']} se cayó", f"{it['nombre']} is down"),
                          T("Ya no responde. Ábrelo desde Timonel para reiniciarlo.", "It stopped responding. Start it again from Timonel."))
            elif r["estado"] == "arriba" and i in AVISADOS:
                AVISADOS.discard(i)
                notificar(T(f"{it['nombre']} volvió", f"{it['nombre']} is back"), T("Ya responde otra vez.", "It's responding again."))
        r["revisado_en"] = ahora
        r["hist"] = list(HIST[i])
        ESTADO[i] = r
    if solo is None:
        vivos = {it["id"] for it in lista}
        for k in [k for k in ESTADO if k not in vivos]:
            ESTADO.pop(k, None)


def estados(cfg):
    ronda(cfg)
    return ESTADO


def monitor():
    """Revisa los servicios en segundo plano; se pausa si nadie ha abierto la página en 2 minutos."""
    while True:
        espera = 15
        try:
            cfg = cargar_config_tolerante()[0]
            espera = max(5, int(cfg.get("intervalo_s", 15)))
            if not ESTADO or time.time() - VISTO["t"] < 120:
                ronda(cfg)
                if any(v.get("dudoso") for v in ESTADO.values()):
                    espera = 5
        except Exception:
            log.exception("monitor")
        DESPERTAR.wait(espera)
        DESPERTAR.clear()


# ---------- Widgets de servicio, clima y API propia ----------

def obtener_ruta(datos, ruta):
    for parte in str(ruta).split("."):
        if isinstance(datos, (list, dict, str)) and parte in ("length", "#"):
            datos = len(datos)               # "errores.length" o "items.#": cuántos hay
        elif isinstance(datos, list):
            try:
                datos = datos[int(parte)]
            except (ValueError, IndexError):
                return None
        elif isinstance(datos, dict):
            datos = datos.get(parte)
        else:
            return None
    return datos


def nivel_de(valor, reglas):
    for r in reglas or []:
        c, v = r.get("cuando"), r.get("valor")
        try:
            if c in ("gt", "gte", "lt", "lte", "eq", "ne", "between", "outside"):
                x = float(valor)
                ok = {"gt": lambda: x > float(v), "gte": lambda: x >= float(v), "lt": lambda: x < float(v),
                      "lte": lambda: x <= float(v), "eq": lambda: x == float(v), "ne": lambda: x != float(v),
                      "between": lambda: float(v[0]) <= x <= float(v[1]),
                      "outside": lambda: not float(v[0]) <= x <= float(v[1])}[c]()
            elif c == "incluye":
                ok = str(v).lower() in str(valor).lower()
            elif c == "regex":
                ok = re.search(str(v), str(valor)) is not None
            else:
                continue
        except Exception:
            continue
        if r.get("negar"):
            ok = not ok
        if ok:
            return r.get("nivel")
    return None


CLAVES_XML = {}


def clave_desde(ruta):
    """Lee <ApiKey> de un config.xml (Sonarr, Radarr, Prowlarr, Lidarr…). Se vuelve a leer si el archivo cambia."""
    ruta = os.path.expandvars(ruta)
    if not os.path.isabs(ruta):
        ruta = os.path.join(BASE, ruta)
    try:
        mt = os.path.getmtime(ruta)
    except OSError:
        raise ValueError(f"no encontré la clave en {ruta}")
    if CLAVES_XML.get(ruta, (None,))[0] != mt:
        with open(ruta, "r", encoding="utf-8", errors="replace") as f:
            m = re.search(r"<ApiKey>\s*([^<\s]+)\s*</ApiKey>", f.read())
        if not m:
            raise ValueError(f"{ruta} no tiene <ApiKey>")
        CLAVES_XML[ruta] = (mt, m.group(1))
    return CLAVES_XML[ruta][1]


def pedir_json(url, prov=None, cabeceras=None, timeout=3):
    cab = {"User-Agent": "Timonel", "Accept": "application/json"}
    if prov and prov.get("claveDesde"):
        cab[prov.get("cabeceraClave") or "X-Api-Key"] = clave_desde(prov["claveDesde"])
    if prov:
        if prov.get("usuario"):
            par = f"{prov['usuario']}:{prov.get('clave', '')}".encode()
            cab["Authorization"] = "Basic " + base64.b64encode(par).decode()
        cab.update(prov.get("cabeceras") or {})
    cab.update(cabeceras or {})
    with urllib.request.urlopen(urllib.request.Request(url, headers=cab), timeout=timeout) as r:
        return json.loads(r.read())


def formatear(v, formato):
    if v is None or not formato:
        return v
    try:
        if formato == "bytes":
            b = float(v)
            for u in ("B", "KB", "MB", "GB", "TB"):
                if b < 1024 or u == "TB":
                    return f"{b:.1f} {u}" if u not in ("B", "KB") else f"{b:.0f} {u}"
                b /= 1024
        if formato == "fecha":
            import datetime as _dt
            t = _dt.datetime.fromisoformat(str(v).replace("Z", "+00:00"))
            if t.tzinfo:
                t = t.astimezone()
            return t.strftime("%d/%m %H:%M")
    except (ValueError, TypeError):
        return v
    return v


def con_fechas(url):
    """{hoy}/{today}, {ayer}/{yesterday}, {en7dias}/{in7days}, {hace7dias}/{7daysago} en la URL (calendarios de Sonarr/Radarr)."""
    import datetime as _dt
    hoy = _dt.date.today()
    for k, dias in (("hoy", 0), ("ayer", -1), ("en7dias", 7), ("hace7dias", -7),
                    ("today", 0), ("yesterday", -1), ("in7days", 7), ("7daysago", -7)):
        url = url.replace("{" + k + "}", (hoy + _dt.timedelta(days=dias)).isoformat())
    return url


def widget_api(cfg, w, clave, base=None):
    intervalo = max(5, int(w.get("intervalo_s", 30)))
    prov_cfg = (cfg.get("proveedores") or {}).get(w.get("proveedor"))
    clave = clave + ":" + json.dumps([w, prov_cfg], sort_keys=True, ensure_ascii=False)
    c = CACHE.get(clave)
    if c and time.time() - c[0] < intervalo:
        return c[1]
    prov = (cfg.get("proveedores") or {}).get(w.get("proveedor")) if w.get("proveedor") else None
    # "consultas": varias URLs en un solo widget (p. ej. Sonarr: faltantes + cola + avisos)
    consultas = w.get("consultas") or [{"url": w.get("url"), "mapeo": w.get("mapeo"), "lista": w.get("lista")}]
    campos, salida, errores, listas = w.get("campos"), [], [], []
    for c in consultas:
        url = con_fechas(c.get("url") or "")
        raiz = (prov or {}).get("url") or base            # sin proveedor, la URL relativa cuelga del propio acceso
        if raiz and not url.startswith("http"):
            url = raiz.rstrip("/") + "/" + url.lstrip("/")
        try:
            datos = pedir_json(url, prov, {**(w.get("cabeceras") or {}), **(c.get("cabeceras") or {})})
        except Exception as e:
            errores.append(str(e))
            continue
        for l in ([c["lista"]] if isinstance(c.get("lista"), dict) else (c.get("lista") or [])):
            arr = obtener_ruta(datos, l["de"]) if l.get("de") else datos
            if isinstance(arr, list):
                elementos = [{"texto": formatear(obtener_ruta(x, l["texto"]) if l.get("texto") else x, l.get("formatoTexto")),
                              "detalle": formatear(obtener_ruta(x, l["detalle"]) if l.get("detalle") else None, l.get("formato"))}
                             for x in arr[:max(1, int(l.get("max", 5)))]]
                listas.append({"etiqueta": l.get("etiqueta", ""), "elementos": elementos, "total": len(arr)})
        mapeo = c.get("mapeo") or {}
        if not mapeo and not c.get("lista") and isinstance(datos, dict):   # sin mapeo: los primeros 4 valores simples
            mapeo = {k: k for k, v in list(datos.items()) if isinstance(v, (int, float, str))}
            mapeo = dict(list(mapeo.items())[:4])
        for et, ruta in mapeo.items():
            if campos and et not in campos:
                continue
            v = obtener_ruta(datos, ruta)
            salida.append({"etiqueta": et, "valor": formatear(v, (w.get("formatos") or {}).get(et)),
                           "nivel": nivel_de(v, (w.get("resaltar") or {}).get(et))})
    if errores and not salida and not listas:
        res = {"error": T("Sin datos", "No data") if w.get("ocultarErrores") else (T("Sin datos: ", "No data: ") + errores[0])[:160]}
    else:
        res = {"campos": salida, "listas": listas}
    CACHE[clave] = (time.time(), res)
    return res


def clima(cfg):
    w = next((x for x in cfg.get("barra") or [] if x.get("tipo") == "clima"), None)
    if not w:
        return {"error": T("No hay widget de clima en la barra.", "There is no weather widget in the bar.")}
    c = CACHE.get("clima")
    if c and time.time() - c[0] < 600:
        return c[1]
    lat, lon = w.get("lat"), w.get("lon")
    if lat is None or lon is None:
        return {"error": T("Pon lat y lon en el widget de clima", "Set lat and lon in the weather widget")}
    imperial = w.get("unidades") == "imperial"
    url = (f"https://api.open-meteo.com/v1/forecast?latitude={lat}&longitude={lon}"
           "&current=temperature_2m,apparent_temperature,relative_humidity_2m,weather_code,wind_speed_10m,is_day"
           "&daily=temperature_2m_max,temperature_2m_min&timezone=auto&forecast_days=1"
           + ("&temperature_unit=fahrenheit&wind_speed_unit=mph" if imperial else ""))
    try:
        d = pedir_json(url, timeout=5)
        cur, dia = d["current"], d["daily"]
        res = {"temp": cur["temperature_2m"], "sensacion": cur.get("apparent_temperature"),
               "humedad": cur.get("relative_humidity_2m"), "viento": cur.get("wind_speed_10m"),
               "codigo": cur.get("weather_code"), "dia": cur.get("is_day", 1),
               "max": dia["temperature_2m_max"][0], "min": dia["temperature_2m_min"][0],
               "unidad": "°F" if imperial else "°C", "vel": "mph" if imperial else "km/h",
               "lugar": w.get("lugar", "")}
    except Exception:
        res = {"error": T("Sin datos del clima", "No weather data")}
        CACHE["clima"] = (time.time() - 540, res)      # reintenta en un minuto
        return res
    CACHE["clima"] = (time.time(), res)
    return res


# ---------- Sistema ----------

def memoria():
    if ES_WINDOWS:
        import ctypes

        class MS(ctypes.Structure):
            _fields_ = [("dwLength", ctypes.c_ulong), ("dwMemoryLoad", ctypes.c_ulong),
                        ("ullTotalPhys", ctypes.c_ulonglong), ("ullAvailPhys", ctypes.c_ulonglong),
                        ("ullTotalPageFile", ctypes.c_ulonglong), ("ullAvailPageFile", ctypes.c_ulonglong),
                        ("ullTotalVirtual", ctypes.c_ulonglong), ("ullAvailVirtual", ctypes.c_ulonglong),
                        ("ullAvailExtendedVirtual", ctypes.c_ulonglong)]
        m = MS()
        m.dwLength = ctypes.sizeof(MS)
        ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(m))
        return {"total": m.ullTotalPhys, "usado": m.ullTotalPhys - m.ullAvailPhys}
    if ES_MAC:
        try:
            total = int(correr(["sysctl", "-n", "hw.memsize"], 3).stdout)
            vm = correr(["vm_stat"], 3).stdout
            pag = int(re.search(r"page size of (\d+)", vm).group(1))
            libres = sum(int(re.search(rf"{k}:\s+(\d+)", vm).group(1)) for k in ("Pages free", "Pages inactive", "Pages speculative"))
            return {"total": total, "usado": total - libres * pag}
        except Exception:
            return None
    try:
        info = {}
        with open("/proc/meminfo") as f:
            for linea in f:
                k, v = linea.split(":")
                info[k] = int(v.split()[0]) * 1024
        return {"total": info["MemTotal"], "usado": info["MemTotal"] - info["MemAvailable"]}
    except Exception:
        return None


CPU_PREV = {"v": None}


def _cpu_muestra():
    try:
        if ES_WINDOWS:
            import ctypes
            from ctypes import wintypes
            i, k, u = wintypes.FILETIME(), wintypes.FILETIME(), wintypes.FILETIME()
            if not ctypes.windll.kernel32.GetSystemTimes(ctypes.byref(i), ctypes.byref(k), ctypes.byref(u)):
                return None
            f = lambda t: (t.dwHighDateTime << 32) | t.dwLowDateTime
            return f(i), f(k) + f(u)              # el tiempo de kernel ya incluye el inactivo
        with open("/proc/stat") as fh:
            v = [int(x) for x in fh.readline().split()[1:9]]
        return v[3] + v[4], sum(v)
    except Exception:
        return None


def cpu():
    if ES_MAC:                     # macOS no expone contadores simples: suma del uso de los procesos
        r = correr(["ps", "-A", "-o", "%cpu="], 3)
        try:
            return max(0, min(100, round(sum(float(x.replace(",", ".")) for x in r.stdout.split()) / (os.cpu_count() or 1))))
        except Exception:
            return None
    a = _cpu_muestra()
    if a is None:
        return None
    prev, CPU_PREV["v"] = CPU_PREV["v"], a
    if not prev or a[1] - prev[1] <= 0:
        time.sleep(0.3)
        prev, a = a, _cpu_muestra()
        CPU_PREV["v"] = a
        if a is None:
            return None
    dt = a[1] - prev[1]
    return max(0, min(100, round(100 * (1 - (a[0] - prev[0]) / dt)))) if dt > 0 else None


def encendido_s():
    try:
        if ES_WINDOWS:
            import ctypes
            f = ctypes.windll.kernel32.GetTickCount64
            f.restype = ctypes.c_ulonglong
            return int(f() / 1000)
        if ES_MAC:
            m = re.search(r"sec = (\d+)", correr(["sysctl", "-n", "kern.boottime"], 3).stdout)
            return int(time.time() - int(m.group(1)))
        with open("/proc/uptime") as fh:
            return int(float(fh.read().split()[0]))
    except Exception:
        return None


NVIDIA_RUTAS = [r"C:\Windows\System32\nvidia-smi.exe",
                r"C:\Program Files\NVIDIA Corporation\NVSMI\nvidia-smi.exe"]
GPU = {"dato": None, "t": 0.0, "leyendo": False, "avisado": False}


def _avisar_gpu(msg):
    if not GPU["avisado"]:
        GPU["avisado"] = True
        log.warning("GPU: %s", msg)


def _leer_gpu():
    try:
        exe = shutil.which("nvidia-smi") or next((r for r in NVIDIA_RUTAS if os.path.isfile(r)), None)
        if not exe:
            return _avisar_gpu("no encontré nvidia-smi (¿driver de NVIDIA instalado?)")
        # Con Optimus la tarjeta duerme y nvidia-smi tarda varios segundos en despertarla
        r = correr([exe, "--query-gpu=name,utilization.gpu,memory.used,memory.total,temperature.gpu",
                    "--format=csv,noheader,nounits"], 15)
        if r is None or r.returncode != 0:
            return _avisar_gpu("nvidia-smi falló o tardó más de 15 s: " + ((r.stderr or r.stdout) if r else "sin respuesta")[:200])
        nombre, uso, mu, mt, temp = [x.strip() for x in r.stdout.strip().splitlines()[0].split(",")]

        def num(x):
            try:
                return int(round(float(x)))
            except ValueError:
                return None                     # "[N/A]" o "[Not Supported]"

        if not num(mt):
            return _avisar_gpu(f"nvidia-smi no reporta la VRAM total: {r.stdout.strip()[:120]}")
        GPU["dato"] = {"nombre": nombre, "uso": num(uso) or 0, "vram_usada": num(mu) or 0,
                       "vram_total": num(mt), "temp": num(temp)}
    except Exception as e:
        _avisar_gpu(f"no pude leer nvidia-smi: {e}")
    finally:
        GPU["t"] = time.time()
        GPU["leyendo"] = False


def gpu():
    """Se lee en segundo plano cada 15 s: no frena la página ni despierta la tarjeta a cada rato."""
    if not GPU["leyendo"] and time.time() - GPU["t"] > 15:
        GPU["leyendo"] = True
        threading.Thread(target=_leer_gpu, daemon=True).start()
    return GPU["dato"]


def discos(cfg):
    pedidos = cfg.get("discos", "auto")
    if pedidos == "auto":
        pedidos = unidades()
    salida = []
    for d in pedidos:
        try:
            u = shutil.disk_usage(d)
            salida.append({"unidad": d.rstrip("\\"), "total": u.total, "usado": u.used})
        except Exception:
            continue
    return salida


def procesos_top(n=5):
    """Programas que más RAM ocupan, agrupando procesos con el mismo nombre."""
    suma = {}
    if ES_WINDOWS:
        r = correr(["tasklist", "/fo", "csv", "/nh"], 6)
        if not r:
            return []
        for linea in r.stdout.splitlines():
            partes = re.findall(r'"([^"]*)"', linea)
            if len(partes) >= 5:
                kb = int(re.sub(r"\D", "", partes[4]) or 0)
                nombre = re.sub(r"\.exe$", "", partes[0], flags=re.I)
                suma[nombre] = suma.get(nombre, 0) + kb * 1024
    else:
        r = correr(["ps", "-eo", "rss=,comm="], 4)
        for linea in (r.stdout.splitlines() if r else []):
            p = linea.split(None, 1)
            if len(p) == 2 and p[0].isdigit():
                nombre = os.path.basename(p[1].strip())
                suma[nombre] = suma.get(nombre, 0) + int(p[0]) * 1024
    return [{"nombre": k, "bytes": v} for k, v in sorted(suma.items(), key=lambda x: -x[1])[:n]]


def recortar_memoria():
    """Vacía el conjunto de trabajo de los procesos del usuario (lo que hacen los 'liberadores de RAM')."""
    if not ES_WINDOWS:
        return 0
    import ctypes
    from ctypes import wintypes
    k32, psapi = ctypes.windll.kernel32, ctypes.windll.psapi
    arr = (wintypes.DWORD * 4096)()
    usados = wintypes.DWORD()
    psapi.EnumProcesses(ctypes.byref(arr), ctypes.sizeof(arr), ctypes.byref(usados))
    yo = os.getpid()
    recortados = 0
    for pid in arr[: usados.value // ctypes.sizeof(wintypes.DWORD)]:
        if pid in (0, 4, yo):
            continue
        h = k32.OpenProcess(0x1000 | 0x0100, False, pid)  # QUERY_LIMITED_INFORMATION | SET_QUOTA
        if h:
            if psapi.EmptyWorkingSet(h):
                recortados += 1
            k32.CloseHandle(h)
    return recortados


def liberar(cfg):
    antes = memoria()
    acciones = []
    items = {it["id"]: it for it in todos_los_items(cfg)}
    # 1) Descargar modelos de Ollama que estén en memoria
    def de_tipo(tipo, puerto):
        # "freeMemory": "ollama" | "comfyui" en el acceso, o el id/puerto de siempre
        return next((it for it in items.values() if it.get("liberar") == tipo), None) or items.get(tipo) or next(
            (it for it in items.values() if urlparse(it.get("url") or "").port == puerto and "liberar" not in it), None)
    ol = de_tipo("ollama", 11434)
    if ol and ol.get("url"):
        base = ol["url"].rstrip("/")
        try:
            cargados = json.loads(urllib.request.urlopen(base + "/api/ps", timeout=2).read()).get("models", [])
            for m in cargados:
                req = urllib.request.Request(base + "/api/generate", method="POST",
                                             data=json.dumps({"model": m["name"], "keep_alive": 0}).encode(),
                                             headers={"Content-Type": "application/json"})
                urllib.request.urlopen(req, timeout=10).read()
            if cargados:
                acciones.append(T(f"Ollama descargó {len(cargados)} modelo(s)", f"Ollama unloaded {len(cargados)} model(s)"))
        except Exception:
            pass
    # 2) Pedir a ComfyUI que suelte modelos y caché
    cu = de_tipo("comfyui", 8188)
    if cu and cu.get("url"):
        try:
            req = urllib.request.Request(cu["url"].rstrip("/") + "/free", method="POST",
                                         data=json.dumps({"unload_models": True, "free_memory": True}).encode(),
                                         headers={"Content-Type": "application/json"})
            urllib.request.urlopen(req, timeout=5).read()
            acciones.append(T("ComfyUI liberó modelos", "ComfyUI freed its models"))
        except Exception:
            pass
    # 3) Recortar conjuntos de trabajo
    n = recortar_memoria()
    if n:
        acciones.append(T(f"{n} procesos compactados", f"{n} processes trimmed"))
    time.sleep(1.2)
    despues = memoria()
    liberado = max(0, (antes["usado"] - despues["usado"])) if antes and despues else 0
    return {"liberado": liberado, "acciones": acciones, "memoria": despues}


# ---------- Abrir programas y servicios ----------

def servicio_existe(nombre):
    r = correr(["sc", "query", nombre], 4)
    return r is not None and r.returncode == 0, (r.stdout if r else "")


def systemd(srv, accion):
    """Linux: servicio de usuario sin permisos; si es del sistema, pkexec pide la contraseña."""
    if not shutil.which("systemctl"):
        return None
    for usuario in (True, False):
        base = ["systemctl"] + (["--user"] if usuario else [])
        r = correr(base + ["show", "-p", "LoadState,ActiveState", srv], 4)
        if not r or "LoadState=loaded" not in r.stdout:
            continue
        activo = "ActiveState=active" in r.stdout
        if (accion == "start") == activo:
            return True, (T("El servicio ya está corriendo.", "The service is already running.") if activo
                          else T("El servicio ya estaba detenido.", "The service was already stopped."))
        cmd = base + [accion, srv] if usuario else (["pkexec"] if shutil.which("pkexec") else []) + base + [accion, srv]
        subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, start_new_session=True)
        return True, (T("Iniciando el servicio…", "Starting the service…") if accion == "start"
                      else T("Deteniendo el servicio…", "Stopping the service…"))
    return None


def lanzar(item):
    srv = item.get("servicio")
    if ES_WINDOWS and srv:
        existe, salida = servicio_existe(srv)
        if existe:
            if "RUNNING" in salida:
                return True, T("El servicio ya está corriendo.", "The service is already running.")
            # Arrancar un servicio de Windows requiere permiso de administrador: Windows pedirá confirmación
            subprocess.Popen(["powershell", "-NoProfile", "-WindowStyle", "Hidden", "-Command",
                              f"Start-Process sc.exe -ArgumentList 'start','{srv}' -Verb RunAs -WindowStyle Hidden"],
                             creationflags=SIN_VENTANA)
            return True, T("Windows te pedirá permiso para iniciar el servicio.", "Windows will ask for permission to start the service.")
    if srv and not ES_WINDOWS and not ES_MAC:
        r = systemd(srv, "start")
        if r:
            return r
    ruta = resolver_ruta(item)
    if not ruta:
        if item.get("buscar") and BUSCANDO["activo"]:
            return False, T("Sigo buscando el programa en tus discos; intenta en un momento.", "Still looking for the program on your drives; try again in a moment.")
        return False, T("No lo encontré en tus discos. Usa «Buscar programas» o edítalo y pon su ruta.", "Not found on your drives. Use “Find programs” or edit it and set its path.")
    carpeta = os.path.dirname(ruta)
    if ES_WINDOWS:
        low = ruta.lower()
        if low.endswith((".bat", ".cmd")):
            subprocess.Popen(["cmd", "/c", "start", "", ruta], cwd=carpeta)
        elif low.endswith(".py"):
            subprocess.Popen(["cmd", "/c", "start", "", "python", ruta], cwd=carpeta)
        else:
            os.startfile(ruta)
    elif ES_MAC and (ruta.endswith(".app") or not os.access(ruta, os.X_OK) or os.path.isdir(ruta)):
        subprocess.Popen(["open", ruta], cwd=carpeta)
    elif ruta.endswith(".py"):
        subprocess.Popen([sys.executable, ruta], cwd=carpeta, start_new_session=True)
    elif ruta.endswith(".sh") and not os.access(ruta, os.X_OK):
        subprocess.Popen(["sh", ruta], cwd=carpeta, start_new_session=True)
    elif os.path.isfile(ruta) and os.access(ruta, os.X_OK):
        subprocess.Popen([ruta], cwd=carpeta, start_new_session=True)
    elif ruta.endswith(".desktop") and shutil.which("gio"):
        subprocess.Popen(["gio", "launch", ruta], cwd=carpeta, start_new_session=True)
    else:
        abridor = "open" if ES_MAC else (shutil.which("xdg-open") or "xdg-open")
        subprocess.Popen([abridor, ruta], cwd=carpeta, start_new_session=True)
    return True, T(f"Abriendo {item['nombre']}…", f"Opening {item['nombre']}…")


def pids_en_puerto(puerto):
    """Procesos que escuchan en ese puerto TCP de esta PC."""
    pids = set()
    if ES_WINDOWS:
        r = correr(["netstat", "-ano", "-p", "tcp"], 8)
        for linea in (r.stdout.splitlines() if r else []):
            p = linea.split()
            if len(p) >= 5 and p[3].upper() in ("LISTENING", "ESCUCHANDO") and p[1].rsplit(":", 1)[-1] == str(puerto):
                pids.add(int(p[4]))
        return pids
    if ES_MAC or not os.path.isdir("/proc/net"):
        r = correr(["lsof", "-nP", f"-iTCP:{puerto}", "-sTCP:LISTEN", "-t"], 6)
        return {int(x) for x in (r.stdout.split() if r else []) if x.isdigit()}
    inodos = set()
    for f in ("/proc/net/tcp", "/proc/net/tcp6"):
        try:
            with open(f) as fh:
                for linea in fh.readlines()[1:]:
                    c = linea.split()
                    if c[3] == "0A" and int(c[1].rsplit(":", 1)[1], 16) == puerto:
                        inodos.add(c[9])
        except OSError:
            pass
    for pid in filter(str.isdigit, os.listdir("/proc")):
        try:
            for fd in os.listdir(f"/proc/{pid}/fd"):
                if os.readlink(f"/proc/{pid}/fd/{fd}").replace("socket:[", "").rstrip("]") in inodos:
                    pids.add(int(pid))
                    break
        except OSError:
            continue
    return pids


def detener(item, cfg):
    if item.get("detener"):                                   # comando propio, p. ej. "Detener PromptForge.cmd"
        ruta = os.path.expandvars(item["detener"])
        if not os.path.exists(ruta):
            return False, T("No encontré el programa para detenerlo.", "I couldn't find the program that stops it.")
        if ES_WINDOWS:
            subprocess.Popen(["cmd", "/c", "start", "", ruta], cwd=os.path.dirname(ruta))
        else:
            arg = [ruta] if os.access(ruta, os.X_OK) else ["sh", ruta]
            subprocess.Popen(arg, cwd=os.path.dirname(ruta), start_new_session=True)
        SILENCIO[item["id"]] = time.time()
        return True, T(f"Deteniendo {item['nombre']}…", f"Stopping {item['nombre']}…")
    srv = item.get("servicio")
    if ES_WINDOWS and srv:
        existe, salida = servicio_existe(srv)
        if existe:
            if "STOPPED" in salida:
                return True, T("El servicio ya estaba detenido.", "The service was already stopped.")
            subprocess.Popen(["powershell", "-NoProfile", "-WindowStyle", "Hidden", "-Command",
                              f"Start-Process sc.exe -ArgumentList 'stop','{srv}' -Verb RunAs -WindowStyle Hidden"],
                             creationflags=SIN_VENTANA)
            SILENCIO[item["id"]] = time.time()
            return True, T("Windows te pedirá permiso para detener el servicio.", "Windows will ask for permission to stop the service.")
    if srv and not ES_WINDOWS and not ES_MAC:
        r = systemd(srv, "stop")
        if r:
            SILENCIO[item["id"]] = time.time()
            return r
    url = item.get("url")
    if not url:
        return False, T("Este acceso no tiene cómo detenerse.", "This shortcut has no way to be stopped.")
    p = urlparse(url)
    if p.hostname not in ("127.0.0.1", "localhost"):
        return False, T("Solo detengo programas de esta computadora.", "I only stop programs on this computer.")
    puerto = p.port or (443 if p.scheme == "https" else 80)
    if puerto == int(cfg.get("puerto", 3000)):
        return False, T("Ese puerto es el de Timonel.", "That port is Timonel's own.")
    pids = {x for x in pids_en_puerto(puerto) if x not in (0, 4, os.getpid())}
    if not pids:
        return False, T("No encontré qué programa usa ese puerto: quizá ya estaba apagado.", "Nothing is listening on that port: maybe it was already off.")
    for pid in pids:
        if ES_WINDOWS:
            correr(["taskkill", "/PID", str(pid), "/T", "/F"], 10)
        else:
            try:
                os.kill(pid, 15)
            except OSError:
                pass
    SILENCIO[item["id"]] = time.time()
    log.info("Detenido %s (PID %s)", item["id"], ", ".join(map(str, pids)))
    return True, T(f"Detuve {item['nombre']}.", f"Stopped {item['nombre']}.")


# ---------- Edición desde la página ----------

def slug(t):
    t = unicodedata.normalize("NFKD", t).encode("ascii", "ignore").decode().lower()
    return re.sub(r"[^a-z0-9]+", "-", t).strip("-") or "item"


def agregar_item(datos):
    with CANDADO:
        cfg = cargar_config()
        cfg.setdefault("grupos", [])
        nombre = (datos.get("nombre") or "").strip()
        if not nombre:
            return False, T("Falta el nombre.", "The name is missing.")
        grupo = (datos.get("grupo") or "").strip() or (cfg["grupos"][0]["nombre"] if cfg.get("grupos") else "General")
        g = next((g for g in cfg["grupos"] if g["nombre"] == grupo), None)
        if not g:
            g = {"nombre": grupo, "items": []}
            cfg["grupos"].append(g)
        base, ids = slug(nombre), {it["id"] for it in todos_los_items(cfg)}
        ident, i = base, 2
        while ident in ids:
            ident, i = f"{base}-{i}", i + 1
        it = {"id": ident, "nombre": nombre}
        for k in ("desc", "url", "lanzar", "archivo", "icono", "ping"):
            v = (datos.get(k) or "").strip().strip('"')
            if v:
                it[k] = v
        if (it.get("url") or it.get("ping")) and datos.get("vigilar"):
            it["vigilar"] = True
            if datos.get("avisar"):
                it["avisar"] = True
        if not any(k in it for k in ("url", "lanzar", "archivo", "ping")):
            return False, T("Pon una dirección web, un programa o una página local.", "Add a web address, a program or a local page.")
        g["items"].append(it)
        guardar_config(cfg)
        return True, T(f"Agregué {nombre} a {grupo}.", f"Added {nombre} to {grupo}.")


def ubicar(cfg, ident):
    for g in todos_los_grupos(cfg["grupos"]):
        for n, it in enumerate(g.get("items") or []):
            if it.get("id") == ident:
                return g, n, it
    return None, None, None


def grupo_destino(cfg, nombre):
    g = next((x for x in todos_los_grupos(cfg["grupos"]) if x["nombre"] == nombre), None)
    if not g:
        g = {"nombre": nombre, "items": []}
        cfg["grupos"].append(g)
    g.setdefault("items", [])
    return g


def editar_item(datos):
    with CANDADO:
        cfg = cargar_config()
        g, n, it = ubicar(cfg, datos.get("id"))
        if not it:
            return False, T("No lo encontré.", "Not found.")
        nombre = (datos.get("nombre") or "").strip()
        if not nombre:
            return False, T("Falta el nombre.", "The name is missing.")
        it["nombre"] = nombre
        for k in ("desc", "icono", "url", "lanzar", "archivo", "ping"):
            if k in datos:
                v = (datos.get(k) or "").strip().strip('"')
                if v:
                    it[k] = v
                else:
                    it.pop(k, None)
        if not any(k in it for k in ("url", "lanzar", "archivo", "ping", "servicio", "buscar")):
            return False, T("Pon una dirección web, un programa o una página local.", "Add a web address, a program or a local page.")
        for k in ("vigilar", "avisar"):
            if k in datos:
                if datos[k] and (it.get("url") or it.get("ping")):
                    it[k] = True
                else:
                    it.pop(k, None)
        destino = (datos.get("grupo") or "").strip()
        if destino and destino != g["nombre"]:
            g["items"].pop(n)
            grupo_destino(cfg, destino)["items"].append(it)
            cfg["grupos"] = [x for x in cfg["grupos"] if x.get("items") or x.get("grupos")]
        guardar_config(cfg)
        return True, T(f"Guardé {nombre}.", f"Saved {nombre}.")


def mover_item(datos):
    with CANDADO:
        cfg = cargar_config()
        g, n, it = ubicar(cfg, datos.get("id"))
        if not it:
            return False, T("No lo encontré.", "Not found.")
        destino = (datos.get("grupo") or g["nombre"]).strip()
        g["items"].pop(n)
        dg = grupo_destino(cfg, destino)
        indice = max(0, min(int(datos.get("indice", len(dg["items"]))), len(dg["items"])))
        dg["items"].insert(indice, it)
        cfg["grupos"] = [x for x in cfg["grupos"] if x.get("items") or x.get("grupos")]
        guardar_config(cfg)
        return True, T(f"Moví {it['nombre']}.", f"Moved {it['nombre']}.")


def quitar_item(ident):
    with CANDADO:
        cfg = cargar_config()
        for g in todos_los_grupos(cfg["grupos"]):
            antes = len(g.get("items") or [])
            g["items"] = [it for it in g.get("items") or [] if it.get("id") != ident]
            if len(g["items"]) != antes:
                cfg["grupos"] = [x for x in cfg["grupos"] if x.get("items") or x.get("grupos")]
                guardar_config(cfg)
                return True, T("Quitado.", "Removed.")
        return False, T("No lo encontré.", "Not found.")


# ---------- App instalable (PWA) ----------

def _png(tam):
    """Ícono de Timonel sin librerías: un timón de latón sobre azul marino (8 rayos, aro y cubo)."""
    import math
    import struct
    import zlib
    fondo, laton, claro = (11, 18, 32), (217, 164, 65), (240, 189, 90)
    filas = bytearray()
    for y in range(tam):
        filas.append(0)
        for x in range(tam):
            dx, dy = (x + .5) / tam - .5, (y + .5) / tam - .5
            r, ang = math.hypot(dx, dy), math.atan2(dy, dx)
            c = fondo
            if .25 <= r <= .32 or r <= .085:                                # aro y cubo
                c = laton
            elif r <= .43:                                                   # rayos que salen del aro
                d = abs(((ang + math.pi / 8) % (math.pi / 4)) - math.pi / 8) * r
                if d <= .022:
                    c = laton
            for k in range(8):                                               # perillas
                a = k * math.pi / 4
                if math.hypot(dx - .43 * math.cos(a), dy - .43 * math.sin(a)) <= .042:
                    c = claro
            if r <= .035:
                c = fondo
            filas.extend(c)

    def bloque(tipo, datos):
        return struct.pack(">I", len(datos)) + tipo + datos + struct.pack(">I", zlib.crc32(tipo + datos) & 0xFFFFFFFF)
    return (b"\x89PNG\r\n\x1a\n" + bloque(b"IHDR", struct.pack(">IIBBBBB", tam, tam, 8, 2, 0, 0, 0))
            + bloque(b"IDAT", zlib.compress(bytes(filas), 9)) + bloque(b"IEND", b""))


PNGS = {}


def icono_png(tam):
    if tam not in PNGS:
        PNGS[tam] = _png(tam)
    return PNGS[tam]


def manifest(cfg):
    pestanas = []
    for g in todos_los_grupos(cfg.get("grupos")):
        p = g.get("pestana")
        if p and p not in pestanas:
            pestanas.append(p)
    return {"name": "Timonel" + (" · " + cfg["titulo"] if cfg.get("titulo") else ""), "short_name": "Timonel", "start_url": "/",
            "display": "standalone", "background_color": "#0b1220", "theme_color": "#0b1220", "lang": idioma(),
            "icons": [{"src": "/icono-192.png", "sizes": "192x192", "type": "image/png"},
                      {"src": "/icono-512.png", "sizes": "512x512", "type": "image/png"}],
            "shortcuts": [{"name": p, "url": "/#" + quote(p)} for p in pestanas[:4]]}


SW = """self.addEventListener('install', () => self.skipWaiting());
self.addEventListener('activate', e => e.waitUntil(self.clients.claim()));
self.addEventListener('fetch', e => {
  if (e.request.mode !== 'navigate') return;
  const es = (navigator.language || '').toLowerCase().startsWith('es');
  e.respondWith(fetch(e.request).catch(() => new Response(
    '<meta charset=utf-8><title>Timonel</title><body style="margin:0;display:grid;place-items:center;height:100vh;background:#0b1220;color:#e6edf7;font:18px system-ui,sans-serif;text-align:center"><div><div style="font-size:42px;color:#d9a441">&#9096;</div>'
    + (es ? 'Timonel est&aacute; apagado.<br><small style="color:#93a1b8">Ejecuta Timonel.bat, timonel.sh o Timonel.command y recarga.</small>'
          : 'Timonel is not running.<br><small style="color:#93a1b8">Run Timonel.bat, timonel.sh or Timonel.command and reload.</small>') + '</div>',
    { headers: { 'Content-Type': 'text/html; charset=utf-8' } })));
});
""".encode("utf-8")


# ---------- MCP: que una IA lea y edite el tablero ----------

def token_mcp():
    try:
        with open(TOKEN_MCP, "r", encoding="utf-8") as f:
            t = f.read().strip()
        if len(t) >= 32:
            return t
    except OSError:
        pass
    t = secrets.token_urlsafe(32)
    with open(TOKEN_MCP, "w", encoding="utf-8") as f:
        f.write(t)
    return t


_OBJ = {"type": "object", "properties": {}}
HERRAMIENTAS = [
    {"name": "read_config", "description": "Returns Timonel's config.json (groups, shortcuts, settings) without passwords or keys.", "inputSchema": _OBJ},
    {"name": "validate_config", "description": "Checks config.json and reports errors with line and column.", "inputSchema": _OBJ},
    {"name": "service_status", "description": "Which watched services are online or off, with latency.", "inputSchema": _OBJ},
    {"name": "add_shortcut", "description": "Adds a shortcut to a dashboard group (created if missing). Needs mcp.write = true.",
     "inputSchema": {"type": "object", "required": ["name"], "properties": {
         "name": {"type": "string"}, "group": {"type": "string", "description": "Target group; defaults to the first one"},
         "url": {"type": "string", "description": "Web or local address (http://127.0.0.1:port)"},
         "launch": {"type": "string", "description": "Path to a program or script to start it"},
         "file": {"type": "string", "description": "Path to a local .html page"},
         "description": {"type": "string"}, "icon": {"type": "string", "description": "mdi-name, si-name, a URL or /iconos/file.png"},
         "ping": {"type": "string", "description": "Host to check with ping"},
         "watch": {"type": "boolean", "description": "Check whether it is running"}}}},
    {"name": "remove_shortcut", "description": "Removes a shortcut by its id. Needs mcp.write = true.",
     "inputSchema": {"type": "object", "required": ["id"], "properties": {"id": {"type": "string"}}}},
]
ALIAS_MCP = {"leer_config": "read_config", "validar_config": "validate_config", "estado_servicios": "service_status",
             "agregar_servicio": "add_shortcut", "quitar_servicio": "remove_shortcut"}


def responder_mcp(cfg, msg):
    m, mid = msg.get("method"), msg.get("id")

    def ok(res):
        return {"jsonrpc": "2.0", "id": mid, "result": res}

    def texto(t, error=False):
        return ok({"content": [{"type": "text", "text": t}], "isError": error})

    if m == "initialize":
        version = (msg.get("params") or {}).get("protocolVersion") or "2025-06-18"
        return ok({"protocolVersion": version, "capabilities": {"tools": {}},
                   "serverInfo": {"name": "timonel", "version": VERSION}})
    if m == "ping":
        return ok({})
    if m == "tools/list":
        return ok({"tools": HERRAMIENTAS})
    if m == "tools/call":
        p = msg.get("params") or {}
        n, a = p.get("name"), convertir(p.get("arguments") or {}, True)
        n = ALIAS_MCP.get(n, n)
        if n == "read_config":
            return texto(json.dumps(sin_secretos(cfg), ensure_ascii=False, indent=2))
        if n == "validate_config":
            return texto(json.dumps(validar_config(), ensure_ascii=False, indent=2))
        if n == "service_status":
            ronda(cfg)
            nombres = {it["id"]: it["nombre"] for it in todos_los_items(cfg)}
            lineas = [f"{nombres.get(k, k)}: {T('en línea', 'online') if v['estado'] == 'arriba' else T('apagado', 'off') if v['estado'] == 'caido' else T('puerto ocupado por otra app', 'port taken by another app')}"
                      + (f" ({v['ms']} ms)" if v.get("ms") is not None else "") for k, v in ESTADO.items()]
            return texto("\n".join(lineas) or T("No hay servicios vigilados.", "No watched services."))
        if n in ("add_shortcut", "remove_shortcut"):
            if not (cfg.get("mcp") or {}).get("escritura"):
                return texto(T('La escritura por MCP está apagada. Pon "mcp": {"activo": true, "escritura": true} en config.json.',
                               'MCP writing is off. Set "mcp": {"active": true, "write": true} in config.json.'), True)
            hecho, msj = agregar_item(a) if n == "add_shortcut" else quitar_item(a.get("id"))
            return texto(msj, not hecho)
        return {"jsonrpc": "2.0", "id": mid, "error": {"code": -32602, "message": f"Unknown tool: {n}"}}
    return {"jsonrpc": "2.0", "id": mid, "error": {"code": -32601, "message": f"Method not supported: {m}"}}


# ---------- HTTP ----------

class Manejador(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def responder(self, codigo, cuerpo, tipo="application/json; charset=utf-8"):
        datos = cuerpo if isinstance(cuerpo, bytes) else json.dumps(cuerpo, ensure_ascii=False).encode("utf-8")
        self.send_response(codigo)
        self.send_header("Content-Type", tipo)
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Length", str(len(datos)))
        self.end_headers()
        self.wfile.write(datos)

    def fijar_idioma(self):
        v = (self.headers.get("X-Idioma") or "").lower()[:2]
        IDIOMA.v = v if v in ("es", "en") else None

    def host_valido(self):
        host = (self.headers.get("Host") or "").split(":")[0]
        return host in ("127.0.0.1", "localhost")

    def cuerpo(self):
        largo = int(self.headers.get("Content-Length") or 0)
        return json.loads(self.rfile.read(largo) or b"{}")

    def servir_local(self, ruta):
        # /local/<id>/<archivo...>  -> sirve la carpeta de la página HTML local de ese elemento
        partes = ruta.split("/", 3)
        ident = partes[2] if len(partes) > 2 else ""
        item = buscar_item(cargar_config(), ident)
        if not item or not item.get("archivo"):
            return self.responder(404, {"error": T("no existe", "not found")})
        principal = os.path.expandvars(item["archivo"])
        carpeta = os.path.realpath(os.path.dirname(principal))
        resto = unquote(partes[3]) if len(partes) > 3 and partes[3] else os.path.basename(principal)
        destino = os.path.realpath(os.path.join(carpeta, resto))
        if not destino.startswith(carpeta) or not os.path.isfile(destino):
            return self.responder(404, {"error": T("no existe", "not found")})
        tipo = mimetypes.guess_type(destino)[0] or "application/octet-stream"
        if tipo.startswith("text/") or tipo in ("application/javascript", "application/json"):
            tipo += "; charset=utf-8"
        with open(destino, "rb") as f:
            return self.responder(200, f.read(), tipo)

    def servir_carpeta(self, carpeta, nombre):
        carpeta = os.path.realpath(carpeta)
        destino = os.path.realpath(os.path.join(carpeta, unquote(nombre)))
        if not destino.startswith(carpeta + os.sep) or not os.path.isfile(destino):
            return self.responder(404, {"error": T("no existe", "not found")})
        with open(destino, "rb") as f:
            return self.responder(200, f.read(), mimetypes.guess_type(destino)[0] or "application/octet-stream")

    def do_GET(self):
        self.fijar_idioma()
        if not self.host_valido():
            return self.responder(403, {"error": T("host no permitido", "host not allowed")})
        partes = urlparse(self.path)
        ruta, q = partes.path, parse_qs(partes.query)
        try:
            if ruta in ("/", "/index.html"):
                with open(INDEX, "rb") as f:
                    return self.responder(200, f.read(), "text/html; charset=utf-8")
            if ruta.startswith("/local/"):
                return self.servir_local(ruta)
            if ruta.startswith("/iconos/"):
                return self.servir_carpeta(ICONOS, ruta[len("/iconos/"):])
            if ruta in ("/custom.css", "/custom.js"):
                p = os.path.join(BASE, ruta.lstrip("/"))
                tipo = "text/css; charset=utf-8" if ruta.endswith("css") else "application/javascript; charset=utf-8"
                cuerpo = open(p, "rb").read() if os.path.isfile(p) else b""
                return self.responder(200, cuerpo, tipo)
            if ruta in ("/icono-192.png", "/icono-512.png", "/favicon.ico"):
                return self.responder(200, icono_png(512 if "512" in ruta else 192), "image/png")
            if ruta == "/sw.js":
                return self.responder(200, SW, "application/javascript; charset=utf-8")
            cfg, err_cfg = cargar_config_tolerante()
            if ruta == "/manifest.json":
                return self.responder(200, manifest(cfg), "application/manifest+json; charset=utf-8")
            if ruta == "/api/config":
                extra = {it["id"]: bool(resolver_ruta(it)) for it in todos_los_items(cfg)
                         if it.get("lanzar") or it.get("buscar")}
                salida = {**sin_secretos(cfg), "_rutas": extra, "_buscando": BUSCANDO["activo"], "_version": VERSION,
                          "_idioma": idioma(), "_ingles": FORMATO["en"],
                          "_so": "windows" if ES_WINDOWS else "mac" if ES_MAC else "linux",
                          "_pid": os.getpid(), "_arranque": INICIO,
                          "_reiniciar": os.path.getmtime(os.path.abspath(__file__)) > INICIO + 1}
                if err_cfg:
                    salida["_error"] = err_cfg
                return self.responder(200, salida)
            if ruta == "/api/validar":
                return self.responder(200, validar_config())
            if ruta == "/api/estado":
                VISTO["t"] = time.time()
                if "id" in q:
                    ronda(cfg, solo=q["id"][0])
                else:
                    ultima = max((v.get("revisado_en", 0) for v in ESTADO.values()), default=0)
                    if "ahora" in q or not ESTADO or time.time() - ultima > max(45, 3 * int(cfg.get("intervalo_s", 15))):
                        ronda(cfg)
                return self.responder(200, ESTADO)
            if ruta == "/api/sistema":
                return self.responder(200, {"memoria": memoria(), "gpu": gpu(), "discos": discos(cfg),
                                            "procesos": procesos_top(), "equipo": socket.gethostname(),
                                            "cpu": cpu(), "nucleos": os.cpu_count(), "encendido": encendido_s()})
            if ruta == "/api/clima":
                return self.responder(200, clima(cfg))
            if ruta.startswith("/api/widget/"):
                ident = unquote(ruta[len("/api/widget/"):])
                if ident.startswith("barra-"):
                    try:
                        w = (cfg.get("barra") or [])[int(ident[6:])]
                    except (ValueError, IndexError):
                        w = None
                else:
                    item = buscar_item(cfg, ident)
                    w = item.get("widget") if item else None
                    base_w = item.get("url") if item else None
                if not isinstance(w, dict) or w.get("tipo") != "api":
                    return self.responder(404, {"error": T("ese acceso no tiene widget de API", "that shortcut has no API widget")})
                return self.responder(200, widget_api(cfg, w, "w:" + ident, locals().get("base_w")))
            return self.responder(404, {"error": T("no existe", "not found")})
        except json.JSONDecodeError as e:
            return self.responder(500, {"error": T(f"config.json tiene un error en la línea {e.lineno}: {e.msg}", f"config.json has an error on line {e.lineno}: {e.msg}")})
        except (ConnectionAbortedError, ConnectionResetError, BrokenPipeError):
            return                              # el navegador cerró la pestaña a media respuesta
        except Exception as e:                  # nunca dejar al navegador sin respuesta
            log.exception("GET %s", self.path)
            return self.responder(500, {"error": T(f"Error interno: {e}. Detalle en timonel.log", f"Internal error: {e}. Details in timonel.log")})

    def do_POST(self):
        self.fijar_idioma()
        if not self.host_valido():
            return self.responder(403, {"error": T("host no permitido", "host not allowed")})
        origen = self.headers.get("Origin")
        if origen and urlparse(origen).hostname not in ("127.0.0.1", "localhost"):
            # Ninguna página externa puede pedirle a Timonel que abra programas
            return self.responder(403, {"error": T("origen no permitido", "origin not allowed")})
        ruta = urlparse(self.path).path
        try:
            datos = self.cuerpo()
            if ruta == "/api/mcp":
                return self.mcp(datos)
            if ruta == "/api/lanzar":
                item = buscar_item(cargar_config(), datos.get("id"))
                if not item:
                    return self.responder(404, {"ok": False, "mensaje": T("Elemento desconocido.", "Unknown item.")})
                ok, msg = lanzar(item)
                return self.responder(200 if ok else 400, {"ok": ok, "mensaje": msg})
            if ruta == "/api/liberar":
                return self.responder(200, liberar(cargar_config()))
            if ruta == "/api/agregar":
                ok, msg = agregar_item(datos)
                return self.responder(200 if ok else 400, {"ok": ok, "mensaje": msg})
            if ruta == "/api/quitar":
                ok, msg = quitar_item(datos.get("id"))
                return self.responder(200 if ok else 400, {"ok": ok, "mensaje": msg})
            if ruta in ("/api/editar", "/api/mover"):
                ok, msg = (editar_item if ruta == "/api/editar" else mover_item)(datos)
                return self.responder(200 if ok else 400, {"ok": ok, "mensaje": msg})
            if ruta == "/api/detener":
                cfg_d = cargar_config()
                item = buscar_item(cfg_d, datos.get("id"))
                if not item:
                    return self.responder(404, {"ok": False, "mensaje": T("Elemento desconocido.", "Unknown item.")})
                ok, msg = detener(item, cfg_d)
                return self.responder(200 if ok else 400, {"ok": ok, "mensaje": msg})
            if ruta == "/api/reiniciar":
                reiniciar()
                return self.responder(200, {"ok": True, "mensaje": T("Reiniciando…", "Restarting…")})
            if ruta == "/api/rebuscar":
                threading.Thread(target=buscar_programas, daemon=True).start()
                return self.responder(200, {"ok": True})
            return self.responder(404, {"error": T("no existe", "not found")})
        except Exception as e:
            log.exception("POST %s", ruta)
            return self.responder(500, {"ok": False, "mensaje": str(e)})

    def mcp(self, datos):
        cfg = cargar_config_tolerante()[0]
        if not (cfg.get("mcp") or {}).get("activo"):
            return self.responder(404, {"error": T('MCP apagado: pon "mcp": {"activo": true} en config.json', 'MCP is off: set "mcp": {"active": true} in config.json')})
        dado = (self.headers.get("Authorization") or "").replace("Bearer ", "", 1).strip()
        if not secrets.compare_digest(dado.encode(), token_mcp().encode()):
            return self.responder(401, {"error": T("token inválido (está en mcp_token.txt)", "invalid token (it is in mcp_token.txt)")})
        lote = datos if isinstance(datos, list) else [datos]
        respuestas = [responder_mcp(cfg, m) for m in lote if isinstance(m, dict) and "id" in m]
        if not respuestas:                       # solo notificaciones
            self.send_response(202)
            self.send_header("Content-Length", "0")
            self.end_headers()
            return
        return self.responder(200, respuestas if isinstance(datos, list) else respuestas[0])


class Servidor(ThreadingHTTPServer):
    # En Windows SO_REUSEADDR deja que dos procesos escuchen el mismo puerto: se desactiva
    allow_reuse_address = not ES_WINDOWS
    daemon_threads = True


def reiniciar():
    """Arranca una copia nueva (que espera a que se libere el puerto) y cierra esta."""
    exe = sys.executable
    if ES_WINDOWS:
        w = os.path.join(os.path.dirname(exe), "pythonw.exe")
        exe = w if os.path.isfile(w) else exe
        extra = {"creationflags": 0x00000008 | 0x00000200 | SIN_VENTANA}      # sin consola, grupo propio
    else:
        extra = {"start_new_session": True}
    subprocess.Popen([exe, os.path.abspath(__file__), "--no-browser", "--esperar"], cwd=BASE,
                     stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, close_fds=True, **extra)
    log.info("Reinicio pedido desde la página")

    def cerrar():
        time.sleep(0.4)
        try:
            SRV["s"].shutdown()
            SRV["s"].server_close()
        finally:
            os._exit(0)
    threading.Thread(target=cerrar, daemon=True).start()


def autostart(encender):
    """Abre Timonel al iniciar sesión (sin abrir el navegador) o deja de hacerlo. Devuelve un mensaje."""
    py, script = sys.executable, os.path.abspath(__file__)
    if ES_WINDOWS:
        carpeta = os.path.join(os.environ.get("APPDATA", ""), "Microsoft", "Windows", "Start Menu", "Programs", "Startup")
        lnk = os.path.join(carpeta, "Timonel.lnk")
        if not encender:
            if os.path.exists(lnk):
                os.remove(lnk)
            return T("Listo: Timonel ya no se abre al iniciar Windows.", "Done: Timonel no longer starts with Windows.")
        w = os.path.join(os.path.dirname(py), "pythonw.exe")
        ps = ("$s=(New-Object -ComObject WScript.Shell).CreateShortcut($env:TM_LNK);$s.TargetPath=$env:TM_EXE;"
              "$s.Arguments=('\"'+$env:TM_PY+'\" --no-browser');$s.WorkingDirectory=$env:TM_DIR;$s.Save()")
        subprocess.run(["powershell", "-NoProfile", "-Command", ps], check=True, timeout=30, creationflags=SIN_VENTANA,
                       env={**os.environ, "TM_LNK": lnk, "TM_EXE": w if os.path.isfile(w) else py, "TM_PY": script, "TM_DIR": BASE})
        return T(f"Listo: Timonel se abrirá al iniciar Windows ({lnk}).", f"Done: Timonel will start with Windows ({lnk}).")
    if ES_MAC:
        plist = os.path.expanduser("~/Library/LaunchAgents/dev.timonel.plist")
        if not encender:
            if os.path.exists(plist):
                os.remove(plist)
            return T("Listo: Timonel ya no se abre al iniciar sesión.", "Done: Timonel no longer starts at login.")
        os.makedirs(os.path.dirname(plist), exist_ok=True)
        import plistlib
        with open(plist, "wb") as f:
            plistlib.dump({"Label": "dev.timonel", "ProgramArguments": [py, script, "--no-browser"],
                           "WorkingDirectory": BASE, "RunAtLoad": True}, f)
        return T(f"Listo: Timonel se abrirá al iniciar sesión ({plist}).", f"Done: Timonel will start at login ({plist}).")
    desktop = os.path.join(os.environ.get("XDG_CONFIG_HOME") or os.path.expanduser("~/.config"), "autostart", "timonel.desktop")
    if not encender:
        if os.path.exists(desktop):
            os.remove(desktop)
        return T("Listo: Timonel ya no se abre al iniciar sesión.", "Done: Timonel no longer starts at login.")
    os.makedirs(os.path.dirname(desktop), exist_ok=True)
    with open(desktop, "w", encoding="utf-8") as f:
        f.write(f'[Desktop Entry]\nType=Application\nName=Timonel\nExec="{py}" "{script}" --no-browser\n'
                f'Path={BASE}\nX-GNOME-Autostart-enabled=true\nNoDisplay=true\n')
    return T(f"Listo: Timonel se abrirá al iniciar sesión ({desktop}).", f"Done: Timonel will start at login ({desktop}).")


AYUDA_CLI = """Timonel {v}
  python timonel.py                 start and open the browser · arranca y abre el navegador
  python timonel.py --no-browser    start without opening it · arranca sin abrirlo
  python timonel.py --autostart on  start at login · abrir al iniciar sesión   (off: quitar)
  python timonel.py --version
"""


def main():
    args = sys.argv[1:]
    if "--help" in args or "-h" in args:
        return print(AYUDA_CLI.format(v=VERSION))
    if "--version" in args:
        return print(VERSION)
    if "--autostart" in args:
        valor = (args[args.index("--autostart") + 1:] or ["on"])[0].lower()
        return print(autostart(valor not in ("off", "no", "0", "false")))
    sin_navegador = "--no-browser" in args or "--sin-navegador" in args
    crear_config_si_falta()
    cfg = cargar_config()
    ENCONTRADAS.update(cargar_rutas())
    threading.Thread(target=buscar_programas, daemon=True).start()
    threading.Thread(target=monitor, daemon=True).start()
    puerto = int(cfg.get("puerto", 3000))
    intentos = 60 if "--esperar" in sys.argv else 1           # al reiniciar, espera a que el anterior suelte el puerto
    for n in range(intentos):
        try:
            srv = Servidor(("127.0.0.1", puerto), Manejador)
            break
        except OSError:
            if n == intentos - 1:
                print(T(f"El puerto {puerto} ya está ocupado: probablemente Timonel ya está abierto.", f"Port {puerto} is busy: Timonel is probably already running."))
                if "--esperar" not in sys.argv:
                    webbrowser.open(f"http://localhost:{puerto}")
                return
            time.sleep(0.25)
    SRV["s"] = srv
    url = f"http://localhost:{puerto}"
    print(T(f"Timonel en {url}  (Ctrl+C para cerrar)", f"Timonel at {url}  (Ctrl+C to quit)"))
    log.info("Timonel %s en %s", VERSION, url)
    if (cfg.get("mcp") or {}).get("activo"):
        token_mcp()
        print(T(f"MCP activo en {url}/api/mcp  (token en mcp_token.txt)", f"MCP on at {url}/api/mcp  (token in mcp_token.txt)"))
    if not sin_navegador:
        webbrowser.open(url)
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()

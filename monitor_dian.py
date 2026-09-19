#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Monitor de citas DIAN -> alerta por WhatsApp (CallMeBot).

Vigila el agendamiento de https://agendamiento.dian.gov.co/ para la
combinacion:  Persona Natural + Videoatencion + Devoluciones.

Como funciona (sin navegador, solo HTTP):
  1. GET /                              -> extrae el token anti-CSRF "anticsrf"
                                           (es de un solo uso, se pide uno nuevo
                                           para cada POST).
  2. POST /Player.aspx/ObtenerConfiguracion
                                        -> devuelve la definicion del player,
                                           de donde sale el token cifrado
                                           "ConfiguracionServicioRestEncriptado".
  3. POST /Player.aspx/ValidadorValidar
                                        -> con el manejador "manejadorEncontroColas"
                                           devuelve los tramites disponibles.
                                           Encontrado=true  -> HAY cita
                                           Encontrado=false -> no hay

Estado: guarda en state.json los tramites ya avisados para no repetir la
alerta en cada corrida mientras el cupo siga abierto.
"""

import json
import os
import re
import sys
import time
import html as htmllib
import urllib.parse
from datetime import datetime, timezone, timedelta

import requests

# ----------------------------------------------------------------------------
# Configuracion (todo se puede sobreescribir con variables de entorno)
# ----------------------------------------------------------------------------

BASE = "https://agendamiento.dian.gov.co"
RUTA_RECURSOS = "Recursos/CitasDIAN/"

# Codigos descubiertos en la propia app de la DIAN:
#   Tipo de persona : 1 = Persona Natural, 2 = Persona Juridica
#   Tipo de atencion: 1 = Presencial,      2 = Virtual (Videoatencion)
#   Categoria       : 7  = RUT y orientacion TAC
#                     11 = Conferencias o capacitaciones
#                     13 = Devoluciones           <-- el que nos interesa
#                     15 = Autogestion servicios en linea con NAF
#                     16 = Inconsistencias Grandes Contribuyentes
#                     17 = Cobranzas
#                     19 = Defensoria
TIPO_PERSONA = os.environ.get("DIAN_TIPO_PERSONA", "1")
TIPO_ATENCION = os.environ.get("DIAN_TIPO_ATENCION", "2")
CATEGORIA = os.environ.get("DIAN_CATEGORIA", "13")

# Filtro opcional por texto (ej. "Bogot"). Vacio = avisa por cualquier ciudad.
FILTRO = os.environ.get("DIAN_FILTRO", "").strip()

# CallMeBot
WA_PHONE = os.environ.get("CALLMEBOT_PHONE", "").strip()
WA_APIKEY = os.environ.get("CALLMEBOT_APIKEY", "").strip()

STATE_FILE = os.environ.get("DIAN_STATE_FILE", "state.json")

# Cuantas corridas fallidas seguidas antes de avisar que el bot esta roto
FALLOS_ANTES_DE_AVISAR = int(os.environ.get("DIAN_FALLOS_ANTES_DE_AVISAR", "6"))

TIMEOUT = 30
REINTENTOS = 3

UA = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/140.0.0.0 Safari/537.36"
)

BOGOTA = timezone(timedelta(hours=-5))


def ahora():
    return datetime.now(BOGOTA).strftime("%Y-%m-%d %H:%M:%S")


def log(msg):
    print("[{}] {}".format(ahora(), msg), flush=True)


# ----------------------------------------------------------------------------
# Cliente DIAN
# ----------------------------------------------------------------------------

class DianClient:
    def __init__(self):
        self.s = requests.Session()
        self.s.headers.update({
            "User-Agent": UA,
            "Accept-Language": "es-CO,es;q=0.9",
        })
        self._enc_token = None

    def _anticsrf(self):
        """El token es de un solo uso: se pide uno nuevo antes de cada POST."""
        r = self.s.get(BASE + "/", timeout=TIMEOUT)
        r.raise_for_status()
        m = re.search(r'name="anticsrf"[^>]*value="([^"]+)"', r.text)
        if not m:
            raise RuntimeError("No se encontro el token anticsrf en el HTML")
        return m.group(1)

    def _post(self, metodo, payload):
        headers = {
            "Content-Type": "application/json; charset=utf-8",
            "Accept": "application/json, text/javascript, */*; q=0.01",
            "X-Requested-With": "XMLHttpRequest",
            "Referer": BASE + "/",
            "RequestVerificationToken": self._anticsrf(),
            "g-recaptcha-response": "",
        }
        r = self.s.post(
            "{}/Player.aspx/{}".format(BASE, metodo),
            headers=headers,
            data=json.dumps(payload),
            timeout=TIMEOUT,
        )
        if r.status_code != 200:
            raise RuntimeError(
                "{} devolvio HTTP {}: {}".format(metodo, r.status_code, r.text[:200])
            )
        # Las page methods de ASP.NET envuelven la respuesta en {"d": "<json>"}
        outer = r.json()
        return json.loads(outer["d"]) if isinstance(outer.get("d"), str) else outer["d"]

    def token_cifrado(self):
        """ConfiguracionServicioRestEncriptado: cambia por sesion/despliegue."""
        if self._enc_token:
            return self._enc_token
        data = self._post(
            "ObtenerConfiguracion",
            {"rutaRecurso": RUTA_RECURSOS, "nombreRecurso": ""},
        )
        raw = data if isinstance(data, str) else json.dumps(data, ensure_ascii=False)
        m = re.search(
            r'"ConfiguracionServicioRestEncriptado"\s*:\s*"([^"]+)"', raw)
        if not m:
            raise RuntimeError("No se encontro ConfiguracionServicioRestEncriptado")
        self._enc_token = m.group(1)
        return self._enc_token

    def _configuracion(self):
        return {
            "ConfiguracionServicioRestEncriptado": self.token_cifrado(),
            "ControlesGeolocalizacion": [],
            "FormatoCitas": "{cita.codigo}    {cita.fecha}    {cita.Oficina.Nombre}",
            "IdPais": 1,
            "DistanciaMinima": 0,
            "TopOficinasCercanas": 0,
            "FormatoEncabezadoOficina": "",
            "FormatoOficina": "{0}",
            "ModoWebPlayer": True,
            "Archivo": {
                "Ruta": RUTA_RECURSOS,
                "FechaActualizacion": "2026-09-09T12:19:00.5196151-05:00",
            },
            "TipoPolitica": 0,
            "ObtenerEspecialidadesVirtuales": False,
            "ObtenerEspecialidadesPresenciales": False,
            "GenerarTurno": False,
        }

    def consultar_tramites(self, tipo_persona, categoria, tipo_atencion):
        """Devuelve la lista de tramites con cupo. Lista vacia = no hay cita."""
        cita = {
            "CodigoCita": None,
            "CodigoCitaModificada": None,
            "Cola": {"IdEspecialidad": "0", "Nombre": None},
            "TipoEspecialidad": {
                "IdTipoEspecialidad": int(tipo_atencion),
                "Nombre": "Virtual" if str(tipo_atencion) == "2" else "Presencial",
            },
            "Oficina": {"IdOficina": "001", "Nombre": None, "Latitud": 0, "Longitud": 0},
            "UsuarioCliente": {
                "IdTipoCliente": str(tipo_persona),
                "IdTipoDocumento": 0,
                "Nombre": None, "Apellido": None, "NumeroDocumento": None,
                "CorreoElectronico": None, "Celular": None, "Telefono": None,
                "Direccion": None, "IdCiudad": 0, "IdEstado": 0,
                "AceptaPoliticaDatos": False,
            },
            "Fecha": "2001-01-01T17:00:00.000Z",
            "Hora": "2001-01-01T17:00:00.000Z",
            "IdAgenda": 0,
            "Estado": {"IdEstado": 0, "Nombre": None},
            "Funcionario": {"NombreAMostrar": None, "Id": None},
            "Archivo": None,
            "CamposAdicionales": None,
            "EsFlujoCitaCreacion": "true",
        }
        payload = {
            "nombre": "ValidadorDatos.CitasWeb",
            "configuracion": self._configuracion(),
            "respuestaBase": {
                "Fuente": "Validador",
                "Encontrado": False,
                "DetalleAdicional": "manejadorEncontroColas",
                "ObjetosEncontrados": [
                    json.dumps(cita),
                    "Nombre",
                    str(tipo_persona),
                    str(categoria),
                    str(tipo_atencion),
                ],
                "Recurso": "CitasDIAN",
            },
        }
        data = self._post("ValidadorValidar", payload)
        if not data.get("Encontrado"):
            return []
        grupos = data.get("ObjetosEncontrados") or []
        items = grupos[0] if grupos and isinstance(grupos[0], list) else grupos
        return [limpiar(x.get("Nombre", "")) for x in items if isinstance(x, dict)]


def limpiar(txt):
    return htmllib.unescape(re.sub(r"\s+", " ", str(txt))).strip()


# ----------------------------------------------------------------------------
# WhatsApp (CallMeBot)
# ----------------------------------------------------------------------------

def enviar_whatsapp(texto):
    if not WA_PHONE or not WA_APIKEY:
        log("AVISO: faltan CALLMEBOT_PHONE / CALLMEBOT_APIKEY, no se envia nada.")
        log("Mensaje que se habria enviado:\n" + texto)
        return False
    url = "https://api.callmebot.com/whatsapp.php?" + urllib.parse.urlencode({
        "phone": WA_PHONE,
        "text": texto,
        "apikey": WA_APIKEY,
    })
    for intento in range(1, 4):
        try:
            r = requests.get(url, timeout=TIMEOUT)
            if r.status_code == 200:
                log("WhatsApp enviado.")
                return True
            log("CallMeBot HTTP {} (intento {}): {}".format(
                r.status_code, intento, r.text[:200]))
        except Exception as e:
            log("Error enviando WhatsApp (intento {}): {}".format(intento, e))
        time.sleep(3 * intento)
    return False


# ----------------------------------------------------------------------------
# Estado
# ----------------------------------------------------------------------------

def leer_estado():
    try:
        with open(STATE_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {"avisados": [], "fallos": 0, "ultima_revision": None,
                "ultimo_error": None, "aviso_fallo_enviado": False}


def guardar_estado(st):
    st["ultima_revision"] = ahora()
    with open(STATE_FILE, "w", encoding="utf-8") as f:
        json.dump(st, f, ensure_ascii=False, indent=2)


# ----------------------------------------------------------------------------
# Main
# ----------------------------------------------------------------------------

NOMBRE_ATENCION = {"1": "Presencial", "2": "Videoatencion"}
NOMBRE_CATEGORIA = {
    "7": "RUT y orientacion TAC", "11": "Conferencias o capacitaciones",
    "13": "Devoluciones", "15": "Autogestion servicios en linea con NAF",
    "16": "Inconsistencias Grandes Contribuyentes", "17": "Cobranzas",
    "19": "Defensoria",
}


def main():
    st = leer_estado()
    etiqueta = "{} / {} / {}".format(
        "Persona Natural" if TIPO_PERSONA == "1" else "Persona Juridica",
        NOMBRE_ATENCION.get(TIPO_ATENCION, TIPO_ATENCION),
        NOMBRE_CATEGORIA.get(CATEGORIA, CATEGORIA),
    )
    log("Revisando: " + etiqueta)

    tramites, error = None, None
    for intento in range(1, REINTENTOS + 1):
        try:
            tramites = DianClient().consultar_tramites(
                TIPO_PERSONA, CATEGORIA, TIPO_ATENCION)
            break
        except Exception as e:
            error = e
            log("Intento {}/{} fallo: {}".format(intento, REINTENTOS, e))
            if intento < REINTENTOS:
                time.sleep(5 * intento)

    # --- la consulta fallo -------------------------------------------------
    if tramites is None:
        st["fallos"] = st.get("fallos", 0) + 1
        st["ultimo_error"] = str(error)[:300]
        log("Consulta fallida. Fallos seguidos: {}".format(st["fallos"]))
        if st["fallos"] >= FALLOS_ANTES_DE_AVISAR and not st.get("aviso_fallo_enviado"):
            enviar_whatsapp(
                "[Bot DIAN] No he podido consultar la pagina en las ultimas {} "
                "revisiones. Puede que la DIAN haya cambiado algo o este caida.\n"
                "Ultimo error: {}".format(st["fallos"], st["ultimo_error"])
            )
            st["aviso_fallo_enviado"] = True
        guardar_estado(st)
        return 0

    st["fallos"] = 0
    st["ultimo_error"] = None
    st["aviso_fallo_enviado"] = False

    # --- filtro opcional ---------------------------------------------------
    if FILTRO:
        tramites = [t for t in tramites if FILTRO.lower() in t.lower()]

    log("Tramites con cupo: {}".format(tramites if tramites else "ninguno"))

    # --- no hay cupo -------------------------------------------------------
    if not tramites:
        if st.get("avisados"):
            log("Se cerro el cupo que ya habia avisado; limpio el estado.")
        st["avisados"] = []
        guardar_estado(st)
        return 0

    # --- hay cupo: aviso solo lo que no he avisado antes --------------------
    nuevos = [t for t in tramites if t not in st.get("avisados", [])]
    if not nuevos:
        log("Hay cupo pero ya te avise de estos tramites. No repito.")
        guardar_estado(st)
        return 0

    lineas = "\n".join("- " + t for t in tramites)
    mensaje = (
        "HAY CITA EN LA DIAN\n\n"
        "{}\n\n"
        "Tramites disponibles:\n{}\n\n"
        "Agenda ya: https://agendamiento.dian.gov.co/\n"
        "Ruta: Agendar cita > Persona Natural > Videoatencion > Devoluciones\n\n"
        "({})"
    ).format(etiqueta, lineas, ahora())

    enviar_whatsapp(mensaje)
    st["avisados"] = tramites
    guardar_estado(st)
    return 0


if __name__ == "__main__":
    sys.exit(main())

# Bot de citas DIAN → WhatsApp

Vigila el agendamiento de la DIAN y manda un WhatsApp apenas se habilite una cita de
**Persona Natural + Videoatención + Devoluciones**, solo en **Bogotá**.

Corre solo en GitHub Actions. No depende de que ningún computador esté encendido.

**Estado: funcionando.** Verificado el 19 de septiembre de 2026 con una alerta real de prueba.

---

## Ritmo adaptativo

GitHub no puede disparar más seguido que cada 5 minutos, así que el workflow corre cada 5 minutos y es el script el que decide, según el día y la hora de Bogotá, si consulta y cuántas veces dentro de la misma corrida.

Según la experiencia de una asesora que sigue estos cupos, la DIAN abre sobre todo los **viernes** (alrededor de las 9:30 am, y alguna vez a las 3 pm) y suelta cancelaciones los **martes y miércoles**.

| Ritmo | Cuándo | Cada cuánto revisa |
|---|---|---|
| ALTA | Viernes 8:30–12:30 y 14:00–17:00 | **~75 segundos** |
| MEDIA | Martes y miércoles 8:00–17:00, y viernes el resto de 7:00–19:00 | 5 minutos |
| NORMAL | Lunes y jueves 8:00–17:00 | 10 minutos |
| BAJA | Resto de días hábiles 6:00–21:00 | 20 minutos |
| MÍNIMA | Noches y fines de semana | 30 minutos |

## Prudencia con el servidor de la DIAN

El objetivo es no molestar ni terminar bloqueados:

- En la ventana más intensa son **2 peticiones por minuto**, comparable a una persona refrescando la página.
- En toda la semana son unas **3.400 peticiones**, y el 64% de las veces que se dispara el workflow ni siquiera consulta.
- Espera unos segundos al azar antes de arrancar, para no pegarle al servidor en el segundo exacto.
- Reutiliza el token dentro de la corrida: el primer sondeo cuesta 4 peticiones y los siguientes solo 2.
- Apenas encuentra cupo deja de sondear.
- Si la DIAN responde 403 o 429, corta la corrida de inmediato. Con dos cortes seguidos baja solo a ritmo mínimo, y con cinco avisa por WhatsApp.

---

## Cómo está configurado

| Qué | Valor |
|---|---|
| Tipo de persona | Persona Natural |
| Tipo de atención | Videoatención |
| Servicio | Devoluciones |
| Ciudad | Solo Bogotá |
| Aviso | WhatsApp vía CallMeBot |

Todo se cambia en `.github/workflows/monitor.yml`, en el bloque `env:`.

| Variable | Opciones |
|---|---|
| `DIAN_TIPO_PERSONA` | `1` Persona Natural · `2` Persona Jurídica |
| `DIAN_TIPO_ATENCION` | `2` Videoatención · `1` Presencial |
| `DIAN_CATEGORIA` | `13` Devoluciones · `7` RUT y orientación TAC · `11` Conferencias · `15` NAF · `16` Inconsistencias Grandes Contribuyentes · `17` Cobranzas · `19` Defensoría |
| `DIAN_FILTRO` | `Bogot` avisa solo de Bogotá (funciona con y sin tilde). Vacío avisa por cualquier ciudad |

Las ventanas horarias se cambian en la función `plan_de_sondeo()` de `monitor_dian.py`.

**Probarlo cuando sea:** desde la pestaña Actions, botón *Run workflow*. Una corrida lanzada a mano siempre consulta, sin importar la hora.

---

## Cómo son las alertas

Avisa **cada vez** que ve cupo, aunque ya haya avisado de lo mismo. Si abren a las 3:50, otro a las 3:55 y otro a las 3:57, llegan los tres mensajes. Como el bot deja de sondear apenas encuentra algo, sale como máximo un mensaje por corrida: uno cada 5 minutos mientras el cupo siga abierto.

    HAY CITA EN LA DIAN

    Persona Natural / Videoatencion / Devoluciones

    Tramites disponibles:
    - Bogota "Solicitud de devolucion y/o compensacion persona natural".

    Agenda ya: https://agendamiento.dian.gov.co/
    Ruta: Agendar cita > Persona Natural > Videoatencion > Devoluciones

Los cupos duran minutos, así que conviene entrar a agendar apenas llegue el mensaje.

---

## Lo único que puede apagar el bot

GitHub desactiva los cron en repositorios inactivos: si pasan **60 días** sin actividad del dueño, apaga el workflow y manda un correo. Los commits que hace el bot solo no cuentan.

Si llega ese correo, basta entrar a la pestaña **Actions** y reactivarlo con un clic.

Hay además un chequeo diario automático que avisa si el bot lleva más de 3 horas sin dar señales.

---

## Cómo funciona por dentro

El bot no abre un navegador ni hace clics: habla directamente con la API interna que usa la página.

1. `GET /` para sacar el token anti-CSRF `anticsrf` del HTML. Es de un solo uso, así que se pide uno nuevo antes de cada POST.
2. `POST /Player.aspx/ObtenerConfiguracion` devuelve la definición del player, de donde sale el token cifrado `ConfiguracionServicioRestEncriptado`. Se pide una sola vez por corrida.
3. `POST /Player.aspx/ValidadorValidar` con el manejador `manejadorEncontroColas` y los parámetros `[cita, "Nombre", tipoPersona, categoría, tipoAtención]`.

La respuesta trae `Encontrado: true` con la lista de trámites cuando hay cupo, y `Encontrado: false` con `manejadorNoEncontroColas` cuando no hay — que es exactamente lo que dispara el popup de *"No se encontraron especialidades relacionadas según los filtros seleccionados"* en la página.

---

## Configurar CallMeBot desde cero

Por si algún día hay que renovar la clave:

1. Agregar **+34 623 758 418** a los contactos.
2. Mandarle por WhatsApp: `I allow callmebot to send me messages`
3. Responde con una clave numérica.
4. Guardarla en **Settings → Secrets and variables → Actions** como `CALLMEBOT_APIKEY`.

El número de destino va en el secreto `CALLMEBOT_PHONE`.

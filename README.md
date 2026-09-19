# Bot de citas DIAN → WhatsApp

Vigila el agendamiento de la DIAN y manda un WhatsApp apenas se habilite una cita de
**Persona Natural + Videoatención + Devoluciones**, en cualquier ciudad.

Corre solo en GitHub Actions cada 10 minutos. No depende de que ningún computador esté encendido.

**Estado: funcionando.** Verificado el 18 de septiembre de 2026 con una alerta real de prueba.

---

## Cómo está configurado

| Qué | Valor |
|---|---|
| Tipo de persona | Persona Natural |
| Tipo de atención | Videoatención |
| Servicio | Devoluciones |
| Ciudad | Cualquiera |
| Frecuencia | Cada 10 minutos |
| Aviso | WhatsApp vía CallMeBot |

Todo eso se cambia en `.github/workflows/monitor.yml`, en el bloque `env:`.

| Variable | Opciones |
|---|---|
| `DIAN_TIPO_PERSONA` | `1` Persona Natural · `2` Persona Jurídica |
| `DIAN_TIPO_ATENCION` | `2` Videoatención · `1` Presencial |
| `DIAN_CATEGORIA` | `13` Devoluciones · `7` RUT y orientación TAC · `11` Conferencias · `15` NAF · `16` Inconsistencias Grandes Contribuyentes · `17` Cobranzas · `19` Defensoría |
| `DIAN_FILTRO` | Vacío avisa por cualquier ciudad. `Bogot` para solo Bogotá |

Para cambiar la frecuencia se edita el `cron`. El mínimo que acepta GitHub es 5 minutos (`*/5 * * * *`).

---

## Cómo son las alertas

Llega un solo mensaje por tanda de cupo, no uno cada 10 minutos:

    HAY CITA EN LA DIAN

    Persona Natural / Videoatencion / Devoluciones

    Tramites disponibles:
    - Bogota "Solicitud de devolucion y/o compensacion persona natural".
    - Cali "Solicitud de devolucion y/o compensacion persona natural".

    Agenda ya: https://agendamiento.dian.gov.co/
    Ruta: Agendar cita > Persona Natural > Videoatencion > Devoluciones

Si aparece un trámite nuevo que no se había avisado, vuelve a escribir. Cuando el cupo se cierra, el bot limpia su estado y queda listo para la próxima vez.

También avisa si lleva 6 revisiones seguidas sin poder consultar la página (una hora), por si la DIAN cambia algo y el bot deja de servir.

---

## Lo único que puede apagar el bot

GitHub desactiva los cron en repositorios inactivos: si pasan **60 días** sin actividad del dueño, apaga el workflow y manda un correo. Los commits que hace el bot solo no cuentan.

Si llega ese correo, basta entrar a la pestaña **Actions** y reactivarlo.

---

## Cómo funciona por dentro

El bot no abre un navegador ni hace clics: habla directamente con la API interna que usa la página.

1. `GET /` para sacar el token anti-CSRF `anticsrf` del HTML. Es de un solo uso, así que se pide uno nuevo antes de cada POST.
2. `POST /Player.aspx/ObtenerConfiguracion` devuelve la definición del player, de donde sale el token cifrado `ConfiguracionServicioRestEncriptado`.
3. `POST /Player.aspx/ValidadorValidar` con el manejador `manejadorEncontroColas` y los parámetros `[cita, "Nombre", tipoPersona, categoría, tipoAtención]`.

La respuesta trae `Encontrado: true` con la lista de trámites cuando hay cupo, y `Encontrado: false` con `manejadorNoEncontroColas` cuando no hay — que es exactamente lo que dispara el popup de *"No se encontraron especialidades relacionadas según los filtros seleccionados"* en la página.

Cada revisión son tres peticiones HTTP y tarda unos 9 segundos en total.

---

## Configurar CallMeBot desde cero

Por si algún día hay que renovar la clave:

1. Agregar **+34 623 758 418** a los contactos.
2. Mandarle por WhatsApp: `I allow callmebot to send me messages`
3. Responde con una clave numérica.
4. Guardarla en **Settings → Secrets and variables → Actions** como `CALLMEBOT_APIKEY`.

El número de destino va en el secreto `CALLMEBOT_PHONE`.

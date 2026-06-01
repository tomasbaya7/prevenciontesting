"""
Módulo de IA conversacional para Prevención Salud
Motor: Claude (Anthropic)
"""

import os
import json
import httpx

ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY", "")
CLAUDE_MODEL      = "claude-sonnet-4-20250514"

PLANES_INFO = """
## PLANES DE PREVENCIÓN SALUD (Sancor Seguros)

### PLAN A1
Plan de entrada con cobertura PMO completa.
- Cobertura médica básica completa según PMO
- Ideal para familias que buscan cobertura esencial
- Cobertura de maternidad y recién nacido
- Este mes con descuento especial para nuevos afiliados

### PLAN IÓN (A2CP)
Plan intermedio con cobertura nacional, copagos accesibles y prestaciones completas.
- Sistema cerrado según cartilla, con copagos
- Cobertura nacional
- Consultas en consultorio y domicilio (código verde)
- Prestaciones SUPRA PMO con cobertura amplia
- Nutrición: hasta 2 consultas por mes
- Fisio/Kinesiología: 30 sesiones con copago
- Fonoaudiología: 30 sesiones con copago
- Psicología: 50 sesiones con copago
- Psiquiatría: 12 consultas con copago
- Farmacia: 40% (vademécum alto), crónicos 70%, oncológicos/HIV 100%
- Vacunas: 100% calendario oficial
- Habitación individual en internación
- Prótesis nacionales: 100% PMO
- Prótesis importadas: 50%
- Cirugía refractiva ocular: 50% por única vez (12 meses antigüedad, desde 3 dioptrías)
- Ortodoncia: por única vez, de 5 a 35 años (12 meses antigüedad)
- Óptica: cristales, lentes de contacto y armazón por reintegro (1 cada 12 meses)
- Maternidad: 100% madre y recién nacido, anestesia peridural incluida
- Odontología general
- Hemodiálisis y trasplantes: 100%
- Asistencia al viajero nacional
- App Mi Prevención para turnos y cartilla

### PLAN A2
Plan intermedio con cartilla abierta y reintegros.
- Cartilla abierta con reintegros
- Habitaciones individuales
- Farmacia: 40% de cobertura
- Kinesiología y fisioterapia: 30 sesiones
- Fonoaudiología: 30 sesiones
- Prótesis nacionales 100% (antigüedad 12 meses)
- Ortodoncia 100% hasta 30 años por única vez
- Cirugía refractiva 50% por única vez
- Cristales bifocales y lentes de contacto
- Asistencia al viajero nacional e internacional
- Cobertura maternidad y recién nacido
- Subsidio sepelio titular o cónyuge

### PLAN A4
Plan premium con cartilla de prestigio y cirugía estética.
- Cartilla de prestadores de mayor prestigio nacional
- Amplio vademécum y reintegros superadores
- Kinesiología y fisioterapia: 40 sesiones
- Prótesis nacionales 100% hasta 35 años (antigüedad 6 meses)
- Ortodoncia 100% hasta 35 años (antigüedad 6 meses)
- Cirugía refractiva 100% por única vez
- Cirugía estética incluida
- Asistencia al viajero nacional e internacional

### PLAN A5 — Premium máximo
Todo lo del A4, más:
- Habitaciones VIP
- Prótesis importadas 100%
- Ortodoncia sin límite de edad y sin carencia
- Homeopatía y acupuntura: 12 sesiones
- Chequeos médicos ejecutivos
- Farmacia: 50% del vademécum

## INFORMACIÓN GENERAL
- Web: www.prevencionsalud.com.ar
- Superintendencia de Servicios de Salud: 0800 222 SALUD (72583)
- Red de más de 3.500 prestadores en todo el país
- App móvil para turnos y cartilla
- Planes para individuos, familias y empresas
"""

def load_agent_name() -> str:
    if os.path.exists("agent_config.json"):
        try:
            with open("agent_config.json", "r", encoding="utf-8") as f:
                return json.load(f).get("name", "")
        except: pass
    return ""

def load_extra_info() -> str:
    if os.path.exists("planes_extra.txt"):
        try:
            with open("planes_extra.txt", "r", encoding="utf-8") as f:
                return "\n\n## INFORMACIÓN ADICIONAL ACTUALIZADA\n" + f.read()
        except: pass
    return ""

# ─── FASE 1: PRE-CALIFICACIÓN (obtener DNI) ─────────────────────────────────

def build_system_prompt(contact_name: str, contact_phone: str, already_have: dict, is_inbound: bool = False) -> str:
    agent_name = load_agent_name()
    identity = f"Tu nombre es {agent_name} y trabajás en el equipo comercial de Prevención Salud." if agent_name else "Trabajás en el equipo comercial de Prevención Salud."

    has_dni = bool(already_have.get("dni"))

    context_parts = [f"Nombre del contacto: {contact_name}"]
    if has_dni:
        context_parts.append(f"DNI ya obtenido: {already_have['dni']}")
        context_parts.append("Ya tenés el DNI. Seguí la conversación preguntando algo casual sobre su situación.")
    else:
        context_parts.append("Dato que todavía necesitás obtener: DNI")

    if is_inbound:
        context_section = f"""## Contexto MUY importante
El contacto se comunicó directamente con vos — fue él quien inició la conversación. No recibió ningún mensaje tuyo previamente.

Cuando te escriba por primera vez, presentate brevemente como parte del equipo de Prevención Salud (Sancor Seguros) y ofrecé armarle una cotización personalizada con el DNI.

Ejemplos de estilo (no copiés textual, variá):
"Hola, cómo estás. Te comunicaste con Prevención Salud de Sancor Seguros. Si te interesa, te armo una cotización personalizada con tu número de DNI."
"Hola {contact_name}, cómo andás. Acá es Prevención Salud. Para prepararte una cotización personalizada necesito tu DNI, cuando puedas me lo mandás." """

        start_section = """## Cómo arrancar la conversación
Cuando el contacto te escriba (puede ser "hola", una pregunta, lo que sea):
- Saludá con calidez y presentate brevemente como parte de Prevención Salud (Sancor Seguros)
- Ofrecé armarle una cotización personalizada con el DNI
- Un mensaje corto y directo, estilo WhatsApp

Si el contacto hace una pregunta antes de dar el DNI, respondela brevemente y volvé a pedirlo."""

        dni_section = """## Al pedir el DNI
Con el DNI podés armarle una cotización personalizada sin compromiso. No inventes valores, montos ni condiciones."""

        no_fabricar = "- Inventar precios específicos, montos, valores ni cotizaciones — ni aproximados ni exactos"

    else:
        context_section = f"""## Contexto MUY importante
ANTES de que el contacto te escriba, el sistema le envió esta campaña por WhatsApp:

---
Hola {contact_name}, cómo estás?
Quería contarte que durante esta semana tenemos una oferta especial para nuevos afiliados de Prevención Salud, de 45% de descuento.
Tenemos planes para todas las necesidades, para grupos familiares, particulares, monotributistas, trabajadores en relación de dependencia, etc.
Si te interesa, puedo enviarte una cotización sin compromiso con tan solo tu número de DNI.
---

Vos NO mandaste ese mensaje vos misma, pero actuás como si fuera la continuación. Por lo tanto el contacto YA SABE:
- Que le escribiste primero ofreciendo Prevención Salud
- Que hay 45% de descuento esta semana para nuevos afiliados
- Que le pediste su DNI para armarle la cotización

Cuando el contacto te diga "hola" o cualquier mensaje breve, NO empieces de cero ni te presentes — simplemente seguís la conversación de forma natural. La meta sigue siendo conseguir el DNI."""

        start_section = f"""## Cómo arrancar la conversación
Si el contacto te escribe algo corto tipo "hola", "buenas", "sí" o similar:
- NO te presentes de nuevo
- NO repitas la oferta entera
- Respondé con algo amable y breve antes de pedir el DNI — no arranques directo con "dale, pasame tu DNI" sin ninguna calidez
- Ejemplos de buen arranque:
  "Hola, cómo estás. Sí, te escribo por lo de los planes. Pasame tu DNI y te armo la cotización con el descuento."
  "Hola {contact_name}, gracias por responder. Para prepararte la cotización necesito tu DNI, cuando puedas me lo mandás."
  "Hola, acá estoy. Para armar la cotización con el 45% de descuento, pasame tu DNI."

Si el contacto hace una pregunta antes de dar el DNI, respondela brevemente y volvé a pedirlo."""

        dni_section = """## Al pedir el DNI
Podés mencionar el 45% de descuento para nuevos afiliados — ese dato viene de la campaña y es el único número que podés usar. NO inventes otros valores, montos ni condiciones."""

        no_fabricar = "- Inventar precios específicos, montos, valores ni cotizaciones — ni aproximados ni exactos (el único dato numérico permitido es el 45% de descuento de la campaña)"

    return f"""Sos parte del equipo comercial de Prevención Salud (Sancor Seguros). {identity}

{context_section}

## Tu objetivo en esta fase
Obtener el DNI del contacto de forma natural. Punto.

## Personalidad y tono
- Hablás en español argentino (vos, te, tu)
- Sonás como un asesor comercial real que está chateando por WhatsApp, no como una publicidad
- Tono tranquilo, natural, sin exagerar ni sobreactuar — humano pero sin drama
- Oraciones cortas, directas, sin relleno
- Máximo 4 oraciones por mensaje
- EVITÁ signos de exclamación — la mayoría de los mensajes no deberían tener ninguno
- Emoji: uno cada 4-5 mensajes como mucho, no en todos
- JAMÁS mencionás que sos una IA, bot o asistente virtual
- No usés palabras como "registrar", "sistema", "procesar"
- Variá el vocabulario — no repitas siempre las mismas frases
- Escribí como escribe una persona real en WhatsApp: sin mayúsculas innecesarias
- Nada de "¡Genial!" "¡Qué bueno!" "¡Excelente!" "¡Perfecto!" — esas expresiones suenan exageradas

## Cómo sonar más humano
- Usá expresiones argentinas naturales pero con moderación: "dale", "mirá", "bueno"
- Sé directo pero sin sonar frío — un mensaje claro y tranquilo es más creíble que uno lleno de entusiasmo
- Si el contacto hace una pregunta, respondela genuinamente antes de continuar
- No arranques todos los mensajes con un halago o una expresión positiva
- Está bien ser breve. Un mensaje de 1-2 oraciones es válido
- No exageres la calidez — una respuesta tranquila y clara es más creíble que una muy efusiva

{dni_section}

{start_section}

## Si el contacto rechaza dar el DNI
Si dice explícitamente que no quiere darlo, no lo tiene a mano, o expresa cualquier rechazo directo — NO insistas y NO te despidas. Aceptalo tranquilo y pasá a preguntar otra cosa simple para mantener la charla:
- "Dale, no hay drama. Igual contame, ¿de qué ciudad sos?"
- "Bueno, después si querés me lo pasás. ¿Trabajás en relación de dependencia o por tu cuenta?"

La conversación SIGUE — el asesor humano se encarga después. Vos no cerrás la conversación nunca por tu cuenta.

Si en cambio parece que se distrajo o cambió de tema sin rechazar explícitamente, seguí la conversación con naturalidad y volvé al DNI más tarde.

## Manejo de objeciones
- "Es muy caro" / "No me alcanza": "Los precios varían bastante según el plan, hay opciones accesibles. Para darte el número concreto necesito tu DNI."
- "No me interesa" / "No gracias": "Dale, gracias por tu tiempo igual."
- Si menciona que ya tiene alguna cobertura de salud: "Igual con el DNI te puedo armar una cotización sin compromiso y ves los números, ¿te parece?"

## Distinción Sancor Seguros vs Sancor Salud
- **Prevención Salud** pertenece a **Sancor Seguros** — esa es nuestra compañía
- **Sancor Salud** es una empresa completamente distinta
- Si el contacto las confunde, aclarás brevemente: "Sancor Salud es otra empresa, nosotros somos Prevención Salud de Sancor Seguros" y seguís pidiendo el DNI

## Lo que NUNCA hacés
- {no_fabricar}
- Mencionar planes específicos con precios o características detalladas
- Opinar sobre otras coberturas, obras sociales o prepagas — ni bien ni mal
- Sugerir complementar coberturas
- Comparar con la competencia
- Dar consejos médicos o de salud
- Decir que sos una IA o bot
- Anunciar que un asesor va a contactar al cliente (eso lo decide el sistema al final)
- Hacer más de una pregunta por mensaje
- Pedir el número de celular (ya lo tenemos)
- Usar listas con guiones o formato markdown
- Si te preguntan algo que no sabés o no tiene que ver con tu objetivo: "Eso te lo va a poder responder mejor un asesor, primero necesito tu DNI para armar el caso"

{load_extra_info()}

## Contexto actual
{chr(10).join(context_parts)}

Respondé SOLO el texto del mensaje. Texto plano como WhatsApp. Nada de markdown."""


# ─── FASE 2: POST-CALIFICACIÓN (relevar info comercial) ─────────────────────

def build_post_qualification_prompt(contact_name: str, contact_phone: str, already_have: dict, post_data: dict) -> str:
    agent_name = load_agent_name()
    identity = f"Tu nombre es {agent_name} y trabajás en el equipo comercial de Prevención Salud." if agent_name else "Trabajás en el equipo comercial de Prevención Salud."

    has_situacion = bool(post_data.get("situacion_laboral"))
    has_cobertura = bool(post_data.get("cobertura_actual"))
    has_dolor = bool(post_data.get("punto_dolor"))
    has_localidad = bool(post_data.get("localidad") or already_have.get("localidad"))
    has_salud = bool(post_data.get("info_salud"))

    collected = []
    pending = []

    if has_localidad:
        collected.append(f"Localidad: {post_data.get('localidad') or already_have.get('localidad')}")
    else:
        pending.append("Ciudad donde vive")

    if has_situacion:
        collected.append(f"Situación laboral: {post_data['situacion_laboral']}")
    else:
        pending.append("Situación laboral (relación de dependencia, monotributista, o particular)")

    if has_cobertura:
        collected.append(f"Cobertura actual: {post_data['cobertura_actual']}")
    else:
        pending.append("Si tiene cobertura de salud actualmente y cuál (obra social, prepaga, o ninguna)")

    if has_dolor:
        collected.append(f"Punto de dolor: {post_data['punto_dolor']}")
    # punto_dolor es bonus — NO va a pending

    if has_salud:
        collected.append(f"Info de salud: {post_data['info_salud']}")
    else:
        pending.append("Info de salud: si toma alguna medicación, hace algún tratamiento o tiene algún tema de salud importante")

    all_complete = has_cobertura and has_localidad and has_salud and has_situacion

    context_info = ""
    if collected:
        context_info += "Info ya relevada:\n" + "\n".join(f"- {c}" for c in collected) + "\n\n"
    if pending:
        context_info += "Info pendiente de relevar:\n" + "\n".join(f"- {p}" for p in pending) + "\n\n"
    if all_complete:
        context_info += """YA TENÉS TODA LA INFO. Cerrá la conversación con un mensaje de cierre que:
1. Sea MUY corto — 1 oración, máximo 2
2. Diga que le pasa el caso a un asesor que lo contacta por este mismo WhatsApp en minutos
3. NUNCA menciones "mañana", "después", ni ninguna fecha o día. El asesor contacta EN MOMENTOS, en minutos
4. No ofrezcas preparar cotización vos mismo ni prometas enviar opciones — eso lo hace el asesor
5. No hagas preguntas, no pidas confirmación

Ejemplos de estilo (no copies textual, variá):
- "Dale, con eso ya tengo lo que necesito. Un asesor te va a estar escribiendo por acá en unos minutos."
- "Perfecto. Dame unos minutos que le paso tu caso a un asesor y te contacta por acá."
- "Listo, ya tengo todo. En momentos te escribe un asesor por este mismo WhatsApp."

IMPORTANTE: Este es el último mensaje del bot. No generés ningún mensaje más después de este cierre."""

    return f"""Sos parte del equipo comercial de Prevención Salud (Sancor Seguros). {identity}

## Tu única misión
Conseguir 4 datos del contacto {contact_name}, en este orden de prioridad:
1. Ciudad donde vive
2. Situación laboral (relación de dependencia, monotributista o particular)
3. Cobertura actual de salud (obra social, prepaga o ninguna)
4. Información de salud relevante: medicación que toma, tratamientos, condiciones de salud

PUNTO. Eso es TODO lo que tenés que hacer. Nada más.

## Reglas inviolables
- Hacés UNA pregunta por mensaje. Una sola. Nunca dos.
- Cada pregunta es de la lista de 4 datos. Nada que no esté en la lista.
- Si el contacto se va por las ramas, te enfocás en volver a la pregunta pendiente. Nunca lo seguís en su desvío.
- Si el contacto rechaza contestar UN dato, no insistís en ese, pasás al siguiente. Pero igual la pregunta la tenés que haber hecho.
- NO PODÉS cerrar la conversación hasta haber PREGUNTADO los 4 datos.

## Cómo preguntar
Podés usar hasta 4 oraciones por mensaje. No seas tan escueto que suene frío — podés reconocer brevemente lo que dijo el contacto antes de preguntar. Pero tampoco te explayes de más.

Ejemplos de tono correcto (no copies textual, variá):
"Ah, mirá. Y vos de qué ciudad sos?"
"Buenísimo. Te pregunto: ¿trabajás en relación de dependencia o sos monotributista? ¿O quizás por tu cuenta?"
"Ah, y hoy tenés alguna cobertura de salud o estás sin nada?"
"Te consulto una cosita más: ¿tomás alguna medicación o estás haciendo algún tratamiento? ¿Algún tema de salud que me quieras comentar?"

## PROHIBIDO ABSOLUTAMENTE
- Hablar de planes, precios, valores, cotizaciones, costos, descuentos, promociones
- Comparar con otras coberturas, obras sociales o prepagas
- Opinar sobre la cobertura actual del contacto
- Sugerir nada (complementar, cambiar, mejorar)
- Dar información médica o de salud
- Responder consultas técnicas sobre el plan
- Decir que sos IA, bot o asistente
- Anunciar que viene un asesor
- Hacer recomendaciones de cualquier tipo
- Inventar info que no tenés
- Hacer preguntas fuera de la lista de 4
- Al preguntar por cobertura, usá únicamente "¿tenés alguna cobertura actualmente?" o "¿estás sin nada?". Nunca menciones tipos de planes ni productos ("plan integral", "plan individual", etc.)

## Si te preguntan algo prohibido
Respondés con UNA línea, sin explicaciones, y volvés a la pregunta pendiente. Ejemplos:
- "Esa info te la pasa el asesor en un rato. Te consulto, [siguiente pregunta de la lista]"
- "Eso lo charlás directo con el asesor. Una cosita más: [siguiente pregunta]"
- "Te lo confirmamos después. [siguiente pregunta]"

## Tono
- Español argentino (vos, te, tu)
- WhatsApp natural, directo — con calidez genuina pero sin exagerar
- Máximo 4 oraciones por mensaje
- Sin signos de exclamación en la mayoría de los mensajes
- Emoji: uno cada 4-5 mensajes como mucho
- JAMÁS markdown, viñetas, listas
- Hablás como un asesor real chateando, no como un bot entusiasta

## Distinción importante — Sancor Seguros vs Sancor Salud
- Prevención Salud pertenece a Sancor Seguros — esa es nuestra compañía
- Sancor Salud es competencia, otra empresa completamente distinta
- Si el contacto los confunde, aclarás brevemente y seguís con la pregunta pendiente

{context_info}
{load_extra_info()}

Respondé SOLO el texto del mensaje. Texto plano como WhatsApp. Nada de markdown."""


# ─── FUNCIÓN PRINCIPAL ───────────────────────────────────────────────────────

async def get_ai_response(
    conversation_history: list,
    contact_name: str,
    contact_phone: str,
    already_have: dict,
    phase: str = "pre",
    post_data: dict = None,
    campaign_id: int = None
) -> dict:
    """
    phase="pre"  → recolectar DNI (calificación)
    phase="post" → relevar info comercial post-calificación
    """
    if post_data is None:
        post_data = {}

    if phase == "post":
        system_prompt = build_post_qualification_prompt(contact_name, contact_phone, already_have, post_data)
    else:
        system_prompt = build_system_prompt(contact_name, contact_phone, already_have, is_inbound=(campaign_id is None))

    headers = {
        "x-api-key": ANTHROPIC_API_KEY,
        "anthropic-version": "2023-06-01",
        "content-type": "application/json"
    }
    payload = {
        "model": CLAUDE_MODEL,
        "max_tokens": 300,
        "system": system_prompt,
        "messages": conversation_history
    }

    try:
        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.post(
                "https://api.anthropic.com/v1/messages",
                headers=headers, json=payload
            )
            data = resp.json()
            if resp.status_code != 200:
                import sys
                print(f"Claude API error {resp.status_code}: {data}", file=sys.stderr, flush=True)
                raise Exception(f"API returned {resp.status_code}: {data.get('error', {}).get('message', str(data))}")
            reply_text = data["content"][0]["text"]
    except Exception as e:
        import sys
        print(f"Error API Claude: {e}", file=sys.stderr, flush=True)
        first = contact_name.split()[0]
        reply_text = f"¡Hola {first}! Gracias por escribirnos. Ahora mismo te paso toda la información 😊"

    if phase == "pre":
        extracted = await extract_data_from_conversation(conversation_history, already_have)
        all_data  = {**already_have, **extracted}
        qualified = bool(all_data.get("dni"))
        dni_refused = bool(extracted.get("dni_refused")) or bool(already_have.get("dni_refused"))

        return {
            "reply":      reply_text,
            "extracted":  extracted,
            "qualified":  qualified,
            "dni_refused": dni_refused,
            "all_data":   all_data
        }
    else:
        post_extracted = await extract_post_data(conversation_history, post_data)
        merged_post = {**post_data, **post_extracted}
        conversation_complete = bool(
            merged_post.get("cobertura_actual") and
            (merged_post.get("localidad") or already_have.get("localidad")) and
            merged_post.get("info_salud") and
            merged_post.get("situacion_laboral")
        )

        return {
            "reply":               reply_text,
            "post_extracted":      post_extracted,
            "conversation_complete": conversation_complete,
            "post_data":           merged_post
        }


# ─── EXTRACCIÓN FASE 1: DNI ─────────────────────────────────────────────────

async def extract_data_from_conversation(conversation_history: list, already_have: dict) -> dict:
    if not ANTHROPIC_API_KEY:
        return {}

    user_messages = [m["content"] for m in conversation_history if m["role"] == "user"]
    if not user_messages:
        return {}

    text_to_analyze = " | ".join(user_messages[-6:])

    extraction_prompt = f"""Analizá esta conversación de WhatsApp y extraé los datos si aparecen EXPLÍCITAMENTE escritos por el usuario.

Conversación: "{text_to_analyze}"

Datos ya conocidos (NO los incluyas): {json.dumps(already_have, ensure_ascii=False)}

Respondé ÚNICAMENTE con JSON válido, sin texto adicional:
{{"dni": "solo números sin puntos, o null", "dni_refused": true_o_false}}

Reglas para DNI:
- Solo incluí el DNI si aparece EXPLÍCITAMENTE escrito por el usuario
- DNI argentino: 7-8 dígitos. Nunca menos, nunca más.
- Si tiene 4-6 dígitos o 9+ dígitos NO es DNI, poné null
- No inferras nada que no esté escrito

Reglas para dni_refused:
- true SI el usuario expresó claramente que no quiere darlo, no lo tiene a mano, o prefiere no compartirlo
- Ejemplos de rechazo: "no quiero", "no te lo doy", "no lo tengo", "más tarde", "después", "prefiero no", "no me siento cómodo"
- false en cualquier otro caso (incluso si simplemente cambió de tema)

Si no hay nada, dni=null y dni_refused=false."""

    headers = {
        "x-api-key": ANTHROPIC_API_KEY,
        "anthropic-version": "2023-06-01",
        "content-type": "application/json"
    }
    payload = {
        "model": CLAUDE_MODEL,
        "max_tokens": 80,
        "messages": [{"role": "user", "content": extraction_prompt}]
    }

    try:
        async with httpx.AsyncClient(timeout=15) as client:
            resp = await client.post(
                "https://api.anthropic.com/v1/messages",
                headers=headers, json=payload
            )
            data = resp.json()
            text = data["content"][0]["text"].strip()
            text = text.replace("```json", "").replace("```", "").strip()
            extracted = json.loads(text)
            result = {}
            # DNI — validar longitud 7-8 dígitos
            dni_val = extracted.get("dni")
            if dni_val and dni_val != "null" and not already_have.get("dni"):
                dni_clean = "".join(c for c in str(dni_val) if c.isdigit())
                if 7 <= len(dni_clean) <= 8:
                    result["dni"] = dni_clean
                else:
                    print(f"[DNI INVÁLIDO] descartado: {dni_val} (len={len(dni_clean)})", flush=True)
            # dni_refused
            if extracted.get("dni_refused") is True:
                result["dni_refused"] = True
            return result
    except Exception as e:
        print(f"Error extracción: {e}", flush=True)
        return {}


# ─── EXTRACCIÓN FASE 2: DATOS COMERCIALES ───────────────────────────────────

async def extract_post_data(conversation_history: list, already_post: dict) -> dict:
    if not ANTHROPIC_API_KEY:
        return {}

    user_messages = [m["content"] for m in conversation_history if m["role"] == "user"]
    if not user_messages:
        return {}

    text_to_analyze = " | ".join(user_messages[-10:])

    extraction_prompt = f"""Analizá esta conversación de WhatsApp y extraé la información comercial que el usuario haya mencionado EXPLÍCITAMENTE.

Conversación: "{text_to_analyze}"

Datos ya conocidos (NO los repitas): {json.dumps(already_post, ensure_ascii=False)}

Respondé ÚNICAMENTE con JSON válido, sin texto adicional:
{{
  "localidad": "ciudad donde vive, o null",
  "situacion_laboral": "relación de dependencia / monotributista / particular / jubilado / otro texto que diga el usuario. Si el usuario rechazó contestar o evitó la pregunta, poné 'No quiso informar'. Solo null si el tema NUNCA se tocó en la conversación",
  "cobertura_actual": "nombre de la obra social o prepaga que tiene, o 'no tiene' si dice que no tiene, o null si no mencionó el tema",
  "punto_dolor": "resumen breve de qué problema tiene o qué quiere mejorar, o null si no lo mencionó",
  "info_salud": "resumen muy conciso de medicaciones, tratamientos o temas de salud mencionados. Si el usuario dijo que no tiene nada, no toma medicación o está sano, poné 'Sin patologías declaradas'. Solo null si el tema NUNCA se tocó en la conversación"
}}

Reglas:
- Solo incluí info EXPLÍCITAMENTE dicha por el usuario
- Para punto_dolor, resumí en 1-2 oraciones lo que el usuario expresó
- No inferras nada que no esté escrito
- Si no hay datos nuevos, todo null"""

    headers = {
        "x-api-key": ANTHROPIC_API_KEY,
        "anthropic-version": "2023-06-01",
        "content-type": "application/json"
    }
    payload = {
        "model": CLAUDE_MODEL,
        "max_tokens": 200,
        "messages": [{"role": "user", "content": extraction_prompt}]
    }

    try:
        async with httpx.AsyncClient(timeout=15) as client:
            resp = await client.post(
                "https://api.anthropic.com/v1/messages",
                headers=headers, json=payload
            )
            data = resp.json()
            text = data["content"][0]["text"].strip()
            text = text.replace("```json", "").replace("```", "").strip()
            extracted = json.loads(text)
            return {
                k: v for k, v in extracted.items()
                if v and v != "null" and not already_post.get(k)
            }
    except Exception as e:
        print(f"Error extracción post: {e}", flush=True)
        return {}


# ─── GENERAR RESUMEN DEL CASO ────────────────────────────────────────────────

async def generate_case_summary(contact_name: str, dni: str, post_data: dict) -> str:
    """Genera un resumen estructurado del caso para enviar al asesor."""
    localidad = post_data.get("localidad") or "No contestó"
    situacion = post_data.get("situacion_laboral") or "No contestó"
    cobertura = post_data.get("cobertura_actual") or "No contestó"
    salud     = post_data.get("info_salud") or "No contestó"
    dni_str   = dni or "No contestó"
    return (
        f"📋 Resumen del caso — {contact_name}\n\n"
        f"🪪 DNI: {dni_str}\n"
        f"📍 Localidad: {localidad}\n"
        f"💼 Situación laboral: {situacion}\n"
        f"🏥 Cobertura actual: {cobertura}\n"
        f"💊 Info de salud: {salud}"
    )


# ─── GENERAR MENSAJE DE RECORDATORIO ─────────────────────────────────────────

async def generate_reminder_message(contact_name: str, conversation_history: list) -> str:
    """Genera un mensaje conversacional de follow-up para mantener la ventana de 24hs."""
    if not ANTHROPIC_API_KEY:
        first = contact_name.split()[0]
        return f"Hola {first}! ¿Pudiste ver la info que te mandamos? Cualquier duda estoy por acá 😊"

    agent_name = load_agent_name()
    first = contact_name.split()[0]

    system_prompt = f"""Sos parte del equipo comercial de Prevención Salud. {"Tu nombre es " + agent_name + "." if agent_name else ""}

Generá un mensaje corto y natural de follow-up para {first} por WhatsApp. El objetivo es mantener la conversación activa.

Reglas:
- Máximo 2 oraciones
- Tono tranquilo, argentino, profesional — como un asesor real
- No seas insistente ni vendedor agresivo
- Variá el mensaje — no siempre digas lo mismo
- Evitá signos de exclamación
- Sin emoji o como mucho uno
- JAMÁS mencionés que sos IA o bot
- Texto plano, sin markdown

Ejemplos de estilo (no repitas textual):
- "Hola {first}, pudiste ver lo de la cobertura? Cualquier duda avisame"
- "{first}, te comento que este mes hay bonificación en el primer mes. Si te interesa chiflá"
- "Hola, cómo va? Quedo a disposición si necesitás algo sobre los planes"
"""

    headers = {
        "x-api-key": ANTHROPIC_API_KEY,
        "anthropic-version": "2023-06-01",
        "content-type": "application/json"
    }

    recent = conversation_history[-4:] if len(conversation_history) > 4 else conversation_history
    messages = recent + [{"role": "user", "content": "Generá el mensaje de follow-up ahora."}]

    payload = {
        "model": CLAUDE_MODEL,
        "max_tokens": 100,
        "system": system_prompt,
        "messages": messages
    }

    try:
        async with httpx.AsyncClient(timeout=15) as client:
            resp = await client.post(
                "https://api.anthropic.com/v1/messages",
                headers=headers, json=payload
            )
            data = resp.json()
            return data["content"][0]["text"].strip()
    except Exception as e:
        print(f"Error generando reminder: {e}", flush=True)
        return f"Hola {first}! ¿Pudiste ver la info? Cualquier duda estoy por acá 😊"


# ─── HELPERS ─────────────────────────────────────────────────────────────────

async def generate_first_message(contact_name: str) -> str:
    agent_name = load_agent_name()
    first = contact_name.split()[0]
    intro = f"Hola {first}, soy {agent_name} de Prevención Salud" if agent_name else f"Hola {first}"
    return (
        f"{intro}. "
        f"Este mes hay descuentos en planes de salud. "
        f"Si te interesa te armo una cotización, pasame tu DNI."
    )

def save_extra_info(text: str):
    with open("planes_extra.txt", "w", encoding="utf-8") as f:
        f.write(text)

def get_extra_info() -> str:
    if os.path.exists("planes_extra.txt"):
        try:
            with open("planes_extra.txt", "r", encoding="utf-8") as f:
                return f.read()
        except: pass
    return ""

def save_agent_config(name: str):
    with open("agent_config.json", "w", encoding="utf-8") as f:
        json.dump({"name": name}, f, ensure_ascii=False)

def get_agent_config() -> dict:
    if os.path.exists("agent_config.json"):
        try:
            with open("agent_config.json", "r", encoding="utf-8") as f:
                return json.load(f)
        except: pass
    return {"name": ""}

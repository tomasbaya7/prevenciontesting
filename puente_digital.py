"""
Automatización de Puente Digital 2.0 — Prevención Salud (Sancor Seguros)
"""

import os
import sys
import asyncio
from typing import Optional

PUENTE_URL      = "https://puentedigital.prevencionsalud.com.ar"
PUENTE_USER     = os.getenv("PUENTE_USER", "")
PUENTE_PASSWORD = os.getenv("PUENTE_PASSWORD", "")

def log(msg):
    print(f"PUENTE: {msg}", file=sys.stderr, flush=True)

async def cargar_contacto_puente_digital(
    dni: str,
    localidad: str,
    codigo_postal: str = "",
    codigo_area: str = "",
    celular: str = "",
    email: str = "",
    demo_mode: bool = True,
    username: str = "",
    password: str = ""
) -> dict:
    # Usar credenciales pasadas, o fallback a env vars
    effective_user = username or PUENTE_USER
    effective_pass = password or PUENTE_PASSWORD

    if demo_mode or not effective_user or not effective_pass:
        await asyncio.sleep(2)
        return {"success": True, "message": f"[DEMO] DNI: {dni}", "demo": True}

    try:
        from playwright.async_api import async_playwright

        async with async_playwright() as p:
            browser = await p.chromium.launch(headless=True)
            page    = await browser.new_page()

            # ── LOGIN PASO 1: Email ──
            log("login paso 1: email")
            await page.goto(PUENTE_URL)
            await page.wait_for_load_state('networkidle', timeout=15000)
            inputs = await page.query_selector_all('input')
            await inputs[1].fill(effective_user)
            await asyncio.sleep(0.5)
            # Cerrar popup de ayuda si existe
            try:
                close_btn = page.locator('button:has-text("X")').first
                if await close_btn.is_visible():
                    await close_btn.click()
                    await asyncio.sleep(0.5)
            except: pass
            await page.locator('button:has-text("Continuar")').last.click()
            await asyncio.sleep(2)

            # ── LOGIN PASO 2: Contraseña ──
            log("login paso 2: password")
            await page.wait_for_selector('input[type="password"]', timeout=15000)
            await page.fill('input[type="password"]', effective_pass)
            await asyncio.sleep(0.5)
            try:
                close_btn2 = page.locator('button:has-text("X")').first
                if await close_btn2.is_visible():
                    await close_btn2.click()
                    await asyncio.sleep(0.5)
            except: pass
            await page.locator('button:has-text("Continuar")').last.click()
            await asyncio.sleep(3)

            # ── HOME → NUEVO CONTACTO ──
            log("navegando a nuevo contacto")
            await page.wait_for_selector('text=Nuevo contacto', timeout=15000)
            await page.click('text=Nuevo contacto')
            await asyncio.sleep(1)

            # ── FORMULARIO ──
            await page.wait_for_selector('text=Contacto nuevo', timeout=10000)
            log("formulario cargado")

            # 1. Toggle "Ingresar nro. de documento" → activar si no está
            switch = page.locator('#switchDocumentContact')
            if not await switch.is_checked():
                log("activando switch DNI")
                await switch.click()
                await asyncio.sleep(0.5)

            # 2. Tipo de documento → DNI via Select2
            log("seleccionando tipo DNI via Select2")
            dni_selected = False
            for attempt in range(3):
                try:
                    await page.locator('#select2-contactDocumentType-container').click()
                    await asyncio.sleep(0.8)
                    # Esperar a que aparezcan las opciones
                    await page.wait_for_selector('.select2-results__option', timeout=5000)
                    await page.locator('.select2-results__option:has-text("DNI")').first.click()
                    await asyncio.sleep(0.5)
                    # Verificar que quedó seleccionado
                    selected_text = await page.locator('#select2-contactDocumentType-container').inner_text()
                    if "DNI" in selected_text:
                        log(f"tipo DNI seleccionado OK (intento {attempt+1})")
                        dni_selected = True
                        break
                    else:
                        log(f"tipo DNI no quedó seleccionado (intento {attempt+1}), reintentando")
                except Exception as e:
                    log(f"tipo DNI Select2 intento {attempt+1} error: {e}")
                await asyncio.sleep(0.5)

            if not dni_selected:
                # Fallback: setear via JS directamente en el select subyacente
                log("fallback: seteando tipo DNI via JS")
                await page.evaluate("""() => {
                    var sel = document.querySelector('select[name="contactDocumentType"], #contactDocumentType, select[id*="DocumentType"]');
                    if (!sel) {
                        // buscar por todas las opciones disponibles
                        var selects = document.querySelectorAll('select');
                        for (var s of selects) {
                            for (var o of s.options) {
                                if (o.text.trim().toUpperCase() === 'DNI') {
                                    sel = s;
                                    break;
                                }
                            }
                            if (sel) break;
                        }
                    }
                    if (sel) {
                        for (var i = 0; i < sel.options.length; i++) {
                            if (sel.options[i].text.trim().toUpperCase() === 'DNI') {
                                sel.selectedIndex = i;
                                sel.dispatchEvent(new Event('change', {bubbles: true}));
                                break;
                            }
                        }
                        // Actualizar Select2 si está disponible
                        if (window.$ && $(sel).data('select2')) {
                            $(sel).trigger('change');
                        }
                    }
                }""")
                await asyncio.sleep(0.5)
                # Verificar resultado del fallback
                selected_text = await page.locator('#select2-contactDocumentType-container').inner_text()
                log(f"tipo DNI tras fallback JS: '{selected_text}'")

            # 3. Nro de documento (input type="number" id="contactDocumentNumber")
            dni_clean = dni.replace(".", "").replace(" ", "")
            log(f"llenando DNI: {dni_clean}")
            await page.fill('#contactDocumentNumber', dni_clean)
            await asyncio.sleep(0.3)

            # 4. Buscar
            log("click buscar")
            await page.locator('#formContactDocument button:has-text("Buscar")').click()
            await asyncio.sleep(4)
            log(f"post-buscar url={page.url}")

            # Esperar a que la sección de datos adicionales se muestre
            # (el form contactAdditionalInformationForm se hace visible tras buscar)
            try:
                await page.wait_for_selector('#contactAdditionalInformationForm:visible', timeout=10000)
                log("formulario adicional visible")
            except:
                log("formulario adicional no apareció, intentando continuar")

            # 5. Tipo de contacto → Individual
            log("seleccionando tipo contacto Individual")
            try:
                await page.locator('input[type="radio"][value="Individual"]').click(timeout=3000)
            except:
                try:
                    await page.locator('label:has-text("Individual")').click(timeout=3000)
                except Exception as e:
                    log(f"tipo contacto skip: {e}")
            await asyncio.sleep(0.3)

            # 6. Localidad (Select2, id="locality")
            log(f"seleccionando localidad cp={codigo_postal}")
            try:
                await page.locator('#select2-locality-container').click()
                await asyncio.sleep(0.5)
                # Buscar por código postal
                search_term = codigo_postal if codigo_postal else "2000"
                await page.keyboard.type(search_term, delay=50)
                await asyncio.sleep(2)
                # Seleccionar primera opción
                option = page.locator('.select2-results__option').first
                if await option.count() > 0:
                    option_text = await option.inner_text()
                    log(f"localidad opción: {option_text}")
                    await option.click()
                else:
                    log("no se encontraron opciones de localidad")
            except Exception as e:
                log(f"localidad error: {e}")
            await asyncio.sleep(0.5)

            # 6. Código de área (input type="number" id="areaCode")
            #    El formulario ya muestra "0" como prefijo, poner solo el código sin 0
            codigo_area_clean = codigo_area.lstrip("0")
            log(f"llenando código de área: {codigo_area_clean}")
            await page.fill('#areaCode', codigo_area_clean)
            # Disparar validación
            await page.locator('#areaCode').dispatch_event('input')
            await page.locator('#areaCode').dispatch_event('change')
            await asyncio.sleep(0.3)

            # 7. Celular (input type="number" id="phoneNumber")
            #    El formulario muestra "15" como prefijo, poner el resto
            celular_clean = celular.lstrip("15") if celular.startswith("15") else celular
            log(f"llenando celular: {celular_clean}")
            await page.fill('#phoneNumber', celular_clean)
            await page.locator('#phoneNumber').dispatch_event('input')
            await page.locator('#phoneNumber').dispatch_event('change')
            await asyncio.sleep(0.3)

            # 8. Email (opcional, id="email")
            if email:
                log(f"llenando email: {email}")
                await page.fill('#email', email)
                await asyncio.sleep(0.2)

            # 9. Disparar validación completa del formulario vía JS
            log("disparando validación del formulario")
            await page.evaluate("""() => {
                // Disparar eventos en todos los campos requeridos
                ['#areaCode', '#phoneNumber', '#contactDocumentNumber'].forEach(sel => {
                    var el = document.querySelector(sel);
                    if (el) {
                        el.dispatchEvent(new Event('input', {bubbles: true}));
                        el.dispatchEvent(new Event('change', {bubbles: true}));
                        el.dispatchEvent(new Event('blur', {bubbles: true}));
                    }
                });
                // Intentar revalidar con FormValidation si existe
                var form = document.getElementById('contactAdditionalInformationForm');
                if (form && $(form).data('formValidation')) {
                    $(form).data('formValidation').validate();
                }
                // También probar con bootstrapValidator
                if (form && $(form).data('bootstrapValidator')) {
                    $(form).data('bootstrapValidator').validate();
                }
            }""")
            await asyncio.sleep(1)

            # 10. Verificar estado del botón Guardar
            guardar_btn = page.locator('#contactAdditionalInformationForm button:has-text("Guardar")')
            is_enabled = await guardar_btn.is_enabled()
            log(f"botón Guardar enabled={is_enabled}")

            if not is_enabled:
                # Último recurso: habilitar por JS y clickear
                log("Guardar deshabilitado — habilitando por JS")
                await page.evaluate("""() => {
                    var form = document.getElementById('contactAdditionalInformationForm');
                    var btn = form.querySelector('button');
                    if (btn) {
                        btn.removeAttribute('disabled');
                        btn.disabled = false;
                    }
                }""")
                await asyncio.sleep(0.5)

            # 11. Screenshot en base64 para debug
            import base64
            screenshot_bytes = await page.screenshot(full_page=True)
            screenshot_b64 = base64.b64encode(screenshot_bytes).decode()
            log(f"SCREENSHOT_B64:{screenshot_b64}")

            # Click Guardar
            log("click Guardar")
            await guardar_btn.click(force=True)

            # 12. Verificar resultado — esperar modal de éxito
            try:
                await page.wait_for_selector('#saveSuccessfulContactModal', state='visible', timeout=8000)
                log("¡Modal de éxito visible! Contacto guardado.")
                await page.locator('#saveSuccessfulContactModal button:has-text("No, volver")').click()
                await asyncio.sleep(1)
                await browser.close()
                return {"success": True, "message": f"Contacto cargado exitosamente — DNI: {dni_clean}"}
            except:
                pass

            # Si seguimos en la misma página, verificar errores
            final_url = page.url
            log(f"post-guardar url={final_url}")

            # Verificar si hay mensajes de validación visibles
            errors = await page.evaluate("""() => {
                var helps = document.querySelectorAll('#contactAdditionalInformationForm .help-block');
                var visible = [];
                helps.forEach(h => {
                    if (h.offsetParent !== null && h.style.display !== 'none') {
                        visible.push(h.textContent.trim());
                    }
                });
                return visible;
            }""")
            if errors:
                log(f"errores de validación: {errors}")

            # Listar estado de campos para debug
            field_states = await page.evaluate("""() => {
                var fields = {};
                ['#contactDocumentNumber', '#areaCode', '#phoneNumber', '#email'].forEach(sel => {
                    var el = document.querySelector(sel);
                    fields[sel] = el ? el.value : 'NOT_FOUND';
                });
                var loc = document.querySelector('#select2-locality-container');
                fields['locality'] = loc ? loc.textContent.trim() : 'NOT_FOUND';
                var guardar = document.querySelector('#contactAdditionalInformationForm button');
                fields['guardar_disabled'] = guardar ? guardar.disabled : 'NOT_FOUND';
                return fields;
            }""")
            log(f"estado campos: {field_states}")

            await browser.close()

            if "NewContact" in final_url:
                return {"success": False, "message": f"Formulario no se guardó. Errores: {errors}. Campos: {field_states}"}
            else:
                return {"success": True, "message": f"Contacto cargado — DNI: {dni_clean}"}

    except Exception as e:
        log(f"ERROR: {e}")
        return {"success": False, "message": f"Error al cargar en Puente Digital: {str(e)}"}

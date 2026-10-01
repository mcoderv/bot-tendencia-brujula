"""
subscriptions.py
Lógica de negocio para el sistema de suscripciones VIP.
Maneja trials, pagos, recordatorios y expulsiones.
v1.1: Restricción de 1 solo trial por usuario (evita multicuentas).
      Mensajes al usuario en inglés (cordiales y asertivos).
"""
import time
from app.database import (
    get_subscriber, register_subscriber, activate_trial, activate_paid,
    get_pending_activations, get_expiring_soon, get_expired, mark_invoice_sent, update_subscriber_status
)
from app.telegram import (
    send_welcome_message, send_payment_success_message, 
    send_invoice_message, send_expiration_warning, ban_chat_member
)
from app.config import TRIAL_DAYS, SUBSCRIPTION_DAYS, SUBSCRIPTION_PRICE, VIP_CHANNEL_ID, PENDING_ACTIVATION_HOURS

async def handle_start_command(user_id: int, username: str):
    """
    Registra o reactiva la prueba de 7 días.
    Si el usuario ya tuvo trial antes (expired/banned), le envía factura directa.
    """
    sub = await get_subscriber(user_id)
    now = int(time.time())
    
    if not sub:
        # Usuario completamente nuevo → 7 días gratis
        await register_subscriber(user_id, username, now)
        await activate_trial(user_id)
        await send_welcome_message(user_id, username, is_new=True)
        
    elif sub["status"] in ("expired", "banned"):
        # Ya tuvo trial antes y no pagó (o fue baneado) → NO dar otro trial
        # Enviar factura directa para renovar
        print(f"💳 Usuario {username} ya tuvo trial. Enviando factura directa.")
        success = await send_invoice_message(user_id, SUBSCRIPTION_PRICE)
        if success:
            await mark_invoice_sent(user_id)
        else:
            await send_expiration_warning(user_id)
            
    elif sub["status"] == "pending":
        # Usuario que entró al canal pero no había activado → activar trial
        await activate_trial(user_id)
        await send_welcome_message(user_id, username, is_new=True)
        
    else:
        # Ya está en trial o active → informar días restantes
        end_date = sub.get("subscription_end") or (sub.get("trial_start", now) + (TRIAL_DAYS * 86400))
        days_left = max(0, (end_date - now) // 86400)
        await send_welcome_message(user_id, username, is_new=False, days_left=int(days_left))

async def handle_successful_payment(user_id: int):
    """Procesa un pago exitoso y extiende la suscripción 30 días."""
    await activate_paid(user_id)
    await send_payment_success_message(user_id)

async def run_subscription_checks():
    """
    Revisa suscripciones por expirar, vencidas y usuarios inactivos.
    Esta función debe llamarse periódicamente (ej. desde el endpoint /tick).
    """
    print("🔄 Revisando suscripciones VIP...")
    
    # 1. Enviar recordatorios y facturas a los que expiran en < 24h
    expiring = await get_expiring_soon(hours=24)
    for user in expiring:
        print(f"  📩 Enviando recordatorio de pago a {user['username']} ({user['user_id']})")
        success = await send_invoice_message(user["user_id"], SUBSCRIPTION_PRICE)
        if success:
            await mark_invoice_sent(user["user_id"])
        else:
            # Fallback a mensaje de texto si la factura falla
            await send_expiration_warning(user["user_id"])

    # 2. Expulsar a los que ya vencieron su suscripción o trial
    expired = await get_expired()
    for user in expired:
        print(f"  🚫 Expulsando usuario vencido: {user['username']} ({user['user_id']})")
        await ban_chat_member(VIP_CHANNEL_ID, user["user_id"])
        await update_subscriber_status(user["user_id"], "expired")
        
    # 3. Expulsar a los que entraron al canal pero no activaron el bot en 24h
    pending = await get_pending_activations(hours=PENDING_ACTIVATION_HOURS)
    for user in pending:
        print(f"  🚫 Expulsando usuario inactivo (no activó trial): {user['username']} ({user['user_id']})")
        await ban_chat_member(VIP_CHANNEL_ID, user["user_id"])
        await update_subscriber_status(user["user_id"], "banned")
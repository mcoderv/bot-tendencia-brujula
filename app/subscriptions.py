"""
subscriptions.py v1.2 FINAL: Trigger semanal de reporte + sin cambios en VIP.
"""
import time
import datetime
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
    sub = await get_subscriber(user_id)
    now = int(time.time())

    if not sub:
        await register_subscriber(user_id, username, now)
        await activate_trial(user_id)
        await send_welcome_message(user_id, username, is_new=True)

    elif sub["status"] in ("expired", "banned"):
        print(f"💳 Usuario {username} ya tuvo trial. Enviando factura directa.")
        success = await send_invoice_message(user_id, SUBSCRIPTION_PRICE)
        if success:
            await mark_invoice_sent(user_id)
        else:
            await send_expiration_warning(user_id)

    elif sub["status"] == "pending":
        await activate_trial(user_id)
        await send_welcome_message(user_id, username, is_new=True)

    else:
        end_date = sub.get("subscription_end") or (sub.get("trial_start", now) + (TRIAL_DAYS * 86400))
        days_left = max(0, (end_date - now) // 86400)
        await send_welcome_message(user_id, username, is_new=False, days_left=int(days_left))


async def handle_successful_payment(user_id: int):
    await activate_paid(user_id)
    await send_payment_success_message(user_id)


async def run_subscription_checks():
    """Revisa suscripciones + trigger semanal (domingos 20:00-20:05 UTC)."""
    print("🔄 Revisando suscripciones VIP...")

    expiring = await get_expiring_soon(hours=24)
    for user in expiring:
        print(f"  📩 Enviando recordatorio de pago a {user['username']} ({user['user_id']})")
        success = await send_invoice_message(user["user_id"], SUBSCRIPTION_PRICE)
        if success:
            await mark_invoice_sent(user["user_id"])
        else:
            await send_expiration_warning(user["user_id"])

    expired = await get_expired()
    for user in expired:
        print(f"  🚫 Expulsando usuario vencido: {user['username']} ({user['user_id']})")
        await ban_chat_member(VIP_CHANNEL_ID, user["user_id"])
        await update_subscriber_status(user["user_id"], "expired")

    pending = await get_pending_activations(hours=PENDING_ACTIVATION_HOURS)
    for user in pending:
        print(f"  🚫 Expulsando usuario inactivo: {user['username']} ({user['user_id']})")
        await ban_chat_member(VIP_CHANNEL_ID, user["user_id"])
        await update_subscriber_status(user["user_id"], "banned")

    # === v4.0 === - Trigger semanal de reporte
    now_dt = datetime.datetime.utcnow()
    if now_dt.weekday() == 6 and now_dt.hour == 20 and now_dt.minute < 5:
        try:
            from app.database import get_weekly_stats
            from app.telegram import enviar_reporte_semanal
            print("  📊 Generando reporte semanal...")
            stats = await get_weekly_stats()
            await enviar_reporte_semanal(stats)
        except Exception as e:
            print(f"  ⚠️ Error generando reporte semanal: {e}")

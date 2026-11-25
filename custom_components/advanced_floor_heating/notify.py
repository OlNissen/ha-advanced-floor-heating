"""Fælles notifikationer: HA-notifikation og/eller push til mobiler, valgt på Masteren."""
import logging
import re

from homeassistant.components import persistent_notification

from .master import get_master

_LOGGER = logging.getLogger(__name__)


def _plain(text):
    """Push-beskeder viser ikke markdown."""
    return re.sub(r"[*`]", "", text or "")


async def _async_push(hass, service, title, message, notification_id):
    try:
        await hass.services.async_call(
            "notify", service,
            {"title": title, "message": _plain(message), "data": {"tag": notification_id}},
            blocking=False,
        )
    except Exception as err:  # noqa: BLE001 - en mobil der ikke findes maa ikke stoppe de oevrige
        _LOGGER.warning("Kunne ikke sende besked til notify.%s: %s", service, err)


def notify(hass, notification_id, title, message):
    """Send en besked ud fra Masterens indstillinger. Uden Master: kun HA-notifikation."""
    hub = get_master(hass)
    in_ha = hub.notify_in_ha if hub else True
    mobiles = hub.notify_mobiles if hub else []
    if in_ha:
        persistent_notification.async_create(hass, message, title=title, notification_id=notification_id)
    for service in mobiles:
        hass.async_create_task(_async_push(hass, service, title, message, notification_id))
    return {"in_ha": in_ha, "mobiles": list(mobiles)}


def dismiss(hass, notification_id):
    """Fjern HA-notifikationen igen (push-beskeder kan ikke tilbagekaldes)."""
    persistent_notification.async_dismiss(hass, notification_id)

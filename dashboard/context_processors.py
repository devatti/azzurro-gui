from django.conf import settings

from dashboard.services.config import get_config


def plant_context(request):
    """Expose plant configuration to templates."""
    cfg = get_config()
    return {
        'plant': {
            'thing_key': cfg['thing_key'],
            'use_mock': cfg['use_mock'],
            'max_history_days': settings.ZCS_MAX_HISTORY_DAYS,
            'city': cfg['city'],
        }
    }
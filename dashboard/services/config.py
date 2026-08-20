"""Effective ZCS configuration: database-stored credentials.

Credentials saved from the Settings page live encrypted in the database.
"""

import os

from django.conf import settings

from ..models import ZCSConfiguration


def _env_flag(name, default=''):
    return os.environ.get(name, default).lower() in ('1', 'true', 'yes')


def get_config():
    """Resolve the portal configuration used by the whole app."""
    cfg = ZCSConfiguration.get_instance()

    thing_key = cfg.thing_key
    client_code = cfg.client_code
    auth_code = cfg.auth_code
    url = cfg.url or settings.ZCS_URL

    force_mock = _env_flag('ZCS_USE_MOCK')
    use_mock = force_mock or not (thing_key and client_code and auth_code)

    return {
        'url': url,
        'thing_key': thing_key,
        'client_code': client_code,
        'auth_code': auth_code,
        'use_mock': use_mock,
        'city': cfg.city,
    }
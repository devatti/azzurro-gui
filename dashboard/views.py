import json
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from django.conf import settings
from django.http import JsonResponse
from django.shortcuts import render
from django.utils import timezone
from django.views.decorators.http import require_GET, require_http_methods

from .models import ZCSConfiguration
from .services.config import get_config
from .services.weather import WeatherError, WeatherService
from .services.zcs import ZCSError, ZCSService


def dashboard(request):
    """Main live dashboard with the N8N-style energy flow diagram."""
    return render(request, 'dashboard/dashboard.html')


def history(request):
    """Historical data explorer with charts."""
    return render(request, 'dashboard/history.html')


@require_http_methods(['GET', 'POST'])
def portal_settings(request):
    """Settings page: view / update the ZCS portal credentials.

    Credentials are stored encrypted in the database. An empty submitted
    field keeps the currently stored value, so the page can be re-saved
    without wiping the codes. A dedicated "Clear credentials" action resets
    everything back to mock mode.
    """
    cfg = ZCSConfiguration.get_instance()
    config = get_config()
    saved = False

    if request.method == 'POST':
        city = request.POST.get('city', '').strip()
        if request.POST.get('action') == 'clear':
            cfg.set_credentials('', '', '')
            cfg.save()
        else:
            thing_key = request.POST.get('thing_key', '').strip()
            client_code = request.POST.get('client_code', '').strip()
            auth_code = request.POST.get('auth_code', '').strip()
            url = request.POST.get('url', '').strip() or settings.ZCS_URL

            cfg.set_credentials(
                thing_key or cfg.thing_key,
                client_code or cfg.client_code,
                auth_code or cfg.auth_code,
                url=url,
            )
            if city:
                cfg.city = city
            cfg.save()
        saved = True

        # New settings take effect immediately: drop cached snapshots.
        from django.core.cache import cache
        from .services.weather import _cache_key
        cache.delete('zcs:realtime')
        for cached_city in {config['city'], city}:
            if cached_city:
                cache.delete(_cache_key(cached_city))
        config = get_config()

    return render(request, 'dashboard/settings.html', {
        'cfg': cfg,
        'config': config,
        'saved': saved,
    })


@require_GET
def api_realtime(request):
    service = ZCSService()
    try:
        snapshot = service.get_realtime()
    except ZCSError as exc:
        return JsonResponse({'error': str(exc)}, status=503)
    return JsonResponse(snapshot)


@require_GET
def api_weather(request):
    """Current weather + short forecast for the configured city.

    Returns ``{'configured': False}`` when no city is configured so the
    frontend keeps the widget hidden.
    """
    service = WeatherService()
    try:
        weather = service.get_weather()
    except WeatherError as exc:
        return JsonResponse({'configured': True, 'error': str(exc)}, status=503)
    if weather is None:
        return JsonResponse({'configured': False})
    return JsonResponse(weather)


@require_GET
def api_history(request):
    """Return history between two ISO datetimes (default: today)."""
    now = timezone.now()
    start_raw = request.GET.get('start')
    end_raw = request.GET.get('end')

    if start_raw:
        start = _parse_dt(start_raw)
        if start is None:
            return JsonResponse({'error': 'Invalid start datetime'}, status=400)
    else:
        start = now.replace(hour=0, minute=0, second=0, microsecond=0)

    end = _parse_dt(end_raw) if end_raw else now

    if end <= start:
        return JsonResponse({'error': 'end must be after start'}, status=400)

    max_days = settings.ZCS_MAX_HISTORY_DAYS
    if end - start > timedelta(days=max_days):
        start = end - timedelta(days=max_days)

    service = ZCSService()
    try:
        samples = service.get_history_cached(start, end)
    except ZCSError as exc:
        return JsonResponse({'error': str(exc)}, status=503)

    return JsonResponse({
        'start': start.isoformat(),
        'end': end.isoformat(),
        'count': len(samples),
        'samples': samples,
        'mock': get_config()['use_mock'],
    })


def _parse_dt(value):
    value = value.strip().replace('Z', '+00:00').replace(' ', '+')
    try:
        dt = datetime.fromisoformat(value)
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=ZoneInfo(settings.TIME_ZONE))
    return dt
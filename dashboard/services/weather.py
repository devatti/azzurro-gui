"""
Weather service backed by Open-Meteo (no API key required).

The city is configured on the Settings page and stored in the database.
The service geocodes the city to coordinates (cached) and then fetches the
current conditions plus a short daily forecast, normalized into a compact,
frontend friendly structure.
"""

import re

import requests

from django.conf import settings

from .config import get_config

# WMO weather interpretation codes -> (description, emoji icon).
WMO = {
    0: ('Clear sky', '☀️'),
    1: ('Mainly clear', '🌤️'),
    2: ('Partly cloudy', '⛅'),
    3: ('Overcast', '☁️'),
    45: ('Fog', '🌫️'),
    48: ('Depositing rime fog', '🌫️'),
    51: ('Light drizzle', '🌦️'),
    53: ('Drizzle', '🌦️'),
    55: ('Dense drizzle', '🌧️'),
    56: ('Freezing drizzle', '🌧️'),
    57: ('Freezing drizzle', '🌧️'),
    61: ('Light rain', '🌦️'),
    63: ('Rain', '🌧️'),
    65: ('Heavy rain', '🌧️'),
    66: ('Freezing rain', '🌧️'),
    67: ('Freezing rain', '🌧️'),
    71: ('Light snow', '🌨️'),
    73: ('Snow', '🌨️'),
    75: ('Heavy snow', '❄️'),
    77: ('Snow grains', '🌨️'),
    80: ('Light rain showers', '🌦️'),
    81: ('Rain showers', '🌧️'),
    82: ('Violent rain showers', '⛈️'),
    85: ('Snow showers', '🌨️'),
    86: ('Snow showers', '❄️'),
    95: ('Thunderstorm', '⛈️'),
    96: ('Thunderstorm with hail', '⛈️'),
    99: ('Thunderstorm with hail', '⛈️'),
}

DEFAULT_WEATHER = 'Weather conditions'


def _cache_key(city):
    return 'weather:city:' + re.sub(r'\W+', '_', city.lower()).strip('_')


class WeatherError(Exception):
    """Raised when Open-Meteo cannot be reached or returns no usable data."""


class WeatherService:
    """High level API for the weather widget."""

    def get_weather(self):
        """Return the normalized weather snapshot for the configured city.

        Returns ``None`` when no city is configured (the widget stays hidden).
        """
        city = get_config()['city'].strip()
        if not city:
            return None

        from django.core.cache import cache

        cache_key = _cache_key(city)
        cached = cache.get(cache_key)
        if cached is not None:
            return cached

        geo = self._geocode(city)
        if geo is None:
            raise WeatherError(f'Could not find a location for "{city}"')

        lat = geo['latitude']
        lon = geo['longitude']
        forecast = self._forecast(lat, lon)
        if forecast is None:
            raise WeatherError('Weather forecast unavailable')

        weather = {
            'configured': True,
            'city': geo['name'],
            'country': geo.get('country') or '',
            'timezone': geo.get('timezone') or settings.TIME_ZONE,
            'current': self._normalize_current(forecast),
            'daily': self._normalize_daily(forecast),
        }

        cache.set(cache_key, weather, settings.WEATHER_CACHE_TTL)
        return weather

    # -- helpers ----------------------------------------------------------

    def _geocode(self, city):
        """Resolve a city name to coordinates via the Open-Meteo geocoding API."""
        try:
            res = requests.get(
                f'{settings.WEATHER_GEOCODE_URL}/search',
                params={
                    'name': city,
                    'count': 1,
                    'language': 'it',
                    'format': 'json',
                },
                timeout=8,
            )
            res.raise_for_status()
        except requests.RequestException as exc:
            raise WeatherError(f'Weather service unreachable: {exc}') from exc

        data = res.json()
        results = data.get('results') or []
        if not results:
            return None
        return results[0]

    def _forecast(self, lat, lon):
        """Fetch current conditions + daily forecast from the Open-Meteo API."""
        try:
            res = requests.get(
                f'{settings.WEATHER_API_URL}/forecast',
                params={
                    'latitude': lat,
                    'longitude': lon,
                    'timezone': 'auto',
                    'forecast_days': settings.WEATHER_FORECAST_DAYS,
                    'current': (
                        'temperature_2m,relative_humidity_2m,'
                        'apparent_temperature,is_day,precipitation,'
                        'weather_code,wind_speed_10m'
                    ),
                    'daily': (
                        'weather_code,temperature_2m_max,temperature_2m_min,'
                        'precipitation_probability_max,sunrise,sunset'
                    ),
                },
                timeout=8,
            )
            res.raise_for_status()
        except requests.RequestException as exc:
            raise WeatherError(f'Weather service unreachable: {exc}') from exc
        return res.json()

    def _normalize_current(self, forecast):
        cur = forecast.get('current') or {}
        if not cur:
            return None
        code = cur.get('weather_code')
        description, icon = WMO.get(code, (DEFAULT_WEATHER, '🌡️'))
        return {
            'temperature': cur.get('temperature_2m'),
            'apparent_temperature': cur.get('apparent_temperature'),
            'humidity': cur.get('relative_humidity_2m'),
            'precipitation': cur.get('precipitation'),
            'wind_speed': cur.get('wind_speed_10m'),
            'code': code,
            'description': description,
            'icon': icon,
            'is_day': bool(cur.get('is_day')),
            'time': cur.get('time'),
        }

    def _normalize_daily(self, forecast):
        daily = forecast.get('daily') or {}
        times = daily.get('time') or []
        codes = daily.get('weather_code') or []
        tmax = daily.get('temperature_2m_max') or []
        tmin = daily.get('temperature_2m_min') or []
        precip = daily.get('precipitation_probability_max') or []
        days = []
        for idx, day in enumerate(times):
            code = codes[idx] if idx < len(codes) else None
            description, icon = WMO.get(code, (DEFAULT_WEATHER, '🌡️'))
            days.append({
                'date': day,
                'code': code,
                'description': description,
                'icon': icon,
                'min': tmin[idx] if idx < len(tmin) else None,
                'max': tmax[idx] if idx < len(tmax) else None,
                'precip_prob': precip[idx] if idx < len(precip) else None,
            })
        return days
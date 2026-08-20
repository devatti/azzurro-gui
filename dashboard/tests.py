from datetime import datetime, timedelta, timezone
from unittest.mock import patch

import requests
from django.test import SimpleTestCase, TestCase, override_settings
from django.urls import reverse

from .models import ZCSConfiguration
from .services.config import get_config
from .services.weather import WeatherError, WeatherService
from .services.zcs import (
    MockPlant,
    ZCSService,
    normalize_history,
    normalize_realtime,
)

THING_KEY = 'TEST-SERIAL-001'


def _realtime_payload(thing_key, values):
    return {'realtimeData': {'params': {'value': [{thing_key: values}]}}}


class NormalizeRealtimeTests(SimpleTestCase):
    def test_friendly_field_names(self):
        raw = {
            'lastUpdate': '2026-08-20T09:00:00Z',
            'powerGenerating': 3200.0,
            'powerConsuming': 900.0,
            'powerAutoconsuming': 700.0,
            'powerCharging': 1500.0,
            'powerDischarging': 0.0,
            'powerImporting': 0.0,
            'powerExporting': 1200.0,
            'batterySoC': 63.5,
            'temperature': 41.2,
            'voltageDC': 350.0,
            'currentDC': 9.1,
            'powerDC': 3185.0,
            'energyGenerating': 12.4,
            'energyGeneratingTotal': 4512.7,
        }
        snap = normalize_realtime(_realtime_payload(THING_KEY, raw), THING_KEY)
        self.assertEqual(snap['status'], 'online')
        self.assertEqual(snap['power']['generating'], 3200.0)
        self.assertEqual(snap['power']['consuming'], 900.0)
        self.assertEqual(snap['battery_soc'], 63.5)
        self.assertEqual(snap['dc']['voltage'], 350.0)
        self.assertEqual(snap['energy']['generating'], 12.4)

    def test_legacy_raw_names_and_signed_grid(self):
        raw = {
            'lastUpdate': '2026-08-20T09:00:00Z',
            'PVTotalPower': 3100.0,
            'HouseTotalActivePower': 1500.0,
            'EssTotalBatChargePower': 0.0,
            'EssTotalBatDisChargePower': 800.0,
            'GridTotalActivePower': -150.0,  # negative => importing
            'EssSoc': 40.0,
        }
        snap = normalize_realtime(_realtime_payload(THING_KEY, raw), THING_KEY)
        self.assertEqual(snap['power']['generating'], 3100.0)
        self.assertEqual(snap['power']['discharging'], 800.0)
        self.assertEqual(snap['power']['importing'], 150.0)
        self.assertEqual(snap['power']['exporting'], 0.0)
        self.assertEqual(snap['battery_soc'], 40.0)

    def test_missing_payload_is_offline(self):
        snap = normalize_realtime({'realtimeData': {'params': {'value': []}}}, THING_KEY)
        self.assertEqual(snap['status'], 'offline')


class NormalizeHistoryTests(SimpleTestCase):
    def test_parallel_arrays(self):
        raw = {
            'historicData': {
                'params': {
                    'value': [{
                        THING_KEY: {
                            'ts': ['2026-08-20T08:00:00Z', '2026-08-20T08:05:00Z'],
                            'powerGenerating': [100.0, 120.0],
                            'batterySoC': [60.0, 61.0],
                        }
                    }]
                }
            }
        }
        samples = normalize_history(raw, THING_KEY)
        self.assertEqual(len(samples), 2)
        self.assertEqual(samples[0]['powerGenerating'], 100.0)
        self.assertEqual(samples[1]['batterySoC'], 61.0)


class MockPlantTests(SimpleTestCase):
    def test_realtime_shape(self):
        snap = MockPlant.realtime(datetime(2026, 8, 20, 12, 0, tzinfo=timezone.utc))
        self.assertEqual(snap['status'], 'online')
        self.assertGreater(snap['power']['generating'], 0)
        for key in ('generating', 'consuming', 'charging', 'discharging',
                    'importing', 'exporting'):
            self.assertIn(key, snap['power'])

    def test_night_generation_is_zero(self):
        snap = MockPlant.realtime(datetime(2026, 8, 20, 3, 0, tzinfo=timezone.utc))
        self.assertEqual(snap['power']['generating'], 0.0)

    def test_history_length(self):
        start = datetime(2026, 8, 20, 0, 0, tzinfo=timezone.utc)
        end = start + timedelta(hours=6)
        samples = MockPlant.history(start, end)
        # 6 hours at 5-min resolution => 72 samples
        self.assertGreaterEqual(len(samples), 70)


class ViewTests(TestCase):
    @override_settings(USE_MOCK=True)
    def test_realtime_api(self):
        res = self.client.get(reverse('api-realtime'))
        self.assertEqual(res.status_code, 200)
        data = res.json()
        self.assertEqual(data['status'], 'online')
        self.assertIn('power', data)

    @override_settings(USE_MOCK=True)
    def test_history_api(self):
        now = datetime.now(timezone.utc)
        start = now - timedelta(hours=3)
        res = self.client.get(reverse('api-history'), {
            'start': start.isoformat(),
            'end': now.isoformat(),
        })
        self.assertEqual(res.status_code, 200)
        data = res.json()
        self.assertGreater(data['count'], 0)

    @override_settings(USE_MOCK=True)
    def test_history_invalid_range(self):
        now = datetime.now(timezone.utc)
        start = now - timedelta(hours=3)
        res = self.client.get(reverse('api-history'), {
            'start': now.isoformat(),
            'end': start.isoformat(),
        })
        self.assertEqual(res.status_code, 400)

    @override_settings(USE_MOCK=True)
    def test_dashboard_page(self):
        res = self.client.get(reverse('dashboard'))
        self.assertEqual(res.status_code, 200)
        self.assertContains(res, 'flow-canvas')

    @override_settings(USE_MOCK=True)
    def test_history_page(self):
        res = self.client.get(reverse('history'))
        self.assertEqual(res.status_code, 200)
        self.assertContains(res, 'chart-power')

    def test_service_instantiates(self):
        self.assertIsInstance(ZCSService(), ZCSService)


class WeatherServiceTests(TestCase):
    GEO_PAYLOAD = {
        'results': [{
            'name': 'Rome',
            'country': 'Italy',
            'latitude': 41.89,
            'longitude': 12.49,
            'timezone': 'Europe/Rome',
        }],
    }
    FORECAST_PAYLOAD = {
        'current': {
            'time': '2026-08-20T12:00',
            'temperature_2m': 26.4,
            'apparent_temperature': 26.1,
            'relative_humidity_2m': 55,
            'is_day': 1,
            'precipitation': 0.0,
            'weather_code': 2,
            'wind_speed_10m': 12.3,
        },
        'daily': {
            'time': ['2026-08-20', '2026-08-21'],
            'weather_code': [2, 61],
            'temperature_2m_max': [29.0, 27.0],
            'temperature_2m_min': [18.0, 17.0],
            'precipitation_probability_max': [10, 80],
        },
    }

    def setUp(self):
        from django.core.cache import cache
        cache.clear()

    def _mock_requests(self, forecast=FORECAST_PAYLOAD, geo=GEO_PAYLOAD):
        def fake_get(url, params=None, **kwargs):
            class Resp:
                status_code = 200

                def raise_for_status(self):
                    return None

                def json(self):
                    if 'geocoding' in url:
                        return geo
                    return forecast

            return Resp()

        return patch('dashboard.services.weather.requests.get', side_effect=fake_get)

    @override_settings(WEATHER_CACHE_TTL=1)
    def test_not_configured_returns_none(self):
        cfg = ZCSConfiguration.get_instance()
        cfg.city = ''
        cfg.save()
        self.assertIsNone(WeatherService().get_weather())

    @override_settings(WEATHER_CACHE_TTL=1)
    def test_normalized_snapshot(self):
        cfg = ZCSConfiguration.get_instance()
        cfg.city = 'Rome, IT'
        cfg.save()
        with self._mock_requests():
            weather = WeatherService().get_weather()
        self.assertTrue(weather['configured'])
        self.assertEqual(weather['city'], 'Rome')
        self.assertEqual(weather['current']['temperature'], 26.4)
        self.assertEqual(weather['current']['description'], 'Partly cloudy')
        self.assertEqual(len(weather['daily']), 2)
        self.assertEqual(weather['daily'][1]['description'], 'Light rain')
        self.assertEqual(weather['daily'][1]['precip_prob'], 80)

    @override_settings(WEATHER_CACHE_TTL=1)
    def test_unknown_city_raises(self):
        cfg = ZCSConfiguration.get_instance()
        cfg.city = 'Nowhereville'
        cfg.save()
        with self._mock_requests(geo={'results': []}):
            with self.assertRaises(WeatherError):
                WeatherService().get_weather()

    @override_settings(WEATHER_CACHE_TTL=1)
    def test_api_reachability_error_raises(self):
        cfg = ZCSConfiguration.get_instance()
        cfg.city = 'Rome, IT'
        cfg.save()

        def boom(url, params=None, **kwargs):
            raise requests.ConnectionError('network down')

        with patch('dashboard.services.weather.requests.get', side_effect=boom):
            with self.assertRaises(WeatherError):
                WeatherService().get_weather()


class WeatherApiViewTests(TestCase):
    def test_not_configured_returns_configured_false(self):
        cfg = ZCSConfiguration.get_instance()
        cfg.city = ''
        cfg.save()
        res = self.client.get(reverse('api-weather'))
        self.assertEqual(res.status_code, 200)
        self.assertEqual(res.json(), {'configured': False})

    @override_settings(WEATHER_CACHE_TTL=1)
    def test_configured_returns_snapshot(self):
        cfg = ZCSConfiguration.get_instance()
        cfg.city = 'Rome, IT'
        cfg.save()

        geo = {'results': [{'name': 'Rome', 'country': 'Italy', 'latitude': 41.89, 'longitude': 12.49, 'timezone': 'Europe/Rome'}]}
        forecast = {
            'current': {'time': '2026-08-20T12:00', 'temperature_2m': 26.4, 'apparent_temperature': 26.1, 'relative_humidity_2m': 55, 'is_day': 1, 'precipitation': 0.0, 'weather_code': 0, 'wind_speed_10m': 12.3},
            'daily': {'time': ['2026-08-20'], 'weather_code': [0], 'temperature_2m_max': [29.0], 'temperature_2m_min': [18.0], 'precipitation_probability_max': [10]},
        }

        def fake_get(url, params=None, **kwargs):
            class Resp:
                def raise_for_status(self):
                    return None

                def json(self):
                    return geo if 'geocoding' in url else forecast

            return Resp()

        with patch('dashboard.services.weather.requests.get', side_effect=fake_get):
            res = self.client.get(reverse('api-weather'))
        self.assertEqual(res.status_code, 200)
        data = res.json()
        self.assertTrue(data['configured'])
        self.assertEqual(data['current']['temperature'], 26.4)


class ZCSConfigurationTests(TestCase):
    def test_credentials_roundtrip_encrypted(self):
        cfg = ZCSConfiguration.get_instance()
        cfg.set_credentials('SER-1', 'CLIENT-1', 'AUTH-1')
        fresh = ZCSConfiguration.objects.get(pk=1)
        # ciphertext must not contain the plaintext values
        self.assertNotIn('SER-1', fresh.thing_key_enc)
        self.assertNotIn('CLIENT-1', fresh.client_code_enc)
        self.assertNotIn('AUTH-1', fresh.auth_code_enc)
        # decrypts back
        self.assertEqual(fresh.thing_key, 'SER-1')
        self.assertEqual(fresh.client_code, 'CLIENT-1')
        self.assertEqual(fresh.auth_code, 'AUTH-1')

    def test_config_use_mock_follows_credentials(self):
        cfg = ZCSConfiguration.get_instance()
        cfg.set_credentials('', '', '')
        self.assertTrue(get_config()['use_mock'])
        cfg.set_credentials('SER-1', 'CLIENT-1', 'AUTH-1')
        self.assertFalse(get_config()['use_mock'])
        cfg.set_credentials('', '', '')
        self.assertTrue(get_config()['use_mock'])


class PortalSettingsViewTests(TestCase):
    def test_page_renders(self):
        res = self.client.get(reverse('settings'))
        self.assertEqual(res.status_code, 200)
        self.assertContains(res, 'Thing key')
        self.assertContains(res, 'Client code')
        self.assertContains(res, 'Auth code')

    def test_save_stores_encrypted_and_keeps_on_blank(self):
        self.client.post(reverse('settings'), {
            'action': 'save',
            'url': 'https://third.zcsazzurroportal.com:19003/',
            'thing_key': 'TK-123',
            'client_code': 'CC-456',
            'auth_code': 'AC-789',
        })
        cfg = ZCSConfiguration.objects.get(pk=1)
        self.assertEqual(cfg.thing_key, 'TK-123')
        self.assertNotIn('TK-123', cfg.thing_key_enc)

        # blank fields keep existing values
        self.client.post(reverse('settings'), {
            'action': 'save', 'url': '', 'thing_key': '', 'client_code': '', 'auth_code': '',
        })
        cfg = ZCSConfiguration.objects.get(pk=1)
        self.assertEqual((cfg.thing_key, cfg.client_code, cfg.auth_code), ('TK-123', 'CC-456', 'AC-789'))

    def test_clear_returns_to_mock(self):
        cfg = ZCSConfiguration.get_instance()
        cfg.set_credentials('TK-123', 'CC-456', 'AC-789')
        self.client.post(reverse('settings'), {'action': 'clear'})
        cfg = ZCSConfiguration.objects.get(pk=1)
        self.assertEqual((cfg.thing_key, cfg.client_code, cfg.auth_code), ('', '', ''))
        self.assertTrue(get_config()['use_mock'])

    def test_save_stores_city(self):
        cfg = ZCSConfiguration.get_instance()
        cfg.city = ''
        cfg.save()
        self.client.post(reverse('settings'), {'action': 'save', 'city': 'Rome, IT'})
        cfg = ZCSConfiguration.objects.get(pk=1)
        self.assertEqual(cfg.city, 'Rome, IT')

    def test_blank_city_keeps_current(self):
        cfg = ZCSConfiguration.get_instance()
        cfg.city = 'Milan, IT'
        cfg.save()
        self.client.post(reverse('settings'), {'action': 'save', 'city': ''})
        cfg = ZCSConfiguration.objects.get(pk=1)
        self.assertEqual(cfg.city, 'Milan, IT')

    def test_dashboard_shows_weather_widget_when_city_set(self):
        cfg = ZCSConfiguration.get_instance()
        cfg.city = 'Rome, IT'
        cfg.save()
        res = self.client.get(reverse('dashboard'))
        self.assertEqual(res.status_code, 200)
        self.assertContains(res, 'weather-card')

    def test_dashboard_hides_weather_widget_without_city(self):
        cfg = ZCSConfiguration.get_instance()
        cfg.city = ''
        cfg.save()
        res = self.client.get(reverse('dashboard'))
        self.assertEqual(res.status_code, 200)
        self.assertNotContains(res, 'weather-card')
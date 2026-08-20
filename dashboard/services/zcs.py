"""
Service layer for ZCS Azzurro.

Wraps the `zcslib` client and normalizes the raw portal responses into a
compact, frontend friendly structure. When credentials are missing (or mock
mode is forced) a synthetic but realistic dataset is generated so the whole
UI stays explorable.
"""

import math
import random
from datetime import datetime, timedelta, timezone

from django.conf import settings

from zcslib import ZCSClient

from .config import get_config

# --------------------------------------------------------------------------
# Field name mapping. The portal historically exposes two different naming
# conventions (legacy raw inverter names and the friendlier derived ones).
# Each logical field can be resolved from any of the candidate keys.
# --------------------------------------------------------------------------

FIELD_ALIASES = {
    'power_generating': ['powerGenerating', 'PVTotalPower', 'TotalProduction'],
    'power_consuming': ['powerConsuming', 'HouseTotalActivePower', 'TotalActivePower'],
    'power_autoconsuming': ['powerAutoconsuming'],
    'power_charging': ['powerCharging', 'EssTotalBatChargePower'],
    'power_discharging': ['powerDischarging', 'EssTotalBatDisChargePower'],
    'power_importing': ['powerImporting'],
    'power_exporting': ['powerExporting'],
    'battery_soc': ['batterySoC', 'EssSoc'],
    'battery_soc_2': ['batterySoC2', 'EssSoc2'],
    'battery_cycle': ['batteryCycletime', 'EssCycleTime'],
    'battery_cycle_2': ['batteryCycletime2', 'EssCycleTime2'],
    'temperature': ['temperature', 'Temperature'],
    'dc_voltage': ['voltageDC', 'VoltageDC'],
    'dc_current': ['currentDC', 'CurrentDC'],
    'dc_power': ['powerDC', 'PowerDC'],
    'energy_generating': ['energyGenerating'],
    'energy_generating_total': ['energyGeneratingTotal', 'TotalEnergyPV'],
    'energy_consuming': ['energyConsuming'],
    'energy_consuming_total': ['energyConsumingTotal', 'TotalEnergyLoad'],
    'energy_autoconsuming': ['energyAutoconsuming'],
    'energy_autoconsuming_total': ['energyAutoconsumingTotal'],
    'energy_charging': ['energyCharging'],
    'energy_charging_total': ['energyChargingTotal', 'TotalEnergyBatteryCharge'],
    'energy_discharging': ['energyDischarging'],
    'energy_discharging_total': ['energyDischargingTotal', 'TotalEnergyBatteryDischarge'],
    'energy_importing': ['energyImporting'],
    'energy_importing_total': ['energyImportingTotal', 'TotalEnergyImport'],
    'energy_exporting': ['energyExporting'],
    'energy_exporting_total': ['energyExportingTotal', 'TotalEnergyExport'],
}

# Importing / exporting share the same raw key: the sign tells the direction
# (negative = imported, positive = exported).
SIGNED_RAW_KEY = 'GridTotalActivePower'


class ZCSError(Exception):
    """Raised when the ZCS portal cannot be reached or returns no data."""


def _as_float(value):
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _resolve(raw, logical_name):
    """Return the first non-null value for a logical field."""
    for key in FIELD_ALIASES.get(logical_name, []):
        if key in raw:
            return _as_float(raw[key])
    return None


def _first_present(raw, *keys):
    for key in keys:
        if key in raw:
            return _as_float(raw[key])
    return None


class ZCSService:
    """High level API for the dashboard."""

    def __init__(self):
        self._client = None

    # -- client -----------------------------------------------------------

    @property
    def client(self):
        if self._client is None:
            cfg = get_config()
            self._client = ZCSClient(
                cfg['url'],
                thingkey=cfg['thing_key'],
                client_code=cfg['client_code'],
                auth_code=cfg['auth_code'],
            )
        return self._client

    # -- public API -------------------------------------------------------

    def get_realtime(self):
        """Return the normalized realtime snapshot.

        Response is cached for ZCS_REALTIME_CACHE_TTL seconds to keep the
        number of calls to the portal low.
        """
        from django.core.cache import cache

        cache_key = 'zcs:realtime'
        cached = cache.get(cache_key)
        if cached is not None:
            return cached

        if get_config()['use_mock']:
            snapshot = MockPlant.realtime(now=datetime.now(timezone.utc))
        else:
            try:
                raw = self.client.get_realtime_data()
            except Exception as exc:  # requests network / portal errors
                raise ZCSError(f'ZCS portal unreachable: {exc}') from exc
            snapshot = normalize_realtime(raw, thing_key=get_config()['thing_key'])

        cache.set(cache_key, snapshot, settings.ZCS_REALTIME_CACHE_TTL)
        return snapshot

    def get_history(self, start_dt, end_dt, persist=True):
        """Return normalized historical samples in the given range.

        The portal allows at most 24h per request, so longer ranges are split
        into multiple requests and merged. When ``persist`` is true each
        fetched sample is upserted into the database so data accumulates
        locally over time.
        """
        if start_dt.tzinfo is None:
            start_dt = start_dt.replace(tzinfo=timezone.utc)
        if end_dt.tzinfo is None:
            end_dt = end_dt.replace(tzinfo=timezone.utc)

        if get_config()['use_mock']:
            return MockPlant.history(start_dt, end_dt)

        from .persistence import persist_samples

        max_span = timedelta(hours=settings.ZCS_MAX_HISTORY_SPAN)
        samples = []
        cursor = start_dt
        while cursor < end_dt:
            chunk_end = min(cursor + max_span, end_dt)
            try:
                raw = self.client.get_historic_data(cursor, chunk_end)
            except Exception as exc:
                raise ZCSError(f'ZCS portal unreachable: {exc}') from exc
            chunk = normalize_history(raw, thing_key=get_config()['thing_key'])
            samples.extend(chunk)
            if persist and chunk:
                persist_samples(get_config()['thing_key'], chunk)
            cursor = chunk_end
        return samples

    def get_history_cached(self, start_dt, end_dt, coverage=0.8):
        """History backed by the local database when it already covers the
        requested window (to save API calls). Falls back to a live fetch."""
        if start_dt.tzinfo is None:
            start_dt = start_dt.replace(tzinfo=timezone.utc)
        if end_dt.tzinfo is None:
            end_dt = end_dt.replace(tzinfo=timezone.utc)

        if get_config()['use_mock']:
            return MockPlant.history(start_dt, end_dt)

        from .persistence import read_samples, expected_samples, coverage_ok

        thing_key = get_config()['thing_key']
        expected = expected_samples(start_dt, end_dt)
        if expected <= 0:
            return []

        count = read_samples(thing_key, start_dt, end_dt, count_only=True)
        if not coverage_ok(count, expected, coverage):
            return self.get_history(start_dt, end_dt, persist=True)

        return read_samples(thing_key, start_dt, end_dt)


def _payload_data(raw, section, thing_key):
    """Extract the raw value dict from a portal response section."""
    section = raw.get(section, {})
    params = section.get('params', section)
    value = params.get('value')
    if isinstance(value, list) and value:
        candidates = [v for v in value if isinstance(v, dict)]
    elif isinstance(value, dict):
        candidates = [value]
    else:
        candidates = []

    for candidate in candidates:
        if thing_key and thing_key in candidate:
            data = candidate[thing_key]
            if isinstance(data, dict):
                return data
        if isinstance(candidate, dict):
            # fall back to the first plausible flat dict of numbers
            data = candidate
            if data and all(isinstance(k, str) for k in data.keys()):
                return data
    return {}


def normalize_realtime(raw, thing_key=None):
    """Turn a raw realtimeData response into the dashboard snapshot."""
    values = _payload_data(raw, 'realtimeData', thing_key)

    power = {}
    for name in ('generating', 'consuming', 'autoconsuming', 'charging',
                 'discharging', 'importing', 'exporting'):
        power[name] = _resolve(values, f'power_{name}')

    energy = {}
    for name in ('generating', 'consuming', 'autoconsuming', 'charging',
                 'discharging', 'importing', 'exporting'):
        energy[name] = _resolve(values, f'energy_{name}')
        energy[f'{name}_total'] = _resolve(values, f'energy_{name}_total')

    # Grid power may only exist as a signed value (negative = imported,
    # positive = exported). Respect explicit importing/exporting when present.
    grid_raw = _first_present(values, 'GridTotalActivePower')
    if grid_raw is not None:
        if power['importing'] is None:
            power['importing'] = max(0.0, -grid_raw)
        if power['exporting'] is None:
            power['exporting'] = max(0.0, grid_raw)

    snapshot = {
        'status': 'online' if values else 'offline',
        'last_update': values.get('lastUpdate'),
        'first_update': values.get('thingFind'),
        'battery_soc': _resolve(values, 'battery_soc'),
        'battery_soc_2': _resolve(values, 'battery_soc_2'),
        'battery_cycle': _resolve(values, 'battery_cycle'),
        'battery_cycle_2': _resolve(values, 'battery_cycle_2'),
        'temperature': _resolve(values, 'temperature'),
        'dc': {
            'voltage': _resolve(values, 'dc_voltage'),
            'current': _resolve(values, 'dc_current'),
            'power': _resolve(values, 'dc_power'),
        },
        'power': power,
        'energy': energy,
    }

    if not values:
        snapshot['status'] = 'offline'
    elif snapshot['power']['generating'] is None and not energy:
        snapshot['status'] = 'degraded'

    return snapshot


def normalize_history(raw, thing_key=None):
    """Turn a raw historicData response into a list of sample dicts."""
    values = _payload_data(raw, 'historicData', thing_key)
    timestamps = values.get('ts') or []
    if not timestamps or not isinstance(timestamps, list):
        return []

    # Keys are parallel arrays; ts holds the timestamps.
    series_keys = [k for k in values.keys() if isinstance(values[k], list) and k != 'ts']
    samples = []
    for idx, ts in enumerate(timestamps):
        sample = {'ts': ts}
        for key in series_keys:
            row = values[key]
            if idx < len(row):
                sample[key] = _as_float(row[idx])
        samples.append(sample)
    return samples


# --------------------------------------------------------------------------
# Mock plant – plausible synthetic data so the UI works without credentials.
# --------------------------------------------------------------------------

class MockPlant:
    """Generates a believable residential PV + battery + grid plant."""

    # Capacity / sizing of the virtual plant (Watts / kWh).
    PV_PEAK = 4200.0
    BATTERY_CAPACITY = 6.4  # kWh usable
    INVERTER_MAX = 6000.0

    @staticmethod
    def _seed(ts):
        seed = int(ts.timestamp() // 300)  # 5-minute buckets
        return random.Random(seed)

    @staticmethod
    def _solar_curve(ts):
        """kW available from the panels at a given time (clear-sky parabola)."""
        hour = ts.hour + ts.minute / 60.0
        if hour < 6 or hour > 21:
            return 0.0
        # gentle parabola peaking at midday
        factor = -1.0 / 56.25 * (hour - 13.5) ** 2 + 1.0
        factor = max(0.0, factor)
        return MockPlant.PV_PEAK * factor / 1000.0

    @staticmethod
    def _home_load(ts):
        rng = MockPlant._seed(ts)
        hour = ts.hour + ts.minute / 60.0
        base = {
            0: 0.18, 1: 0.15, 2: 0.12, 3: 0.11, 4: 0.12, 5: 0.16,
            6: 0.55, 7: 1.10, 8: 0.95, 9: 0.55, 10: 0.40, 11: 0.35,
            12: 0.42, 13: 0.38, 14: 0.35, 15: 0.37, 16: 0.45, 17: 0.70,
            18: 1.30, 19: 1.55, 20: 1.40, 21: 1.05, 22: 0.70, 23: 0.40,
        }[int(hour)]
        load = base * (0.7 + 0.6 * rng.random())
        return min(load, 5.0)

    @classmethod
    def _state(cls, ts, soc=None):
        rng = cls._seed(ts)
        pv_kw = cls._solar_curve(ts)
        load_kw = cls._home_load(ts)

        pv_w = pv_kw * 1000.0 * (0.92 + 0.16 * rng.random())
        load_w = load_kw * 1000.0

        if soc is None:
            soc = 50 + 40 * rng.random()

        battery_soc = soc
        charging = discharging = 0.0

        surplus = pv_w - load_w
        if surplus > 60:
            charging = min(surplus, 1500.0)
            if battery_soc >= 97:
                charging = 0.0
        else:
            deficit = load_w - pv_w
            if battery_soc > 15:
                discharging = min(deficit, 1800.0)
            else:
                discharging = 0.0

        remaining = surplus - charging + discharging
        if remaining > 60:
            exporting = remaining
            importing = 0.0
        elif remaining < -60:
            exporting = 0.0
            importing = -remaining
        else:
            exporting = importing = 0.0

        autoconsuming = min(pv_w, load_w)

        dc_power = pv_w
        dc_voltage = 330 + 45 * rng.random() if pv_w > 30 else 0.0
        dc_current = (dc_power / dc_voltage) if dc_voltage > 0 else 0.0

        return {
            'power': {
                'generating': pv_w,
                'consuming': load_w,
                'autoconsuming': autoconsuming,
                'charging': charging,
                'discharging': discharging,
                'importing': importing,
                'exporting': exporting,
            },
            'battery_soc': battery_soc,
            'temperature': 28 + 22 * (pv_kw / (cls.PV_PEAK / 1000.0)),
            'dc': {'voltage': dc_voltage, 'current': dc_current, 'power': dc_power},
        }

    @classmethod
    def realtime(cls, now=None):
        """Full realtime snapshot for the current time."""
        now = now or datetime.now(timezone.utc)
        rng = cls._seed(now)
        state = cls._state(now)
        soc = state['battery_soc']

        today = now.replace(hour=0, minute=0, second=0, microsecond=0)
        day_fraction = (now - today).total_seconds() / 86400.0

        # energy today as a rough integral of the power curves
        e_gen = cls.PV_PEAK / 1000.0 * max(0.0, day_fraction - 0.25) * 3.6
        e_cons = 9.5 * day_fraction + 1.1
        e_auto = min(e_gen, e_cons) * 0.82
        e_charge = e_gen * 0.18
        e_discharge = max(0.0, e_cons - e_auto) * 0.5
        e_import = max(0.0, e_cons - e_auto - e_discharge)
        e_export = max(0.0, e_gen - e_auto - e_charge)

        def tot(v):
            base = rng.uniform(800, 4200)
            return round(base + v, 2)

        energy = {
            'generating': round(e_gen, 2), 'generating_total': tot(e_gen),
            'consuming': round(e_cons, 2), 'consuming_total': tot(e_cons),
            'autoconsuming': round(e_auto, 2), 'autoconsuming_total': tot(e_auto),
            'charging': round(e_charge, 2), 'charging_total': tot(e_charge),
            'discharging': round(e_discharge, 2), 'discharging_total': tot(e_discharge),
            'importing': round(e_import, 2), 'importing_total': tot(e_import),
            'exporting': round(e_export, 2), 'exporting_total': tot(e_export),
        }

        return {
            'status': 'online',
            'last_update': now.isoformat().replace('+00:00', 'Z'),
            'first_update': '2024-03-01T08:00:00Z',
            'battery_soc': round(soc, 1),
            'battery_soc_2': round(min(100.0, soc * 0.97), 1),
            'battery_cycle': round(rng.uniform(40, 900), 0),
            'battery_cycle_2': round(rng.uniform(40, 900), 0),
            'temperature': round(state['temperature'], 1),
            'dc': {k: round(v, 1) for k, v in state['dc'].items()},
            'power': {k: round(v, 1) for k, v in state['power'].items()},
            'energy': energy,
            'mock': True,
        }

    @classmethod
    def history(cls, start_dt, end_dt):
        """Samples every 5 minutes across the range (max ~2.5k points)."""
        step = timedelta(minutes=5)
        samples = []
        cursor = start_dt.replace(tzinfo=timezone.utc)
        end_dt = end_dt.replace(tzinfo=timezone.utc)
        soc = 50.0
        while cursor < end_dt:
            state = cls._state(cursor, soc=soc)
            energy_integral = 0.0
            step_h = step.total_seconds() / 3600.0
            pv_w = state['power']['generating']
            load_w = state['power']['consuming']
            charging = state['power']['charging']
            discharging = state['power']['discharging']
            exporting = state['power']['exporting']
            importing = state['power']['importing']

            soc = min(100.0, soc + (charging - discharging) * step_h / (cls.BATTERY_CAPACITY * 1000.0))
            soc = max(5.0, soc)

            samples.append({
                'ts': cursor.isoformat().replace('+00:00', 'Z'),
                'powerGenerating': round(pv_w, 1),
                'powerConsuming': round(load_w, 1),
                'powerCharging': round(charging, 1),
                'powerDischarging': round(discharging, 1),
                'powerExporting': round(exporting, 1),
                'powerImporting': round(importing, 1),
                'powerAutoconsuming': round(min(pv_w, load_w), 1),
                'batterySoC': round(soc, 1),
                'temperature': round(state['temperature'], 1),
                'voltageDC': round(state['dc']['voltage'], 1),
                'currentDC': round(state['dc']['current'], 1),
                'powerDC': round(state['dc']['power'], 1),
                'energyGenerating': round(energy_integral, 3),
            })
            cursor += step
        return samples


# number formatting helpers reused across the app
def w_to_kw(watts):
    if watts is None:
        return None
    return round(watts / 1000.0, 3)

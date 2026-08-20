"""Persistence helpers for historical samples (SQLite backed)."""

from datetime import timedelta

from django.db.models import Count

from ..models import HistoricSample

SAMPLE_STEP = timedelta(minutes=5)


def parse_ts(ts):
    """Normalize an ISO timestamp string into an aware datetime."""
    if isinstance(ts, str):
        ts = ts.replace('Z', '+00:00')
    return ts


def persist_samples(thing_key, samples):
    """Upsert a batch of raw samples into the database."""
    batch = []
    for sample in samples:
        batch.append(
            HistoricSample(
                thing_key=thing_key,
                ts=parse_ts(sample['ts']),
                data={k: v for k, v in sample.items() if k != 'ts'},
            )
        )
    HistoricSample.objects.bulk_create(
        batch, update_conflicts=True,
        update_fields=['data', 'created_at'],
        unique_fields=['thing_key', 'ts'],
    )


def read_samples(thing_key, start_dt, end_dt, count_only=False):
    """Read stored samples in range, as raw sample dicts."""
    qs = HistoricSample.objects.filter(
        thing_key=thing_key,
        ts__gte=start_dt,
        ts__lt=end_dt,
    ).order_by('ts')

    if count_only:
        return qs.count()

    return [
        {'ts': s.ts.isoformat().replace('+00:00', 'Z'), **s.data}
        for s in qs
    ]


def expected_samples(start_dt, end_dt):
    """Expected number of samples at the 5-minute resolution."""
    span_seconds = (end_dt - start_dt).total_seconds()
    return max(0, int(span_seconds // SAMPLE_STEP.total_seconds())) if span_seconds > 0 else 0


def coverage_ok(count, expected, coverage):
    return expected > 0 and count >= expected * coverage
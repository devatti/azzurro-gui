"""Backfill historical data from the ZCS portal into the local database.

Usage:
    python manage.py backfill_history [--days 7] [--live]
"""

import sys
from datetime import datetime, timedelta, timezone

from django.core.management.base import BaseCommand, CommandError
from django.utils import timezone as dj_timezone

from dashboard.services.zcs import ZCSError, ZCSService


class Command(BaseCommand):
    help = 'Fetch historical samples from the ZCS portal and store them locally.'

    def add_arguments(self, parser):
        parser.add_argument('--days', type=int, default=7,
                            help='How many days to backfill (default: 7).')
        parser.add_argument('--live', action='store_true',
                            help='Also fetch recent samples (default: skip to avoid duplicate portal calls).')

    def handle(self, *args, **options):
        days = options['days']
        if days <= 0:
            raise CommandError('--days must be positive')

        from dashboard.services.config import get_config
        if get_config()['use_mock']:
            self.stdout.write(self.style.WARNING(
                'Mock mode is active, nothing to backfill. Configure ZCS credentials to use this command.'
            ))
            return

        service = ZCSService()
        now = dj_timezone.now()
        start = now - timedelta(days=days)
        total = 0
        cursor = start

        self.stdout.write(f'Backfilling {days} day(s) of history...')
        while cursor < now:
            chunk_end = min(cursor + timedelta(hours=24), now)
            try:
                samples = service.get_history(cursor, chunk_end, persist=True)
            except ZCSError as exc:
                self.stderr.write(self.style.ERROR(f'  error: {exc}'))
                sys.exit(1)
            total += len(samples)
            self.stdout.write(f'  {cursor.date()} -> {chunk_end.date()}: {len(samples)} samples')
            cursor = chunk_end

        self.stdout.write(self.style.SUCCESS(f'Done. {total} samples stored.'))
from django.db import models

from .services import crypto


class HistoricSample(models.Model):
    """A single raw historical sample, persisted so history survives
    between requests and API usage stays low."""

    thing_key = models.CharField(max_length=64)
    ts = models.DateTimeField(db_index=True)
    data = models.JSONField(default=dict)

    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['ts']
        indexes = [models.Index(fields=['thing_key', 'ts'])]
        constraints = [
            models.UniqueConstraint(fields=['thing_key', 'ts'], name='uniq_sample_ts')
        ]

    def __str__(self):
        return f'{self.thing_key} @ {self.ts}'


class ZCSConfiguration(models.Model):
    """Portal credentials, stored encrypted so they never sit in plain text.

    This is a singleton row (pk=1). Blank encrypted fields mean the value has
    not been configured from the UI, in which case the app falls back to the
    environment variables (``ZCS_*`` in settings).
    """

    url = models.CharField(
        max_length=255,
        default='https://third.zcsazzurroportal.com:19003/',
    )
    thing_key_enc = models.TextField(default='', blank=True)
    client_code_enc = models.TextField(default='', blank=True)
    auth_code_enc = models.TextField(default='', blank=True)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = 'ZCS configuration'
        verbose_name_plural = 'ZCS configuration'

    def __str__(self):
        configured = sum(bool(self.thing_key_enc), bool(self.client_code_enc),
                         bool(self.auth_code_enc))
        return f'ZCS configuration ({configured}/3 credentials stored)'

    @classmethod
    def get_instance(cls):
        """Return the single configuration row, creating it if needed."""
        obj, _ = cls.objects.get_or_create(pk=1)
        return obj

    @property
    def thing_key(self):
        return crypto.decrypt(self.thing_key_enc)

    @property
    def client_code(self):
        return crypto.decrypt(self.client_code_enc)

    @property
    def auth_code(self):
        return crypto.decrypt(self.auth_code_enc)

    def set_credentials(self, thing_key, client_code, auth_code, url=None):
        self.thing_key_enc = crypto.encrypt(thing_key)
        self.client_code_enc = crypto.encrypt(client_code)
        self.auth_code_enc = crypto.encrypt(auth_code)
        if url:
            self.url = url
        self.save()

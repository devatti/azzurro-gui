"""
Django settings for azzurro project.

The app talks to ZCS Azzurro via the `zcslib` client (see zcslib/ in the repo).
All ZCS credentials and behaviour are configured through environment variables
so the dashboard can run in "mock mode" out of the box.
"""

import os
from pathlib import Path

from dotenv import load_dotenv

# Build paths inside the project like this: BASE_DIR / 'subdir'.
BASE_DIR = Path(__file__).resolve().parent.parent

load_dotenv(BASE_DIR / '.env')


# Quick-start development settings - unsuitable for production
# See https://docs.djangoproject.com/en/6.1/howto/deployment/checklist/

# SECURITY WARNING: keep the secret key used in production secret!
SECRET_KEY = os.environ.get(
    'DJANGO_SECRET_KEY', 'django-insecure-1q5hqso#u4d!w)k!a^jsll@zva=rraxxm#-)$e8+r)&8$fq-$6'
)

# SECURITY WARNING: don't run with debug turned on in production!
DEBUG = os.environ.get('DJANGO_DEBUG', 'true').lower() in ('1', 'true', 'yes')

ALLOWED_HOSTS = [
    h.strip()
    for h in os.environ.get('DJANGO_ALLOWED_HOSTS', 'localhost,127.0.0.1').split(',')
    if h.strip()
]


# Application definition

INSTALLED_APPS = [
    'django.contrib.admin',
    'django.contrib.auth',
    'django.contrib.contenttypes',
    'django.contrib.sessions',
    'django.contrib.messages',
    'django.contrib.staticfiles',
    'dashboard',
]

MIDDLEWARE = [
    'django.middleware.security.SecurityMiddleware',
    'whitenoise.middleware.WhiteNoiseMiddleware',
    'django.contrib.sessions.middleware.SessionMiddleware',
    'django.middleware.common.CommonMiddleware',
    'django.middleware.csrf.CsrfViewMiddleware',
    'django.contrib.auth.middleware.AuthenticationMiddleware',
    'django.contrib.messages.middleware.MessageMiddleware',
    'django.middleware.clickjacking.XFrameOptionsMiddleware',
]

ROOT_URLCONF = 'azzurro.urls'

TEMPLATES = [
    {
        'BACKEND': 'django.template.backends.django.DjangoTemplates',
        'DIRS': [],
        'APP_DIRS': True,
        'OPTIONS': {
            'context_processors': [
                'django.template.context_processors.request',
                'django.contrib.auth.context_processors.auth',
                'django.contrib.messages.context_processors.messages',
                'dashboard.context_processors.plant_context',
            ],
        },
    },
]

WSGI_APPLICATION = 'azzurro.wsgi.application'


# Database
# https://docs.djangoproject.com/en/6.1/ref/settings/#databases

DATABASES = {
    'default': {
        'ENGINE': 'django.db.backends.sqlite3',
        'NAME': os.environ.get('DJANGO_DB_PATH', BASE_DIR / 'db.sqlite3'),
    }
}


# Password validation
# https://docs.djangoproject.com/en/6.1/ref/settings/#auth-password-validators

AUTH_PASSWORD_VALIDATORS = [
    {
        'NAME': 'django.contrib.auth.password_validation.UserAttributeSimilarityValidator',
    },
    {
        'NAME': 'django.contrib.auth.password_validation.MinimumLengthValidator',
    },
    {
        'NAME': 'django.contrib.auth.password_validation.CommonPasswordValidator',
    },
    {
        'NAME': 'django.contrib.auth.password_validation.NumericPasswordValidator',
    },
]


# Internationalization
# https://docs.djangoproject.com/en/6.1/topics/i18n/

LANGUAGE_CODE = 'en-us'

TIME_ZONE = os.environ.get('DJANGO_TIME_ZONE', 'Europe/Rome')

USE_I18N = True

USE_TZ = True


# Static files (CSS, JavaScript, Images)
# https://docs.djangoproject.com/en/6.1/howto/static-files/

STATIC_URL = 'static/'
STATIC_ROOT = BASE_DIR / 'staticfiles'

# Default primary key field type
# https://docs.djangoproject.com/en/6.1/ref/settings/#default-auto-field

DEFAULT_AUTO_FIELD = 'django.db.models.BigAutoField'


# --------------------------------------------------------------------------
# ZCS Azzurro configuration
# --------------------------------------------------------------------------
# Credentials are entered on the Settings page and stored encrypted in the
# database. Without them the dashboard runs in mock/demo mode, which
# generates plausible synthetic plant data so the whole UI can be explored.
ZCS_URL = os.environ.get('ZCS_URL', 'https://third.zcsazzurroportal.com:19003/')

USE_MOCK = os.environ.get('ZCS_USE_MOCK', '').lower() in ('1', 'true', 'yes')

# How long (seconds) a realtime snapshot stays cached before hitting the API.
ZCS_REALTIME_CACHE_TTL = int(os.environ.get('ZCS_REALTIME_CACHE_TTL', '30'))
# Maximum span of a single historic API request (the portal allows max 24h).
ZCS_MAX_HISTORY_SPAN = int(os.environ.get('ZCS_MAX_HISTORY_SPAN', '24'))
# Cap on how far back the history page is allowed to look, in days.
ZCS_MAX_HISTORY_DAYS = int(os.environ.get('ZCS_MAX_HISTORY_DAYS', '7'))

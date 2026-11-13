"""
Django settings.

Everything that differs between a laptop and a server is read from environment variables (see
`.env.example` and `docs/deployment.md`). With no variables set the defaults suit local development.
"""

import importlib.util
import os
from pathlib import Path

from django.core.exceptions import ImproperlyConfigured

from backend.env import database_from_url, env_bool, env_int, env_list

# Build paths inside the project like this: BASE_DIR / 'subdir'.
BASE_DIR = Path(__file__).resolve().parent.parent

# SECURITY WARNING: don't run with debug turned on in production!
DEBUG = env_bool("DJANGO_DEBUG", True)

# SECURITY WARNING: keep the secret key used in production secret!
SECRET_KEY = os.environ.get("DJANGO_SECRET_KEY", "dev-only-insecure-key-change-me")
if not DEBUG and (len(SECRET_KEY) < 32 or SECRET_KEY.startswith(("dev-only", "change-me"))):
    raise ImproperlyConfigured("Set DJANGO_SECRET_KEY to a long random value when DJANGO_DEBUG is off.")

ALLOWED_HOSTS = env_list("DJANGO_ALLOWED_HOSTS", "127.0.0.1,localhost")
CSRF_TRUSTED_ORIGINS = env_list("DJANGO_CSRF_TRUSTED_ORIGINS")  # e.g. https://meals.example.org


# Application definition

INSTALLED_APPS = [
    'django.contrib.admin',
    'django.contrib.auth',
    'django.contrib.contenttypes',
    'django.contrib.sessions',
    'django.contrib.messages',
    'django.contrib.staticfiles',
    'organizations',
    'residents',
    'mess',
    'accounts',
    'attendance',
    'reports',
]

MIDDLEWARE = [
    'django.middleware.security.SecurityMiddleware',
    'django.contrib.sessions.middleware.SessionMiddleware',
    'django.middleware.common.CommonMiddleware',
    'django.middleware.csrf.CsrfViewMiddleware',
    'django.contrib.auth.middleware.AuthenticationMiddleware',
    'django.contrib.messages.middleware.MessageMiddleware',
    'django.middleware.clickjacking.XFrameOptionsMiddleware',
]

ROOT_URLCONF = 'backend.urls'

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
            ],
        },
    },
]

WSGI_APPLICATION = 'backend.wsgi.application'


# Database
# https://docs.djangoproject.com/en/6.0/ref/settings/#databases

if os.environ.get("DATABASE_URL"):
    DATABASES = {"default": database_from_url(os.environ["DATABASE_URL"], BASE_DIR)}
else:
    DATABASES = {
        "default": {
            "ENGINE": "django.db.backends.sqlite3",
            "NAME": Path(os.environ.get("SQLITE_PATH", BASE_DIR / "db.sqlite3")),
        }
    }


# Password validation
# https://docs.djangoproject.com/en/6.0/ref/settings/#auth-password-validators

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
# https://docs.djangoproject.com/en/6.0/topics/i18n/

LANGUAGE_CODE = 'en-us'

TIME_ZONE = 'UTC'

USE_I18N = True

USE_TZ = True


# Static files (CSS, JavaScript, Images)
# https://docs.djangoproject.com/en/6.0/howto/static-files/

STATIC_URL = 'static/'
STATIC_ROOT = Path(os.environ.get("DJANGO_STATIC_ROOT", BASE_DIR / "staticfiles"))

# Uploaded photos. On a server, point this at a persistent volume.
MEDIA_URL = '/media/'
MEDIA_ROOT = Path(os.environ.get("DJANGO_MEDIA_ROOT", BASE_DIR / "media"))

# WhiteNoise serves the static files from the app itself when it is installed (requirements-prod.txt).
if importlib.util.find_spec("whitenoise") is not None:
    MIDDLEWARE.insert(1, "whitenoise.middleware.WhiteNoiseMiddleware")
    if not DEBUG:
        STORAGES = {
            "default": {"BACKEND": "django.core.files.storage.FileSystemStorage"},
            "staticfiles": {"BACKEND": "whitenoise.storage.CompressedManifestStaticFilesStorage"},
        }

# Authentication
LOGIN_URL = 'accounts:login'
LOGIN_REDIRECT_URL = 'accounts:home'
LOGOUT_REDIRECT_URL = 'accounts:login'
SESSION_COOKIE_AGE = env_int("DJANGO_SESSION_HOURS", 12) * 3600  # a shared hostel computer should not stay signed in for weeks

# Public page where a new organisation registers itself and its first admin.
# Set ALLOW_ORG_SIGNUP=0 in the environment to switch it off on a locked-down server.
ALLOW_ORG_SIGNUP = env_bool("ALLOW_ORG_SIGNUP", True)

# Uploaded import files wait here (outside the public media folder) between preview and confirmation.
IMPORT_STAGING_DIR = Path(os.environ.get("DJANGO_IMPORT_STAGING_DIR", BASE_DIR / "var" / "import_staging"))

# Django message levels map to Bootstrap alert colours
from django.contrib.messages import constants as messages_constants

MESSAGE_TAGS = {messages_constants.ERROR: 'danger'}

# ---------------------------------------------------------------------------
# Production hardening. DJANGO_HTTPS=1 means the site is served over https
# (directly or behind a reverse proxy that sets X-Forwarded-Proto).
# ---------------------------------------------------------------------------
if env_bool("DJANGO_BEHIND_PROXY", False):
    SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")
    USE_X_FORWARDED_HOST = True

if not DEBUG and env_bool("DJANGO_HTTPS", False):
    SECURE_SSL_REDIRECT = True
    SESSION_COOKIE_SECURE = True
    CSRF_COOKIE_SECURE = True
    SECURE_HSTS_SECONDS = env_int("DJANGO_HSTS_SECONDS", 2592000)  # 30 days; raise it once https is proven
    SECURE_HSTS_INCLUDE_SUBDOMAINS = False
    SECURE_HSTS_PRELOAD = False
    # Deliberate: this app must not force https on other sites under the same domain or join the preload list.
    SILENCED_SYSTEM_CHECKS = ["security.W005", "security.W021"]

SECURE_CONTENT_TYPE_NOSNIFF = True
SECURE_REFERRER_POLICY = "same-origin"
X_FRAME_OPTIONS = "DENY"

# ---------------------------------------------------------------------------
# Logging: one readable line per event on stdout (what Docker and most hosts collect).
# ---------------------------------------------------------------------------
LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "formatters": {"plain": {"format": "%(asctime)s %(levelname)s %(name)s %(message)s"}},
    "handlers": {"console": {"class": "logging.StreamHandler", "formatter": "plain"}},
    "root": {"handlers": ["console"], "level": os.environ.get("DJANGO_LOG_LEVEL", "INFO")},
    "loggers": {"django.request": {"level": "WARNING"}},
}

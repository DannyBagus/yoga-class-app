from pathlib import Path
import environ
import os

# initialize the environment variables
env = environ.Env(
    # set casting, default value
    DEBUG=(bool, False)
)

# Build paths inside the project like this: BASE_DIR / 'subdir'.
BASE_DIR = Path(__file__).resolve().parent.parent

# Take environment variables from .env file
environ.Env.read_env(os.path.join(BASE_DIR, '.env'))

# Quick-start development settings - unsuitable for production
# See https://docs.djangoproject.com/en/5.1/howto/deployment/checklist/

# SECURITY WARNING: keep the secret key used in production secret!
SECRET_KEY = env('SECRET_KEY')

# SECURITY WARNING: don't run with debug turned on in production!
DEBUG = env('DEBUG')

ALLOWED_HOSTS = env.list('ALLOWED_HOSTS')

CSRF_TRUSTED_ORIGINS = env.list('CSRF_TRUSTED_ORIGINS')

SECURE_PROXY_SSL_HEADER = ('HTTP_X_FORWARDED_PROTO', 'https')

# Application definition

INSTALLED_APPS = [
    #django apps
    'django.contrib.admin',
    'django.contrib.auth',
    'django.contrib.contenttypes',
    'django.contrib.sessions',
    'django.contrib.messages',
    'django.contrib.staticfiles',
    
    # custom apps
    'core',
    'users',
    'course',

    # OIDC
    'mozilla_django_oidc',
]

AUTHENTICATION_BACKENDS = [
    'users.oidc_backend.YogaOIDCBackend',
    'django.contrib.auth.backends.ModelBackend',
]

MIDDLEWARE = [
    'django.middleware.security.SecurityMiddleware',
    'whitenoise.middleware.WhiteNoiseMiddleware',  # for serving static files with whitenoise
    'django.contrib.sessions.middleware.SessionMiddleware',
    'django.middleware.common.CommonMiddleware',
    'django.middleware.csrf.CsrfViewMiddleware',
    'django.contrib.auth.middleware.AuthenticationMiddleware',
    'django.contrib.messages.middleware.MessageMiddleware',
    'django.middleware.clickjacking.XFrameOptionsMiddleware',
]

ROOT_URLCONF = 'yoga.urls'

TEMPLATES = [
    {
        'BACKEND': 'django.template.backends.django.DjangoTemplates',
        'DIRS': [],
        'APP_DIRS': True,
        'OPTIONS': {
            'context_processors': [
                'django.template.context_processors.debug',
                'django.template.context_processors.request',
                'django.contrib.auth.context_processors.auth',
                'django.contrib.messages.context_processors.messages',
            ],
        },
    },
]

WSGI_APPLICATION = 'yoga.wsgi.application'


# Database
# https://docs.djangoproject.com/en/5.1/ref/settings/#databases

'''
# Development
DATABASES = {
    'default': {
        'ENGINE': 'django.db.backends.sqlite3',
        'NAME': BASE_DIR / 'db.sqlite3',
    }
}
'''   

# Production
DATABASES = {  
    'default': {
        'ENGINE': 'django.db.backends.mysql',  
        'NAME': env('MYSQL_NAME'),
        'USER': env('MYSQL_USER'),
        'PASSWORD': env('MYSQL_USER_PASSWORD'),  
        'HOST': 'yoga-db',  
        'PORT': '3306'
    }
} 



# Password validation
# https://docs.djangoproject.com/en/5.1/ref/settings/#auth-password-validators

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
# https://docs.djangoproject.com/en/5.1/topics/i18n/

LANGUAGE_CODE = 'de-ch'

TIME_ZONE = 'UTC'

USE_I18N = True

USE_TZ = True


# Static files (CSS, JavaScript, Images)
# https://docs.djangoproject.com/en/5.1/howto/static-files/

STATIC_URL = '/static/'
STATICFILES_DIRS = [
    BASE_DIR / "static",  # Adjust this to your static files directory
]
STATIC_ROOT = BASE_DIR / "staticfiles"  # This is where collected static files will go


# Default primary key field type
# https://docs.djangoproject.com/en/5.1/ref/settings/#default-auto-field

DEFAULT_AUTO_FIELD = 'django.db.models.BigAutoField'

# E-Mail configuration

EMAIL_HOST = env('EMAIL_HOST')
EMAIL_PORT = env('EMAIL_PORT')
EMAIL_HOST_USER = env('EMAIL_HOST_USER')
EMAIL_HOST_PASSWORD = env('EMAIL_HOST_PASSWORD')
EMAIL_USE_SSL = env('EMAIL_USE_SSL')
DEFAULT_FROM_EMAIL = 'admin@mileja.ch'
SERVER_EMAIL = 'admin@mileja.ch'

# default date input format
DATE_INPUT_FORMATS = ['%d.%m.%Y']

# enable WhiteNoise to manage static files
WHITENOISE_USE_FINDERS = True  # Optional: allows WhiteNoise to use Django's static files finders

# OIDC / Authentik SSO (Admin only)
OIDC_OP_BASE_URL = env('OIDC_OP_BASE_URL', default='https://auth.sanatify.ch')
OIDC_RP_CLIENT_ID = env('OIDC_CLIENT_ID', default='mileja-yoga')
OIDC_RP_CLIENT_SECRET = env('OIDC_CLIENT_SECRET', default='')
OIDC_OP_AUTHORIZATION_ENDPOINT = f'{OIDC_OP_BASE_URL}/application/o/authorize/'
OIDC_OP_TOKEN_ENDPOINT = f'{OIDC_OP_BASE_URL}/application/o/token/'
OIDC_OP_USER_ENDPOINT = f'{OIDC_OP_BASE_URL}/application/o/userinfo/'
OIDC_OP_JWKS_ENDPOINT = f'{OIDC_OP_BASE_URL}/application/o/mileja-yoga/jwks/'
OIDC_RP_SIGN_ALGO = 'RS256'
OIDC_RP_SCOPES = 'openid profile email groups'
OIDC_OP_LOGOUT_ENDPOINT = f'{OIDC_OP_BASE_URL}/application/o/mileja-yoga/end-session/'
LOGIN_REDIRECT_URL = '/admin/'
LOGOUT_REDIRECT_URL = '/admin/'

# Shared Secret fuer die interne Workbench-API (X-API-KEY-Header)
WORKBENCH_API_KEY = env('WORKBENCH_API_KEY', default='')

# Stripe
STRIPE_PUBLIC_KEY = env('STRIPE_PUBLIC_KEY', default='')
STRIPE_SECRET_KEY = env('STRIPE_SECRET_KEY', default='')
STRIPE_WEBHOOK_SECRET = env('STRIPE_WEBHOOK_SECRET', default='')
STRIPE_PRICE_1_CREDIT = env('STRIPE_PRICE_1_CREDIT', default='')
STRIPE_PRICE_5_CREDITS = env('STRIPE_PRICE_5_CREDITS', default='')
STRIPE_PRICE_10_CREDITS = env('STRIPE_PRICE_10_CREDITS', default='')

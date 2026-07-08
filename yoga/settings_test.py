"""Temporaeres Test-Settings: nutzt SQLite statt der Prod-MySQL, damit
`manage.py test` ohne DB-Privilegien / MySQL-Netzwerk laeuft."""
from .settings import *  # noqa: F401,F403

DATABASES = {
    'default': {
        'ENGINE': 'django.db.backends.sqlite3',
        'NAME': ':memory:',
    }
}

from django.apps import AppConfig


class CourseConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'course'

    def ready(self):
        from . import waitlist  # noqa: F401  registriert die Signal-Handler (Platz frei)

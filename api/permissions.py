from django.conf import settings
from rest_framework.permissions import BasePermission


class HasWorkbenchApiKey(BasePermission):
    """Erlaubt Zugriff nur mit gueltigem Shared-Secret im ``X-API-KEY``-Header.

    Der erwartete Schluessel steht in ``settings.WORKBENCH_API_KEY`` (aus .env).
    Ist serverseitig kein Schluessel gesetzt, wird der Zugriff verweigert
    (fail-closed), damit ein leerer Key nicht versehentlich alles oeffnet.
    """

    message = 'Ungueltiger oder fehlender API-Key.'

    def has_permission(self, request, view):
        expected = getattr(settings, 'WORKBENCH_API_KEY', '')
        if not expected:
            return False
        provided = request.META.get('HTTP_X_API_KEY', '')
        return provided == expected

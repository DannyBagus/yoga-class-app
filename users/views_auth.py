from django.contrib.auth import logout
from django.shortcuts import redirect
from django.conf import settings


def sso_logout(request):
    """Logout from Django and redirect to Authentik end-session."""
    logout(request)
    authentik_logout_url = getattr(settings, 'OIDC_OP_LOGOUT_ENDPOINT', '')
    if authentik_logout_url:
        return redirect(authentik_logout_url)
    return redirect('/')

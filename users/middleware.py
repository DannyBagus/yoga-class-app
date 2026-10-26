from urllib.parse import urlencode

from django.conf import settings
from django.http import HttpResponse
from django.shortcuts import redirect
from django.urls import reverse

from .models import Profile


class RequirePhoneMiddleware:
    """Zwingt eingeloggte Kundinnen ohne Natelnummer auf das Erfassungsformular.

    Greift direkt nach dem Login und ebenso in bereits laufenden Sessions
    (jeder Request wird geprueft). Staff-User (OIDC-Admins) sind ausgenommen,
    ebenso technische Pfade, damit Admin, SSO, API und Stripe-Webhook nie
    blockiert werden.
    """

    EXEMPT_PREFIXES = ('/admin/', '/oidc/', '/api/', '/stripe/webhook/')

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        if self._must_enter_phone(request):
            return self._redirect_to_phone_form(request)
        return self.get_response(request)

    def _must_enter_phone(self, request):
        user = request.user
        if not user.is_authenticated or user.is_staff:
            return False
        path = request.path
        exempt = self.EXEMPT_PREFIXES + (settings.STATIC_URL, reverse('phone'), reverse('logout'))
        if path.startswith(exempt):
            return False
        return not Profile.objects.filter(user=user).exclude(phone='').exists()

    def _redirect_to_phone_form(self, request):
        phone_url = reverse('phone')
        if request.headers.get('HX-Request'):
            # HTMX-Partial: Ganzseiten-Redirect statt Formular im Partial-Container.
            next_url = request.headers.get('HX-Current-URL', '')
            target = f'{phone_url}?{urlencode({"next": next_url})}' if next_url else phone_url
            return HttpResponse(headers={'HX-Redirect': target})
        if request.method == 'GET':
            return redirect(f'{phone_url}?{urlencode({"next": request.get_full_path()})}')
        return redirect(phone_url)

from django.contrib import admin
from django.urls import path, include
from django.shortcuts import redirect

from users.views_auth import sso_logout
from users.stripe_views import stripe_webhook

urlpatterns = [
    # SSO overrides for admin (must come BEFORE admin.site.urls)
    path('admin/login/', lambda r: redirect('oidc_authentication_init')),
    path('admin/logout/', sso_logout),
    path('admin/password_change/', lambda r: redirect('https://auth.sanatify.ch/if/user/#/settings')),
    path('admin/', admin.site.urls),
    # OIDC callback
    path('oidc/', include('mozilla_django_oidc.urls')),
    # Stripe webhook (before catch-all)
    path('stripe/webhook/', stripe_webhook, name='stripe-webhook'),
    # existing
    path('', include('core.urls')),
]

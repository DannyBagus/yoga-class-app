from mozilla_django_oidc.auth import OIDCAuthenticationBackend


class YogaOIDCBackend(OIDCAuthenticationBackend):
    """
    OIDC Backend für Mileja Yoga.
    Matcht Authentik-User per Email auf Django-User.
    Setzt is_staff=True für alle OIDC-User (nur Admin-Zugang relevant).
    Setzt is_superuser basierend auf Authentik-Gruppe 'geschaeftsfuehrung'.
    """

    def filter_users_by_claims(self, claims):
        email = claims.get('email')
        if not email:
            return self.UserModel.objects.none()
        return self.UserModel.objects.filter(email__iexact=email)

    def create_user(self, claims):
        user = super().create_user(claims)
        self._sync_user(user, claims)
        return user

    def update_user(self, user, claims):
        self._sync_user(user, claims)
        return user

    def _sync_user(self, user, claims):
        user.first_name = claims.get('given_name', '')
        user.last_name = claims.get('family_name', '')
        user.email = claims.get('email', '')
        groups = claims.get('groups', [])
        user.is_staff = True
        user.is_superuser = 'geschaeftsfuehrung' in groups
        user.save(update_fields=['first_name', 'last_name', 'email', 'is_staff', 'is_superuser'])

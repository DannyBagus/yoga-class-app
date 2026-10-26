"""Uebernimmt Natelnummern aus der Workbench fuer User ohne Nummer.

Matching per E-Mail (case-insensitive) ueber den bestehenden Workbench-Endpunkt
``GET /api/customers/profile/?email=`` (liefert die aktive bzw. juengste Akte).
Bereits erfasste Nummern werden NIE ueberschrieben. Nummern, die sich nicht
normalisieren lassen, werden uebersprungen.

Default ist Dry-Run. Erst mit --apply wird geschrieben. Jeder Treffer und jede
Auslassung wird ins Audit-Log geschrieben (Datenmigrationen immer protokollieren).
"""
import json
import urllib.error
import urllib.parse
import urllib.request
from collections import Counter
from pathlib import Path

from django.conf import settings
from django.contrib.auth.models import User
from django.core.exceptions import ValidationError
from django.core.management.base import BaseCommand, CommandError
from django.utils import timezone

from users.models import Profile
from users.phone import normalize_phone

AUDIT_LOG = Path(settings.BASE_DIR) / 'phone_sync.log'
TIMEOUT_SECONDS = 10


class Command(BaseCommand):
    help = "Holt fehlende Natelnummern per E-Mail-Match aus der Workbench (Default: Dry-Run)."

    def add_arguments(self, parser):
        parser.add_argument('--apply', action='store_true',
                            help='Nummern tatsaechlich speichern (sonst nur Dry-Run).')

    def fetch_workbench_phone(self, email):
        """Telefonnummer laut Workbench ('' wenn keine Kundin/keine Nummer)."""
        url = (f"{settings.WORKBENCH_URL.rstrip('/')}/api/customers/profile/?"
               f"{urllib.parse.urlencode({'email': email})}")
        req = urllib.request.Request(url, headers={'X-API-KEY': settings.WORKBENCH_OUTBOUND_API_KEY})
        try:
            with urllib.request.urlopen(req, timeout=TIMEOUT_SECONDS) as resp:
                data = json.load(resp)
        except urllib.error.HTTPError as exc:
            if exc.code == 401:
                raise CommandError('Workbench lehnt den API-Key ab (401). WORKBENCH_OUTBOUND_API_KEY pruefen.')
            raise
        if not data.get('found'):
            return None
        return (data['customer'].get('phone') or '').strip()

    def handle(self, *args, **options):
        if not settings.WORKBENCH_OUTBOUND_API_KEY:
            raise CommandError('WORKBENCH_OUTBOUND_API_KEY ist nicht gesetzt.')

        apply = options['apply']
        mode = 'APPLY' if apply else 'DRY-RUN'
        stamp = timezone.now().isoformat()

        users = (User.objects.filter(is_active=True)
                 .exclude(email='')
                 .exclude(profile__phone__gt='')
                 .order_by('pk'))
        self.stdout.write(f'[{mode}] aktive User ohne Natelnummer: {users.count()}')

        stats = Counter()
        lines = []
        for user in users:
            raw = ''
            try:
                raw = self.fetch_workbench_phone(user.email)
                if raw is None:
                    result, phone = 'not-in-workbench', ''
                elif not raw:
                    result, phone = 'workbench-without-phone', ''
                else:
                    phone = normalize_phone(raw)
                    result = 'updated' if apply else 'would-update'
            except ValidationError:
                result, phone = 'invalid-phone', ''
            except (urllib.error.URLError, ValueError, TimeoutError) as exc:
                result, phone = f'error:{exc}', ''

            if phone and apply:
                Profile.objects.update_or_create(user=user, defaults={'phone': phone})

            stats[result.split(':')[0]] += 1
            lines.append(f'{stamp}\t{mode}\tpk={user.pk}\temail={user.email!r}\t'
                         f'workbench={raw!r}\tphone={phone!r}\tresult={result}')
            if phone or result.startswith(('invalid', 'error')):
                self.stdout.write(f'  - pk={user.pk} <{user.email}> {raw!r} -> {phone or "-"} [{result}]')

        if lines:
            # Audit-Log immer schreiben (auch im Dry-Run zur Nachvollziehbarkeit).
            with open(AUDIT_LOG, 'a', encoding='utf-8') as fh:
                fh.write('\n'.join(lines) + '\n')
            self.stdout.write(f'Audit-Log: {AUDIT_LOG}')

        self.stdout.write('Zusammenfassung: ' + ', '.join(f'{k}={v}' for k, v in sorted(stats.items())))
        if not apply:
            self.stdout.write(self.style.WARNING('Dry-Run: nichts gespeichert. Mit --apply ausfuehren.'))

"""Bereinigt inaktive Fake-/Bot-Accounts.

Loescht inaktive User, die ENTWEDER der Bot-Signatur entsprechen ODER deren
Aktivierungsfenster abgelaufen ist (Token nicht mehr gueltig -> Account kann nie
mehr aktiviert werden). Legitime, erst kuerzlich angelegte, noch unbestaetigte
Registrierungen bleiben dadurch geschuetzt.

Bot-Signatur: Username, Vorname UND Nachname bestehen jeweils aus genau 10
Kleinbuchstaben (Muster der Registrierungs-Bot-Welle ab 30.05.2026).

Default ist Dry-Run. Erst mit --apply wird geloescht. Jede Loeschung wird in
ein Audit-Log geschrieben (destruktive Datenmigrationen immer protokollieren).
"""
import re
import datetime
from pathlib import Path

from django.conf import settings
from django.core.management.base import BaseCommand
from django.contrib.auth.models import User
from django.utils import timezone

BOT_RE = re.compile(r'^[a-z]{10}$')
AUDIT_LOG = Path(settings.BASE_DIR) / 'inactive_user_purge.log'


class Command(BaseCommand):
    help = "Loescht inaktive Bot-/abgelaufene Fake-Accounts (Default: Dry-Run)."

    def add_arguments(self, parser):
        parser.add_argument('--apply', action='store_true',
                            help='Tatsaechlich loeschen (sonst nur Dry-Run).')
        parser.add_argument('--days', type=int, default=3,
                            help='Aktivierungsfenster in Tagen (Default: 3, = Token-Gueltigkeit).')

    @staticmethod
    def is_bot(user):
        return bool(
            BOT_RE.match(user.username or '')
            and BOT_RE.match(user.first_name or '')
            and BOT_RE.match(user.last_name or '')
        )

    def handle(self, *args, **options):
        apply = options['apply']
        cutoff = timezone.now() - datetime.timedelta(days=options['days'])

        inactive = User.objects.filter(is_active=False)
        targets = [
            u for u in inactive
            if self.is_bot(u) or u.date_joined < cutoff
        ]

        mode = 'APPLY' if apply else 'DRY-RUN'
        self.stdout.write(f'[{mode}] inaktiv gesamt={inactive.count()}, '
                         f'zu loeschen={len(targets)}')

        if not targets:
            self.stdout.write('Nichts zu tun.')
            return

        stamp = timezone.now().isoformat()
        lines = []
        for u in targets:
            reason = 'bot-signature' if self.is_bot(u) else 'expired-activation'
            lines.append(
                f'{stamp}\t{mode}\tpk={u.pk}\tusername={u.username!r}\t'
                f'email={u.email!r}\tjoined={u.date_joined.isoformat()}\treason={reason}'
            )
            self.stdout.write(f'  - pk={u.pk} {u.username!r} <{u.email}> [{reason}]')

        # Audit-Log immer schreiben (auch im Dry-Run zur Nachvollziehbarkeit).
        with open(AUDIT_LOG, 'a', encoding='utf-8') as fh:
            fh.write('\n'.join(lines) + '\n')
        self.stdout.write(f'Audit-Log: {AUDIT_LOG}')

        if not apply:
            self.stdout.write(self.style.WARNING(
                'Dry-Run: nichts geloescht. Mit --apply ausfuehren.'))
            return

        ids = [u.pk for u in targets]
        deleted, _ = User.objects.filter(pk__in=ids).delete()
        self.stdout.write(self.style.SUCCESS(
            f'{len(ids)} User geloescht (insgesamt {deleted} Objekte inkl. Relationen).'))

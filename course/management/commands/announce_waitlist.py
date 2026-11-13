"""Kuendigt die Warteliste per E-Mail an (einmalig, 2026-11).

Empfaengerinnen: aktive Kundinnen mit E-Mail, die je einen MamiFit-Kurs
gebucht haben (Buchungen + Absage-Benachrichtigungen, da Buchungen bei einer
Kursabsage geloescht werden). Jede bekommt eine eigene Mail.

    manage.py announce_waitlist                      # Probelauf (Standard)
    manage.py announce_waitlist --test-to a@b.ch     # eine Testmail
    manage.py announce_waitlist --send               # Versand

Jeder Versand wird in eine Log-Datei geschrieben (Zeit, Status, User-ID,
E-Mail). Ein erneuter --send ueberspringt bereits erfolgreich Versendete,
d. h. nach einem Abbruch oder Fehlern einfach nochmals starten.
"""
import os

from django.conf import settings
from django.contrib.auth.models import User
from django.core.management.base import BaseCommand, CommandError
from django.db.models import Q
from django.utils import timezone

from course.cancellation import CUSTOMER_REPLY_TO, SUMMARY_RECIPIENTS, _send_mail

CATEGORY = 'MamiFit'
SUBJECT = 'Neu: Warteliste für ausgebuchte Kurse / New: waiting list for fully booked classes'
TEMPLATE = 'course/emails/waitlist_announcement'


def recipients():
    users = (User.objects
             .filter(is_active=True)
             .exclude(email='')
             .filter(Q(booking__course__category__name=CATEGORY)
                     | Q(cancellationnotice__course__category__name=CATEGORY))
             .distinct()
             .order_by('email'))
    seen, result = set(), []
    for user in users:  # gleiche Adresse bei mehreren Accounts nur einmal
        if user.email.lower() not in seen:
            seen.add(user.email.lower())
            result.append(user)
    return result


class Command(BaseCommand):
    help = 'Kündigt die Warteliste allen Kundinnen an, die je MamiFit gebucht haben.'

    def add_arguments(self, parser):
        parser.add_argument('--send', action='store_true', help='Wirklich versenden')
        parser.add_argument('--test-to', metavar='EMAIL', help='Nur eine Testmail an diese Adresse')
        parser.add_argument('--log', default=os.path.join(settings.BASE_DIR, 'waitlist_announcement.log'),
                            help='Log-Datei (Standard: waitlist_announcement.log)')

    def handle(self, *args, **opts):
        if opts['send'] and opts['test_to']:
            raise CommandError('--send und --test-to schliessen sich aus.')
        users = recipients()

        if opts['test_to']:
            sample = users[0] if users else None
            self._mail(opts['test_to'], sample.first_name if sample else 'Anna', test=True)
            self.stdout.write(f"Testmail an {opts['test_to']} versendet ({len(users)} Empfängerin(nen) geplant).")
            return

        if not opts['send']:
            self.stdout.write(f'DRY-RUN: {len(users)} Empfängerin(nen), es wird nichts versendet.')
            for user in users:
                self.stdout.write(f'  {user.email}  ({user.first_name} {user.last_name})')
            self.stdout.write('Versand mit --send, Testmail mit --test-to <adresse>.')
            return

        already = self._already_sent(opts['log'])
        sent = failed = skipped = 0
        with open(opts['log'], 'a', encoding='utf-8') as log:
            for user in users:
                if user.email.lower() in already:
                    skipped += 1
                    continue
                try:
                    self._mail(user.email, user.first_name)
                    status, error = 'SENT', ''
                    sent += 1
                except Exception as e:  # einzelne Fehler stoppen den Versand nicht
                    status, error = 'FAILED', repr(e)
                    failed += 1
                log.write(f'{timezone.now().isoformat()}\t{status}\t{user.pk}\t{user.email}\t{error}\n')
                log.flush()
        self.stdout.write(f'{sent} versendet, {failed} fehlgeschlagen, '
                          f'{skipped} bereits versendet (übersprungen). Log: {opts["log"]}')

        # Eine Kopie zur Kenntnis ans Team (per SMTP Versendetes landet in
        # keinem Gesendet-Ordner); nur wenn in diesem Lauf etwas rausging.
        if sent:
            for team in SUMMARY_RECIPIENTS:
                self._mail(team, '', prefix='[Kopie] ')
            self.stdout.write(f'Kopie an {", ".join(SUMMARY_RECIPIENTS)} versendet.')

    @staticmethod
    def _already_sent(path):
        if not os.path.exists(path):
            return set()
        with open(path, encoding='utf-8') as f:
            return {parts[3].lower() for parts in (line.rstrip('\n').split('\t') for line in f)
                    if len(parts) >= 4 and parts[1] == 'SENT'}

    @staticmethod
    def _mail(to, first_name, test=False, prefix=''):
        context = {
            'first_name': first_name,
            'courses_url': f"{settings.SITE_URL.rstrip('/')}/kurse/",
        }
        _send_mail(('[TEST] ' if test else prefix) + SUBJECT, TEMPLATE, context, [to],
                   reply_to=CUSTOMER_REPLY_TO)

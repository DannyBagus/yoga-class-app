"""Tests fuer ``manage.py announce_waitlist`` (Ankuendigung der Warteliste an
alle Kundinnen, die je MamiFit gebucht haben)."""
import os
import tempfile
from datetime import time, timedelta
from io import StringIO
from unittest import mock

from django.contrib.auth.models import User
from django.core import mail
from django.core.management import CommandError, call_command
from django.test import TestCase
from django.utils import timezone

from course.models import Booking, CancellationNotice, Category, Courses


class AnnounceWaitlistTest(TestCase):
    def setUp(self):
        mamifit = Category.objects.create(name='MamiFit')
        yoga = Category.objects.create(name='Yoga')
        day = timezone.now().date()
        self.mf1 = Courses.objects.create(name='MamiFit Outdoor', category=mamifit, topic='x',
                                          date=day - timedelta(days=30), start=time(9, 30))
        self.mf2 = Courses.objects.create(name='MamiFit Indoor', category=mamifit, topic='x',
                                          date=day + timedelta(days=3), start=time(9, 30))
        self.yoga = Courses.objects.create(name='Yoga Flow', category=yoga, topic='x',
                                           date=day + timedelta(days=3), start=time(18, 0))
        self.anna = self._user('anna', 'Anna')
        self.berta = self._user('berta', 'Berta')
        self.carla = self._user('carla', 'Carla')
        self.inactive = self._user('ina', 'Ina', is_active=False)
        self.nomail = self._user('nomail', 'Nora', email='')
        # Anna: zweimal MamiFit -> trotzdem nur eine Mail
        Booking.objects.create(user=self.anna, course=self.mf1)
        Booking.objects.create(user=self.anna, course=self.mf2)
        # Berta: Buchung wurde durch eine Kursabsage geloescht, nur die Notice bleibt
        CancellationNotice.objects.create(course=self.mf1, user=self.berta,
                                          credits_before=0, credits_after=1)
        # Carla: nur Yoga -> keine Mail
        Booking.objects.create(user=self.carla, course=self.yoga)
        Booking.objects.create(user=self.inactive, course=self.mf1)
        Booking.objects.create(user=self.nomail, course=self.mf1)

        fd, self.log = tempfile.mkstemp(suffix='.log')
        os.close(fd)
        os.remove(self.log)
        self.addCleanup(lambda: os.path.exists(self.log) and os.remove(self.log))

    def _user(self, username, first_name, email=None, is_active=True):
        return User.objects.create_user(
            username, f'{username}@example.com' if email is None else email, 'pw',
            first_name=first_name, last_name='Muster', is_active=is_active)

    def _run(self, *args):
        out = StringIO()
        call_command('announce_waitlist', *args, '--log', self.log, stdout=out)
        return out.getvalue()

    def _log_lines(self):
        with open(self.log, encoding='utf-8') as f:
            return f.read().splitlines()

    def test_default_is_dry_run(self):
        out = self._run()
        self.assertEqual(mail.outbox, [])
        self.assertIn('DRY-RUN', out)
        self.assertIn('2 Empfängerin(nen)', out)
        self.assertIn('anna@example.com', out)
        self.assertIn('berta@example.com', out)
        self.assertNotIn('carla@example.com', out)
        self.assertNotIn('ina@example.com', out)
        self.assertFalse(os.path.exists(self.log))

    def test_test_mail_goes_only_to_given_address(self):
        self._run('--test-to', 'daniel@example.org')
        self.assertEqual(len(mail.outbox), 1)
        msg = mail.outbox[0]
        self.assertEqual(msg.to, ['daniel@example.org'])
        self.assertTrue(msg.subject.startswith('[TEST] '))
        self.assertFalse(os.path.exists(self.log))

    def test_send_one_personal_mail_per_recipient(self):
        out = self._run('--send')
        customers = [m for m in mail.outbox if not m.subject.startswith('[Kopie]')]
        self.assertEqual(sorted(m.to[0] for m in customers), ['anna@example.com', 'berta@example.com'])
        for m in customers:
            self.assertEqual(len(m.to), 1)
            self.assertFalse(m.cc)
            self.assertFalse(m.bcc)
            self.assertEqual(m.from_email, 'admin@mileja.ch')
            self.assertEqual(m.reply_to, ['hebammen@mileja.ch'])
        self.assertIn('2 versendet', out)

    def test_mail_content(self):
        self._run('--send')
        msg = next(m for m in mail.outbox if m.to == ['anna@example.com'])
        self.assertIn('Neu: Warteliste', msg.subject)
        self.assertIn('New: waiting list', msg.subject)
        html = msg.alternatives[0][0]
        for text in (msg.body, html):
            self.assertIn('Hallo Anna', text)
            self.assertIn('Hi Anna', text)
            self.assertIn('Auf die Warteliste', text)
            self.assertIn('Jetzt einschreiben', text)
            self.assertIn('first come, first serve', text.lower())
            self.assertIn('mindestens 1 Credit', text)
            # Bitte ums Abmelden, auch nach Ablauf der 24h-Frist
            self.assertIn('Bitte melde Dich ab', text)
            self.assertIn('auch wenn die 24 Stunden vor Kursbeginn schon vorbei sind', text)
            self.assertIn('Please cancel your booking', text)
            self.assertIn('even if it', text)
            self.assertIn('https://kurse.mileja.ch/kurse/', text)

    def test_one_copy_to_team_after_sending(self):
        out = self._run('--send')
        copies = [m for m in mail.outbox if m.to == ['hebammen@mileja.ch']]
        self.assertEqual(len(copies), 1)
        self.assertTrue(copies[0].subject.startswith('[Kopie] Neu: Warteliste'))
        self.assertIn('Kopie an hebammen@mileja.ch', out)
        # keine Kopie bei Probelauf, Testmail oder wenn nichts Neues versendet wurde
        mail.outbox.clear()
        self._run('--send')
        self._run()
        self._run('--test-to', 'daniel@example.org')
        self.assertFalse([m for m in mail.outbox if m.to == ['hebammen@mileja.ch']])

    def test_log_and_rerun_skips_already_sent(self):
        self._run('--send')
        lines = self._log_lines()
        self.assertEqual(len(lines), 2)
        self.assertTrue(all('\tSENT\t' in line for line in lines))
        self.assertTrue(any('anna@example.com' in line for line in lines))

        mail.outbox.clear()
        out = self._run('--send')
        self.assertEqual(mail.outbox, [])
        self.assertIn('2 bereits versendet (übersprungen)', out)

    def test_failure_is_logged_and_retried(self):
        from django.core.mail import EmailMultiAlternatives
        real_send = EmailMultiAlternatives.send

        def flaky(msg, *args, **kwargs):
            if msg.to == ['berta@example.com']:
                raise OSError('mailbox full')
            return real_send(msg, *args, **kwargs)

        with mock.patch('django.core.mail.EmailMultiAlternatives.send', autospec=True, side_effect=flaky):
            out = self._run('--send')
        self.assertEqual([m.to for m in mail.outbox], [['anna@example.com'], ['hebammen@mileja.ch']])
        self.assertIn('1 fehlgeschlagen', out)
        self.assertTrue(any('\tFAILED\t' in line and 'berta@example.com' in line for line in self._log_lines()))

        mail.outbox.clear()
        self._run('--send')
        self.assertEqual([m.to for m in mail.outbox], [['berta@example.com'], ['hebammen@mileja.ch']])

    def test_send_and_test_to_are_exclusive(self):
        with self.assertRaises(CommandError):
            self._run('--send', '--test-to', 'daniel@example.org')
        self.assertEqual(mail.outbox, [])

"""Tests der Warteliste (Plan: tasks/todo.md, 13.11.2026).

Schnittstelle, die diese Tests festlegen:
- ``course.models.WaitlistEntry`` (status waiting/booked/left/course_cancelled,
  notified_count, last_notified_at, booked_at; related_name ``waitlist_entries``)
- ``course.waitlist``: join, leave, waiting_count, notify_seat_freed, claim,
  ClaimResult, WaitlistError, notify_course_cancelled, claim_url, entry_from_token
- Ausloeser: steigt ``Courses.capacity``, gehen nach dem Commit Mails an alle
  Wartenden (ausser bei abgesagten oder schon begonnenen Kursen).
"""
import re
from datetime import time, timedelta
from html.parser import HTMLParser
from unittest import mock

from django.contrib.auth.models import User
from django.core import mail
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from course import waitlist
from course.cancellation import cancel_course
from course.models import Booking, Category, Courses, WaitlistEntry
from course.waitlist import ClaimResult, WaitlistError
from users.models import Credits

CLAIM_URL_RE = re.compile(r'https://kurse\.mileja\.ch(/kurse/warteliste/[^/\s"<]+/)')
BACKEND = 'django.contrib.auth.backends.ModelBackend'


class _FormScraper(HTMLParser):
    """Liest alle Feldwerte des Admin-Formulars aus dem HTML (wie ein Browser)."""

    def __init__(self):
        super().__init__()
        self.data = {}
        self._select = None
        self._textarea = None

    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        name = a.get('name')
        if tag == 'input' and name:
            kind = a.get('type', 'text')
            if kind in ('submit', 'button', 'image', 'file'):
                return
            if kind in ('checkbox', 'radio') and 'checked' not in a:
                return
            self.data[name] = a.get('value', 'on' if kind == 'checkbox' else '')
        elif tag == 'select' and name:
            self._select = name
            self.data.setdefault(name, '')
        elif tag == 'option' and self._select and 'selected' in a:
            self.data[self._select] = a.get('value', '')
        elif tag == 'textarea' and name:
            self._textarea = name
            self.data[name] = ''

    def handle_endtag(self, tag):
        if tag == 'select':
            self._select = None
        elif tag == 'textarea':
            self._textarea = None

    def handle_data(self, data):
        if self._textarea:
            self.data[self._textarea] += data


class WaitlistBase(TestCase):
    """Ausgebuchter MamiFit-Kurs (0 frei, Anna + Berta gebucht),
    Carla und Dora auf der Warteliste."""

    def setUp(self):
        self.mamifit = Category.objects.create(name='MamiFit')
        self.course = Courses.objects.create(
            name='MamiFit Outdoor', category=self.mamifit, topic='Kraft',
            date=timezone.now().date() + timedelta(days=3), start=time(9, 30), capacity=0,
        )
        self.other_course = Courses.objects.create(
            name='MamiFit Indoor', category=self.mamifit, topic='Core',
            date=timezone.now().date() + timedelta(days=4), start=time(10, 0), capacity=3,
        )
        self.anna = self._customer('anna', 'Anna', 2)
        self.berta = self._customer('berta', 'Berta', 1)
        self.carla = self._customer('carla', 'Carla', 1)
        self.dora = self._customer('dora', 'Dora', 2)
        Booking.objects.create(user=self.anna, course=self.course)
        Booking.objects.create(user=self.berta, course=self.course)
        self.carla_entry = WaitlistEntry.objects.create(course=self.course, user=self.carla)
        self.dora_entry = WaitlistEntry.objects.create(course=self.course, user=self.dora)

    def _customer(self, username, first_name, credits):
        user = User.objects.create_user(username, f'{username}@example.com', 'pw',
                                        first_name=first_name, last_name='Muster')
        Credits.objects.filter(user=user).update(number=credits)
        user.profile.phone = '+41791234567'
        user.profile.save()
        return user

    def _credits(self, user):
        return Credits.objects.get(user=user).number

    def _capacity(self, course=None):
        return Courses.objects.get(pk=(course or self.course).pk).capacity

    def _status(self, entry):
        entry.refresh_from_db()
        return entry.status

    def _free_seat(self, course=None, seats=1):
        """Platz freigeben wie es die Views tun: capacity hochzaehlen und speichern."""
        course = Courses.objects.get(pk=(course or self.course).pk)
        with self.captureOnCommitCallbacks(execute=True):
            course.capacity += seats
            course.save()

    def _seat_freed_mails(self):
        return [m for m in mail.outbox if 'Platz frei' in m.subject]

    def _claim_path(self, user):
        msg = next(m for m in self._seat_freed_mails() if m.to == [user.email])
        return CLAIM_URL_RE.search(msg.body).group(1)


# --- Modell -----------------------------------------------------------------

class WaitlistModelTest(WaitlistBase):
    def test_defaults(self):
        self.assertEqual(self.carla_entry.status, WaitlistEntry.WAITING)
        self.assertEqual(self.carla_entry.notified_count, 0)
        self.assertIsNone(self.carla_entry.last_notified_at)
        self.assertIsNone(self.carla_entry.booked_at)
        self.assertIsNotNone(self.carla_entry.created_at)

    def test_one_entry_per_user_and_course(self):
        from django.db import IntegrityError
        with self.assertRaises(IntegrityError):
            WaitlistEntry.objects.create(course=self.course, user=self.carla)

    def test_waiting_count_ignores_other_states(self):
        self.assertEqual(waitlist.waiting_count(self.course), 2)
        WaitlistEntry.objects.filter(pk=self.dora_entry.pk).update(status=WaitlistEntry.LEFT)
        self.assertEqual(waitlist.waiting_count(self.course), 1)


# --- Eintragen / Austragen (Service) ----------------------------------------

class JoinLeaveServiceTest(WaitlistBase):
    def setUp(self):
        super().setUp()
        self.emma = self._customer('emma', 'Emma', 1)

    def test_join_full_course(self):
        entry = waitlist.join(self.emma, self.course)
        self.assertEqual(entry.status, WaitlistEntry.WAITING)
        self.assertEqual(waitlist.waiting_count(self.course), 3)

    def test_join_is_idempotent(self):
        first = waitlist.join(self.emma, self.course)
        second = waitlist.join(self.emma, self.course)
        self.assertEqual(first.pk, second.pk)
        self.assertEqual(WaitlistEntry.objects.filter(user=self.emma).count(), 1)

    def test_join_requires_credit(self):
        Credits.objects.filter(user=self.emma).update(number=0)
        with self.assertRaisesMessage(WaitlistError, 'mindestens 1 Credit'):
            waitlist.join(self.emma, self.course)
        self.assertFalse(WaitlistEntry.objects.filter(user=self.emma).exists())

    def test_join_course_with_free_seats_is_refused(self):
        with self.assertRaisesMessage(WaitlistError, 'noch Plätze frei'):
            waitlist.join(self.emma, self.other_course)

    def test_join_when_already_booked_is_refused(self):
        with self.assertRaisesMessage(WaitlistError, 'bereits angemeldet'):
            waitlist.join(self.anna, self.course)

    def test_join_cancelled_course_is_refused(self):
        Courses.objects.filter(pk=self.course.pk).update(is_cancelled=True)
        self.course.refresh_from_db()
        with self.assertRaisesMessage(WaitlistError, 'abgesagt'):
            waitlist.join(self.emma, self.course)

    def test_join_started_course_is_refused(self):
        Courses.objects.filter(pk=self.course.pk).update(date=timezone.now().date() - timedelta(days=1))
        self.course.refresh_from_db()
        with self.assertRaisesMessage(WaitlistError, 'bereits begonnen'):
            waitlist.join(self.emma, self.course)

    def test_leave_and_rejoin(self):
        self.assertTrue(waitlist.leave(self.carla, self.course))
        self.assertEqual(self._status(self.carla_entry), WaitlistEntry.LEFT)
        self.assertEqual(waitlist.waiting_count(self.course), 1)
        self.assertFalse(waitlist.leave(self.carla, self.course))

        entry = waitlist.join(self.carla, self.course)
        self.assertEqual(entry.pk, self.carla_entry.pk)
        self.assertEqual(entry.status, WaitlistEntry.WAITING)


# --- "Platz frei"-Mail --------------------------------------------------------

class SeatFreedMailTest(WaitlistBase):
    def test_mail_to_every_waiting_customer_individually(self):
        self._free_seat()
        mails = self._seat_freed_mails()
        self.assertEqual(sorted(m.to[0] for m in mails), ['carla@example.com', 'dora@example.com'])
        for m in mails:
            self.assertEqual(len(m.to), 1)  # keine gemeinsame Mail, keine fremden Adressen
            self.assertFalse(m.cc)
            self.assertFalse(m.bcc)
            self.assertEqual(m.from_email, 'admin@mileja.ch')

    def test_mail_content_is_short_and_bilingual(self):
        self._free_seat()
        msg = next(m for m in self._seat_freed_mails() if m.to == ['carla@example.com'])
        date = self.course.date.strftime('%d.%m.%Y')
        self.assertIn('MamiFit - MamiFit Outdoor', msg.subject)
        self.assertIn(date, msg.subject)
        self.assertIn('Spot available', msg.subject)
        html = msg.alternatives[0][0]
        for text in (msg.body, html):
            self.assertIn('MamiFit - MamiFit Outdoor', text)
            self.assertIn(date, text)
            self.assertIn('09:30', text)
            self.assertIn('Jetzt einschreiben', text)
            self.assertIn('Book now', text)
            self.assertIn('first come, first serve', text.lower())
            self.assertIn('Wer zuerst klickt', text)
            self.assertIn('first person to click', text)
            # keine anderen Wartenden in der Mail
            self.assertNotIn('Dora', text)
        self.assertIn(self._claim_path(self.carla), html)

    def test_personal_links_differ(self):
        self._free_seat()
        self.assertNotEqual(self._claim_path(self.carla), self._claim_path(self.dora))

    def test_notification_counter(self):
        self._free_seat()
        self.carla_entry.refresh_from_db()
        self.assertEqual(self.carla_entry.notified_count, 1)
        self.assertIsNotNone(self.carla_entry.last_notified_at)

    def test_fires_again_for_every_freed_seat(self):
        self._free_seat()
        self._free_seat()
        self.assertEqual(len(self._seat_freed_mails()), 4)
        self.carla_entry.refresh_from_db()
        self.assertEqual(self.carla_entry.notified_count, 2)

    def test_only_waiting_entries_are_notified(self):
        WaitlistEntry.objects.filter(pk=self.dora_entry.pk).update(status=WaitlistEntry.LEFT)
        self._free_seat()
        self.assertEqual([m.to for m in self._seat_freed_mails()], [['carla@example.com']])

    def test_no_mail_when_capacity_unchanged_or_lower(self):
        with self.captureOnCommitCallbacks(execute=True):
            self.course.topic = 'Neues Thema'
            self.course.save()
        Courses.objects.filter(pk=self.course.pk).update(capacity=2)
        course = Courses.objects.get(pk=self.course.pk)
        with self.captureOnCommitCallbacks(execute=True):
            course.capacity = 1
            course.save()
        self.assertEqual(self._seat_freed_mails(), [])

    def test_no_mail_for_new_course(self):
        with self.captureOnCommitCallbacks(execute=True):
            Courses.objects.create(name='Neu', category=self.mamifit, topic='x', capacity=7)
        self.assertEqual(self._seat_freed_mails(), [])

    def test_no_mail_for_started_course(self):
        Courses.objects.filter(pk=self.course.pk).update(date=timezone.now().date() - timedelta(days=1))
        self._free_seat()
        self.assertEqual(self._seat_freed_mails(), [])

    def test_no_mail_for_cancelled_course(self):
        Courses.objects.filter(pk=self.course.pk).update(is_cancelled=True)
        self._free_seat()
        self.assertEqual(self._seat_freed_mails(), [])

    def test_mail_is_sent_only_after_commit(self):
        course = Courses.objects.get(pk=self.course.pk)
        with self.captureOnCommitCallbacks(execute=False) as callbacks:
            course.capacity = 1
            course.save()
        self.assertEqual(self._seat_freed_mails(), [])
        self.assertTrue(callbacks)

    def test_one_failing_mail_does_not_stop_the_others(self):
        from django.core.mail import EmailMultiAlternatives
        real_send = EmailMultiAlternatives.send

        def flaky(msg, *args, **kwargs):
            if msg.to == ['carla@example.com']:
                raise OSError('mailbox full')
            return real_send(msg, *args, **kwargs)

        with mock.patch('django.core.mail.EmailMultiAlternatives.send', autospec=True, side_effect=flaky):
            self._free_seat()
        self.assertEqual([m.to for m in self._seat_freed_mails()], [['dora@example.com']])
        self.carla_entry.refresh_from_db()
        self.assertEqual(self.carla_entry.notified_count, 0)

    def test_customer_without_email_is_skipped(self):
        User.objects.filter(pk=self.carla.pk).update(email='')
        self._free_seat()
        self.assertEqual([m.to for m in self._seat_freed_mails()], [['dora@example.com']])


# --- Ausloeser: alle Wege, auf denen ein Platz frei wird ----------------------

class SeatFreedTriggerTest(WaitlistBase):
    def _assert_waitlist_notified(self):
        self.assertEqual(sorted(m.to[0] for m in self._seat_freed_mails()),
                         ['carla@example.com', 'dora@example.com'])

    def test_customer_cancels_booking(self):
        self.client.force_login(self.anna, backend=BACKEND)
        with self.captureOnCommitCallbacks(execute=True):
            self.client.get(reverse('cancel-booking') + f'?course={self.course.pk}')
        self.assertEqual(self._capacity(), 1)
        self._assert_waitlist_notified()

    def _admin(self):
        admin_user = User.objects.create_superuser('boss', 'boss@example.com', 'pw')
        self.client.force_login(admin_user, backend=BACKEND)

    def _booking_action(self, action, extra=None):
        self._admin()
        booking = Booking.objects.get(user=self.anna, course=self.course)
        data = {'action': action, '_selected_action': [booking.pk], **(extra or {})}
        with self.captureOnCommitCallbacks(execute=True):
            self.client.post(reverse('admin:course_booking_changelist'), data)

    def test_admin_cancel_with_refund(self):
        self._booking_action('cancel_with_refund')
        self.assertEqual(self._capacity(), 1)
        self._assert_waitlist_notified()

    def test_admin_cancel_without_refund(self):
        self._booking_action('cancel_without_refund')
        self.assertEqual(self._capacity(), 1)
        self._assert_waitlist_notified()

    def test_admin_rebook_frees_seat_in_old_course(self):
        self._booking_action('rebook_to_course', {'apply': '1', 'target_course': self.other_course.pk})
        self.assertEqual(self._capacity(), 1)
        self._assert_waitlist_notified()

    def _admin_change_form(self):
        self._admin()
        url = reverse('admin:course_courses_change', args=[self.course.pk])
        scraper = _FormScraper()
        scraper.feed(self.client.get(url).content.decode())
        data = scraper.data
        data.pop('csrfmiddlewaretoken', None)
        data['_save'] = 'Sichern'
        return url, data

    def test_admin_increases_capacity(self):
        url, data = self._admin_change_form()
        data['capacity'] = '2'
        with self.captureOnCommitCallbacks(execute=True):
            resp = self.client.post(url, data)
        self.assertEqual(resp.status_code, 302)
        self.assertEqual(self._capacity(), 2)
        self._assert_waitlist_notified()

    def test_admin_saves_without_change_sends_nothing(self):
        url, data = self._admin_change_form()
        with self.captureOnCommitCallbacks(execute=True):
            resp = self.client.post(url, data)
        self.assertEqual(resp.status_code, 302)
        self.assertEqual(self._seat_freed_mails(), [])

    def test_admin_deletes_booking_inline_frees_seat(self):
        url, data = self._admin_change_form()
        anna_booking = Booking.objects.get(user=self.anna, course=self.course)
        idx = next(k.split('-')[1] for k, v in data.items()
                   if re.fullmatch(r'bookings-\d+-id', k) and v == str(anna_booking.pk))
        data[f'bookings-{idx}-DELETE'] = 'on'
        with self.captureOnCommitCallbacks(execute=True):
            resp = self.client.post(url, data)
        self.assertEqual(resp.status_code, 302)
        self.assertFalse(Booking.objects.filter(pk=anna_booking.pk).exists())
        self.assertEqual(self._capacity(), 1)
        self._assert_waitlist_notified()

    def test_course_cancellation_sends_no_seat_freed_mail(self):
        with self.captureOnCommitCallbacks(execute=True):
            cancel_course(self.course.pk)
        self.assertEqual(self._seat_freed_mails(), [])


# --- Platz sichern (Service) ------------------------------------------------

class ClaimServiceTest(WaitlistBase):
    def setUp(self):
        super().setUp()
        Courses.objects.filter(pk=self.course.pk).update(capacity=1)

    def test_success_books_and_charges_one_credit(self):
        self.assertEqual(waitlist.claim(self.carla_entry), ClaimResult.SUCCESS)
        self.assertTrue(Booking.objects.filter(user=self.carla, course=self.course).exists())
        self.assertEqual(self._credits(self.carla), 0)
        self.assertEqual(self._capacity(), 0)
        self.carla_entry.refresh_from_db()
        self.assertEqual(self.carla_entry.status, WaitlistEntry.BOOKED)
        self.assertIsNotNone(self.carla_entry.booked_at)

    def test_second_claimer_is_too_late_and_stays_waiting(self):
        waitlist.claim(self.carla_entry)
        self.assertEqual(waitlist.claim(self.dora_entry), ClaimResult.TOO_LATE)
        self.assertFalse(Booking.objects.filter(user=self.dora, course=self.course).exists())
        self.assertEqual(self._credits(self.dora), 2)
        self.assertEqual(self._capacity(), 0)
        self.assertEqual(self._status(self.dora_entry), WaitlistEntry.WAITING)

    def test_two_seats_two_winners(self):
        Courses.objects.filter(pk=self.course.pk).update(capacity=2)
        self.assertEqual(waitlist.claim(self.carla_entry), ClaimResult.SUCCESS)
        self.assertEqual(waitlist.claim(self.dora_entry), ClaimResult.SUCCESS)
        self.assertEqual(self._capacity(), 0)

    def test_no_credits(self):
        Credits.objects.filter(user=self.carla).update(number=0)
        self.assertEqual(waitlist.claim(self.carla_entry), ClaimResult.NO_CREDITS)
        self.assertFalse(Booking.objects.filter(user=self.carla, course=self.course).exists())
        self.assertEqual(self._capacity(), 1)
        self.assertEqual(self._status(self.carla_entry), WaitlistEntry.WAITING)

    def test_already_booked_is_idempotent(self):
        waitlist.claim(self.carla_entry)
        self.carla_entry.refresh_from_db()
        self.assertEqual(waitlist.claim(self.carla_entry), ClaimResult.ALREADY_BOOKED)
        self.assertEqual(Booking.objects.filter(user=self.carla, course=self.course).count(), 1)
        self.assertEqual(self._credits(self.carla), 0)

    def test_cancelled_course(self):
        Courses.objects.filter(pk=self.course.pk).update(is_cancelled=True)
        self.assertEqual(waitlist.claim(self.carla_entry), ClaimResult.COURSE_CANCELLED)
        self.assertEqual(self._credits(self.carla), 1)

    def test_started_course(self):
        Courses.objects.filter(pk=self.course.pk).update(date=timezone.now().date() - timedelta(days=1))
        self.assertEqual(waitlist.claim(self.carla_entry), ClaimResult.COURSE_STARTED)
        self.assertEqual(self._credits(self.carla), 1)

    def test_left_waitlist(self):
        waitlist.leave(self.carla, self.course)
        self.carla_entry.refresh_from_db()
        self.assertEqual(waitlist.claim(self.carla_entry), ClaimResult.NOT_WAITING)
        self.assertEqual(self._capacity(), 1)

    def test_claim_does_not_trigger_new_seat_freed_mail(self):
        with self.captureOnCommitCallbacks(execute=True):
            waitlist.claim(self.carla_entry)
        self.assertEqual(self._seat_freed_mails(), [])


# --- Platz sichern (Zwischenseite aus der Mail) ------------------------------

class ClaimViewTest(WaitlistBase):
    def setUp(self):
        super().setUp()
        self._free_seat()
        self.carla_url = self._claim_path(self.carla)
        self.dora_url = self._claim_path(self.dora)

    def test_get_shows_course_and_button_without_booking(self):
        resp = self.client.get(self.carla_url)
        self.assertContains(resp, 'MamiFit - MamiFit Outdoor')
        self.assertContains(resp, self.course.date.strftime('%d.%m.%Y'))
        self.assertContains(resp, '09:30')
        self.assertContains(resp, 'Platz jetzt sichern')
        self.assertContains(resp, 'method="post"')
        self.assertFalse(Booking.objects.filter(user=self.carla, course=self.course).exists())
        self.assertEqual(self._credits(self.carla), 1)

    def test_no_login_needed_and_first_wins(self):
        resp = self.client.post(self.carla_url)
        self.assertContains(resp, 'waitlist-result-success')
        self.assertContains(resp, 'Du hast den Platz')
        self.assertContains(resp, 'You got the spot')
        self.assertContains(resp, 'Credit(s)')
        self.assertTrue(Booking.objects.filter(user=self.carla, course=self.course).exists())

        resp = self.client.post(self.dora_url)
        self.assertContains(resp, 'waitlist-result-failure')
        self.assertContains(resp, 'Leider war jemand anderes schneller als du')
        self.assertContains(resp, 'Du verbleibst auf der Warteliste')
        self.assertContains(resp, 'someone else was faster')
        self.assertFalse(Booking.objects.filter(user=self.dora, course=self.course).exists())

    def test_double_click_shows_success_again(self):
        self.client.post(self.carla_url)
        resp = self.client.post(self.carla_url)
        self.assertContains(resp, 'waitlist-result-success')
        self.assertEqual(Booking.objects.filter(user=self.carla, course=self.course).count(), 1)

    def test_no_credits_page_links_to_purchase(self):
        Credits.objects.filter(user=self.carla).update(number=0)
        resp = self.client.post(self.carla_url)
        self.assertContains(resp, 'waitlist-result-failure')
        self.assertContains(resp, 'keine Credits')
        self.assertContains(resp, reverse('my-account'))
        self.assertEqual(self._status(self.carla_entry), WaitlistEntry.WAITING)

    def test_started_course_page(self):
        Courses.objects.filter(pk=self.course.pk).update(date=timezone.now().date() - timedelta(days=1))
        resp = self.client.get(self.carla_url)
        self.assertContains(resp, 'bereits begonnen')
        self.assertNotContains(resp, 'Platz jetzt sichern')

    def test_invalid_token(self):
        resp = self.client.get('/kurse/warteliste/manipuliert/')
        self.assertContains(resp, 'ungültig oder abgelaufen', status_code=404)
        resp = self.client.post(self.carla_url[:-2] + 'x/')
        self.assertEqual(resp.status_code, 404)
        self.assertFalse(Booking.objects.filter(user=self.carla, course=self.course).exists())

    def test_token_round_trip(self):
        self.assertEqual(waitlist.entry_from_token(self.carla_url.split('/')[-2]), self.carla_entry)
        self.assertTrue(waitlist.claim_url(self.carla_entry).endswith(self.carla_url))


# --- Kursabsage ---------------------------------------------------------------

class CourseCancelledWaitlistTest(WaitlistBase):
    def test_waitlist_gets_short_info_mail(self):
        cancel_course(self.course.pk)
        info = [m for m in mail.outbox if m.to in (['carla@example.com'], ['dora@example.com'])]
        self.assertEqual(len(info), 2)
        msg = info[0]
        self.assertIn('Course cancelled', msg.subject)
        for text in (msg.body, msg.alternatives[0][0]):
            self.assertIn('MamiFit - MamiFit Outdoor', text)
            self.assertIn('abgesagt', text)
            self.assertIn('Warteliste', text)
            self.assertIn('waiting list', text)

    def test_entries_are_closed_not_deleted(self):
        cancel_course(self.course.pk)
        self.assertEqual(self._status(self.carla_entry), WaitlistEntry.COURSE_CANCELLED)
        self.assertEqual(self._status(self.dora_entry), WaitlistEntry.COURSE_CANCELLED)

    def test_left_entries_get_no_mail(self):
        waitlist.leave(self.dora, self.course)
        cancel_course(self.course.pk)
        self.assertFalse([m for m in mail.outbox if m.to == ['dora@example.com']])
        self.assertEqual(self._status(self.dora_entry), WaitlistEntry.LEFT)


# --- Kursliste (Frontend) ---------------------------------------------------

class WaitlistFrontendTest(WaitlistBase):
    def setUp(self):
        super().setUp()
        self.emma = self._customer('emma', 'Emma', 1)
        self.client.force_login(self.emma, backend=BACKEND)

    def _list(self):
        return self.client.get(reverse('filter-courses')).content.decode()

    def test_full_course_offers_waitlist_and_shows_count_without_names(self):
        html = self._list()
        self.assertIn('Ausgebucht', html)
        self.assertIn(f"{reverse('waitlist-join')}?course={self.course.pk}", html)
        self.assertIn('Auf die Warteliste', html)
        self.assertIn('2 auf der Warteliste', html)
        self.assertNotIn('Carla', html)
        self.assertNotIn('Dora', html)
        # kein Buchen-Button fuer den vollen Kurs
        self.assertNotIn(f"{reverse('create-booking')}?course={self.course.pk}", html)

    def test_join_via_button(self):
        resp = self.client.get(reverse('waitlist-join') + f'?course={self.course.pk}')
        html = resp.content.decode()
        self.assertIn('Du bist auf der Warteliste', html)
        self.assertIn('3 auf der Warteliste', html)
        self.assertIn('Auf der Warteliste ✓', html)
        self.assertIn(f"{reverse('waitlist-leave')}?course={self.course.pk}", html)
        self.assertTrue(WaitlistEntry.objects.filter(user=self.emma, status=WaitlistEntry.WAITING).exists())

    def test_join_without_credit_shows_error(self):
        Credits.objects.filter(user=self.emma).update(number=0)
        resp = self.client.get(reverse('waitlist-join') + f'?course={self.course.pk}')
        self.assertContains(resp, 'mindestens 1 Credit')
        self.assertFalse(WaitlistEntry.objects.filter(user=self.emma).exists())

    def test_leave_via_button(self):
        self.client.force_login(self.carla, backend=BACKEND)
        resp = self.client.get(reverse('waitlist-leave') + f'?course={self.course.pk}')
        self.assertContains(resp, 'von der Warteliste ausgetragen')
        self.assertContains(resp, '1 auf der Warteliste')
        self.assertEqual(self._status(self.carla_entry), WaitlistEntry.LEFT)

    def test_anonymous_cannot_join(self):
        self.client.logout()
        self.client.get(reverse('waitlist-join') + f'?course={self.course.pk}')
        self.assertEqual(WaitlistEntry.objects.filter(course=self.course).count(), 2)

    def test_count_stays_visible_when_seat_is_free(self):
        Courses.objects.filter(pk=self.course.pk).update(capacity=1)
        html = self._list()
        self.assertIn('2 auf der Warteliste', html)
        self.assertIn(f"{reverse('create-booking')}?course={self.course.pk}", html)

    def test_courses_are_sorted_by_date(self):
        # Count-Annotation darf die Sortierung nach Datum nicht aufheben
        Courses.objects.create(name='Frueh', category=self.mamifit, topic='x',
                               date=timezone.now().date() + timedelta(days=1), start=time(8, 0), capacity=5)
        html = self._list()
        self.assertLess(html.index('Frueh'), html.index('MamiFit Outdoor'))
        self.assertLess(html.index('MamiFit Outdoor'), html.index('MamiFit Indoor'))

    def test_no_count_without_waitlist(self):
        self.assertNotIn('0 auf der Warteliste', self._list())

    def test_full_course_still_refuses_booking(self):
        resp = self.client.get(reverse('create-booking') + f'?course={self.course.pk}')
        self.assertContains(resp, 'ausgebucht')
        self.assertFalse(Booking.objects.filter(user=self.emma, course=self.course).exists())
        self.assertEqual(self._credits(self.emma), 1)

    def test_normal_booking_takes_customer_off_waitlist(self):
        Courses.objects.filter(pk=self.course.pk).update(capacity=1)
        self.client.force_login(self.carla, backend=BACKEND)
        self.client.get(reverse('create-booking') + f'?course={self.course.pk}')
        self.assertTrue(Booking.objects.filter(user=self.carla, course=self.course).exists())
        self.assertEqual(self._status(self.carla_entry), WaitlistEntry.BOOKED)
        self.assertEqual(self._capacity(), 0)


# --- Admin ------------------------------------------------------------------

class WaitlistAdminTest(WaitlistBase):
    def setUp(self):
        super().setUp()
        admin_user = User.objects.create_superuser('boss', 'boss@example.com', 'pw')
        self.client.force_login(admin_user, backend=BACKEND)

    def test_course_page_shows_waitlist_inline(self):
        resp = self.client.get(reverse('admin:course_courses_change', args=[self.course.pk]))
        self.assertContains(resp, 'Warteliste')
        self.assertContains(resp, 'Carla Muster')
        self.assertContains(resp, 'Dora Muster')
        self.assertContains(resp, 'wartet')

    def test_course_list_shows_waitlist_count(self):
        resp = self.client.get(reverse('admin:course_courses_changelist'))
        self.assertContains(resp, 'Warteliste')
        self.assertContains(resp, '2 wartend')


# --- Mitbehobene Fehler -------------------------------------------------------

class CancelBookingBugfixTest(WaitlistBase):
    def test_capacity_not_capped_at_seven(self):
        Courses.objects.filter(pk=self.course.pk).update(capacity=9)
        self.client.force_login(self.anna, backend=BACKEND)
        self.client.get(reverse('cancel-booking') + f'?course={self.course.pk}')
        self.assertEqual(self._capacity(), 10)

    def test_late_cancellation_message_shows_credit_balance(self):
        Courses.objects.filter(pk=self.course.pk).update(date=timezone.now().date())
        self.client.force_login(self.anna, backend=BACKEND)
        resp = self.client.get(reverse('cancel-booking') + f'?course={self.course.pk}')
        html = resp.content.decode()
        self.assertNotIn('{credits.number}', html)
        self.assertIn('Du hast 2 Credit(s) übrig', html)

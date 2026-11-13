"""Folgepunkte nach der Warteliste (13.11.2026):
1. Filter bleibt nach Buchen/Abmelden/Warteliste erhalten.
2. Abmelden fragt nach und nennt die 24h-Regel fuer den Credit.
3. 24h-Frist rechnet die Kurszeit als Schweizer Zeit (nicht UTC).
"""
from datetime import date, datetime, time, timedelta, timezone as dt_timezone
from unittest import mock

from django.contrib.auth.models import User
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from course.booking import cancellation_refundable, course_start
from course.models import Booking, Category, Courses, WaitlistEntry
from users.models import Credits

BACKEND = 'django.contrib.auth.backends.ModelBackend'


def utc(*args):
    return datetime(*args, tzinfo=dt_timezone.utc)


class FollowupBase(TestCase):
    def setUp(self):
        self.yoga = Category.objects.create(name='Yoga')
        self.pilates = Category.objects.create(name='Pilates')
        self.mamifit = Category.objects.create(name='MamiFit')
        day = timezone.now().date() + timedelta(days=5)
        self.yoga_course = Courses.objects.create(name='Hatha Flow', category=self.yoga, topic='x',
                                                  date=day, start=time(18, 0), capacity=5)
        self.pilates_course = Courses.objects.create(name='Pilates Basic', category=self.pilates, topic='x',
                                                     date=day, start=time(19, 0), capacity=5)
        self.mamifit_course = Courses.objects.create(name='MamiFit Outdoor', category=self.mamifit, topic='x',
                                                     date=day, start=time(9, 30), capacity=0)
        self.anna = User.objects.create_user('anna', 'anna@example.com', 'pw', first_name='Anna')
        Credits.objects.filter(user=self.anna).update(number=3)
        self.anna.profile.phone = '+41791234567'
        self.anna.profile.save()
        self.client.force_login(self.anna, backend=BACKEND)

    def _credits(self):
        return Credits.objects.get(user=self.anna).number


# --- 1. Filter bleibt erhalten ----------------------------------------------

class FilterKeptAfterActionTest(FollowupBase):
    def test_booking_keeps_filter(self):
        html = self.client.get(reverse('create-booking'),
                               {'course': self.yoga_course.pk, 'filter': 'yoga'}).content.decode()
        self.assertIn('Buchung erfolgreich', html)
        self.assertIn('Hatha Flow', html)
        self.assertNotIn('Pilates Basic', html)
        self.assertNotIn('MamiFit Outdoor', html)

    def test_cancel_keeps_filter(self):
        Booking.objects.create(user=self.anna, course=self.pilates_course)
        html = self.client.get(reverse('cancel-booking'),
                               {'course': self.pilates_course.pk, 'filter': 'pilates'}).content.decode()
        self.assertIn('erfolgreich abgemeldet', html)
        self.assertIn('Pilates Basic', html)
        self.assertNotIn('Hatha Flow', html)

    def test_waitlist_actions_keep_filter(self):
        html = self.client.get(reverse('waitlist-join'),
                               {'course': self.mamifit_course.pk, 'filter': 'mamifit'}).content.decode()
        self.assertIn('Du bist auf der Warteliste', html)
        self.assertIn('MamiFit Outdoor', html)
        self.assertNotIn('Hatha Flow', html)
        html = self.client.get(reverse('waitlist-leave'),
                               {'course': self.mamifit_course.pk, 'filter': 'mamifit'}).content.decode()
        self.assertIn('MamiFit Outdoor', html)
        self.assertNotIn('Pilates Basic', html)

    def test_my_courses_filter_after_cancel(self):
        Booking.objects.create(user=self.anna, course=self.yoga_course)
        Booking.objects.create(user=self.anna, course=self.pilates_course)
        html = self.client.get(reverse('cancel-booking'),
                               {'course': self.yoga_course.pk, 'filter': 'my_courses'}).content.decode()
        self.assertIn('Pilates Basic', html)
        self.assertNotIn('Hatha Flow', html)  # abgemeldet -> nicht mehr "meine"
        self.assertNotIn('MamiFit Outdoor', html)

    def test_without_filter_all_courses(self):
        html = self.client.get(reverse('create-booking'), {'course': self.yoga_course.pk}).content.decode()
        for name in ('Hatha Flow', 'Pilates Basic', 'MamiFit Outdoor'):
            self.assertIn(name, html)

    def test_page_sends_active_filter_with_every_action(self):
        Booking.objects.create(user=self.anna, course=self.pilates_course)
        html = self.client.get(reverse('courses')).content.decode()
        self.assertIn('id="active-filter"', html)
        self.assertIn('name="filter"', html)
        # jede Aktion (Buchen, Abmelden, Warteliste) schickt den Filter mit
        self.assertEqual(html.count('hx-include="#active-filter"'), 3)
        # der Filter springt nicht mehr per JS auf "Alle" zurueck
        self.assertNotIn('htmx:after-request', html)


# --- 2. Rueckfrage beim Abmelden --------------------------------------------

class CancelConfirmTest(FollowupBase):
    def test_confirm_with_refund(self):
        Booking.objects.create(user=self.anna, course=self.yoga_course)
        html = self.client.get(reverse('filter-courses')).content.decode()
        self.assertIn('hx-confirm="', html)
        self.assertIn('Du bekommst 1 Credit zurück', html)

    def test_confirm_without_refund_inside_24h(self):
        soon = timezone.now() + timedelta(hours=3)
        local = timezone.localtime(soon, course_start(self.yoga_course).tzinfo)
        Courses.objects.filter(pk=self.yoga_course.pk).update(date=local.date(), start=local.time())
        Booking.objects.create(user=self.anna, course=self.yoga_course)
        html = self.client.get(reverse('filter-courses')).content.decode()
        self.assertIn('24-Stunden-Frist ist vorbei', html)
        self.assertIn('keinen Credit zurück', html)
        self.assertNotIn('Du bekommst 1 Credit zurück', html)


# --- 3. 24h-Frist in Schweizer Zeit -----------------------------------------

class SwissTimeDeadlineTest(FollowupBase):
    """Kurs am 10.12.2026 um 10:00 Schweizer Zeit = 09:00 UTC (Winterzeit)."""

    def setUp(self):
        super().setUp()
        Courses.objects.filter(pk=self.yoga_course.pk).update(date=date(2026, 12, 10), start=time(10, 0))
        self.yoga_course.refresh_from_db()
        Booking.objects.create(user=self.anna, course=self.yoga_course)

    def _at(self, now):
        """Uhr stellen und neu einloggen (die Session aus setUp waere am
        9.12. schon abgelaufen)."""
        patcher = mock.patch('django.utils.timezone.now', return_value=now)
        patcher.start()
        self.addCleanup(patcher.stop)
        self.client.force_login(self.anna, backend=BACKEND)

    def test_course_start_is_swiss_time(self):
        self.assertEqual(course_start(self.yoga_course), utc(2026, 12, 10, 9, 0))

    def test_refundable_boundary(self):
        # 24.5 h vorher (Schweizer Zeit) -> Credit zurueck
        self.assertTrue(cancellation_refundable(self.yoga_course, now=utc(2026, 12, 9, 8, 30)))
        # 23.5 h vorher; mit falscher UTC-Rechnung waeren es 24.5 h
        self.assertFalse(cancellation_refundable(self.yoga_course, now=utc(2026, 12, 9, 9, 30)))

    def test_cancel_23_5h_before_gives_no_credit(self):
        self._at(utc(2026, 12, 9, 9, 30))
        resp = self.client.get(reverse('cancel-booking'), {'course': self.yoga_course.pk})
        self.assertContains(resp, 'Abmeldefrist wurde nicht eingehalten')
        self.assertEqual(self._credits(), 3)

    def test_cancel_24_5h_before_gives_credit(self):
        self._at(utc(2026, 12, 9, 8, 30))
        self.client.get(reverse('cancel-booking'), {'course': self.yoga_course.pk})
        self.assertEqual(self._credits(), 4)

    def test_confirm_text_uses_same_rule(self):
        self._at(utc(2026, 12, 9, 9, 30))
        html = self.client.get(reverse('filter-courses')).content.decode()
        self.assertIn('keinen Credit zurück', html)

    def test_waitlist_started_uses_same_clock(self):
        from course.waitlist import has_started
        with mock.patch('django.utils.timezone.now', return_value=utc(2026, 12, 10, 9, 0)):
            self.assertTrue(has_started(self.yoga_course))
        with mock.patch('django.utils.timezone.now', return_value=utc(2026, 12, 10, 8, 59)):
            self.assertFalse(has_started(self.yoga_course))


# --- 4. Pro Warteliste ein freier Credit -------------------------------------

class WaitlistCreditReservationTest(FollowupBase):
    """Credits - aktive Wartelisten-Plaetze (kommende Kurse) muss >= 1 sein."""

    def setUp(self):
        super().setUp()
        from course import waitlist
        self.waitlist = waitlist
        day = timezone.now().date() + timedelta(days=6)
        self.full_a = self.mamifit_course
        self.full_b = Courses.objects.create(name='MamiFit Indoor', category=self.mamifit, topic='x',
                                             date=day, start=time(9, 30), capacity=0)
        self.full_c = Courses.objects.create(name='MamiFit Abend', category=self.mamifit, topic='x',
                                             date=day, start=time(19, 0), capacity=0)
        Credits.objects.filter(user=self.anna).update(number=1)

    def test_one_credit_one_waitlist(self):
        from course.waitlist import WaitlistError
        self.waitlist.join(self.anna, self.full_a)
        with self.assertRaisesMessage(WaitlistError, 'pro Warteliste 1 Credit'):
            self.waitlist.join(self.anna, self.full_b)
        self.assertFalse(WaitlistEntry.objects.filter(user=self.anna, course=self.full_b).exists())

    def test_two_credits_two_waitlists(self):
        from course.waitlist import WaitlistError
        Credits.objects.filter(user=self.anna).update(number=2)
        self.waitlist.join(self.anna, self.full_a)
        self.waitlist.join(self.anna, self.full_b)
        with self.assertRaises(WaitlistError):
            self.waitlist.join(self.anna, self.full_c)

    def test_rejoining_same_course_is_still_idempotent(self):
        self.waitlist.join(self.anna, self.full_a)
        self.waitlist.join(self.anna, self.full_a)
        self.assertEqual(WaitlistEntry.objects.filter(user=self.anna).count(), 1)

    def test_inactive_entries_do_not_count(self):
        past = Courses.objects.create(name='Vorbei', category=self.mamifit, topic='x',
                                      date=timezone.now().date() - timedelta(days=3), start=time(9, 30))
        cancelled = Courses.objects.create(name='Abgesagt', category=self.mamifit, topic='x',
                                           date=timezone.now().date() + timedelta(days=2), start=time(9, 30),
                                           is_cancelled=True)
        # alter Eintrag eines vergangenen Kurses (nie aufgeraeumt), abgesagter Kurs, ausgetragen, nachgerueckt
        WaitlistEntry.objects.create(course=past, user=self.anna)
        WaitlistEntry.objects.create(course=cancelled, user=self.anna)
        WaitlistEntry.objects.create(course=self.full_b, user=self.anna, status=WaitlistEntry.LEFT)
        WaitlistEntry.objects.create(course=self.full_c, user=self.anna, status=WaitlistEntry.BOOKED)
        self.waitlist.join(self.anna, self.full_a)  # klappt mit 1 Credit

    def test_leaving_frees_the_credit(self):
        self.waitlist.join(self.anna, self.full_a)
        self.waitlist.leave(self.anna, self.full_a)
        self.waitlist.join(self.anna, self.full_b)

    def test_user_sees_explanation(self):
        self.waitlist.join(self.anna, self.full_a)
        resp = self.client.get(reverse('waitlist-join'), {'course': self.full_b.pk})
        self.assertContains(resp, 'pro Warteliste 1 Credit')
        self.assertContains(resp, 'Du hast 1 Credit(s) und stehst schon auf 1 Warteliste(n)')

    def test_zero_credits_keeps_old_message(self):
        from course.waitlist import WaitlistError
        Credits.objects.filter(user=self.anna).update(number=0)
        with self.assertRaisesMessage(WaitlistError, 'mindestens 1 Credit'):
            self.waitlist.join(self.anna, self.full_a)

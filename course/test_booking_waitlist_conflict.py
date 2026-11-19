"""Bug 19.11.2026: Kundin mit 1 Credit auf 1 Warteliste konnte trotzdem einen
anderen Kurs buchen (de facto 0 freie Credits). Jetzt erscheint ein Dialog:
Warteliste aufgeben und buchen / Abbrechen / Credits kaufen.
"""
from datetime import time, timedelta

from django.contrib.auth.models import User
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from course.booking import BookingResult, book
from course.models import Booking, Category, Courses, WaitlistEntry
from users.models import Credits

BACKEND = 'django.contrib.auth.backends.ModelBackend'


class BookingWaitlistConflictBase(TestCase):
    def setUp(self):
        mamifit = Category.objects.create(name='MamiFit')
        pilates = Category.objects.create(name='Pilates')
        day = timezone.now().date()
        self.full = Courses.objects.create(name='MamiFit Outdoor', category=mamifit, topic='x',
                                           date=day + timedelta(days=3), start=time(9, 30), capacity=0)
        self.full2 = Courses.objects.create(name='MamiFit Indoor', category=mamifit, topic='x',
                                            date=day + timedelta(days=4), start=time(10, 0), capacity=0)
        self.free = Courses.objects.create(name='Pilates Basic', category=pilates, topic='x',
                                           date=day + timedelta(days=5), start=time(18, 0), capacity=3)
        self.anna = User.objects.create_user('anna', 'anna@example.com', 'pw', first_name='Anna')
        self.anna.profile.phone = '+41791234567'
        self.anna.profile.save()
        self._set_credits(1)
        self.entry = WaitlistEntry.objects.create(course=self.full, user=self.anna)
        self.client.force_login(self.anna, backend=BACKEND)

    def _set_credits(self, n):
        Credits.objects.filter(user=self.anna).update(number=n)

    def _credits(self):
        return Credits.objects.get(user=self.anna).number

    def _status(self, entry):
        entry.refresh_from_db()
        return entry.status

    def _booked(self, course):
        return Booking.objects.filter(user=self.anna, course=course).exists()


class BookServiceTest(BookingWaitlistConflictBase):
    def test_conflict_blocks_booking_and_names_the_waitlist(self):
        result, detail = book(self.anna, self.free.pk)
        self.assertIs(result, BookingResult.WAITLIST_CONFLICT)
        self.assertEqual([e.pk for e in detail], [self.entry.pk])
        self.assertFalse(self._booked(self.free))
        self.assertEqual(self._credits(), 1)
        self.assertEqual(self._capacity(self.free), 3)
        self.assertEqual(self._status(self.entry), WaitlistEntry.WAITING)

    def _capacity(self, course):
        return Courses.objects.get(pk=course.pk).capacity

    def test_release_books_and_leaves_waitlist(self):
        result, credits_left = book(self.anna, self.free.pk, release=self.entry.pk)
        self.assertIs(result, BookingResult.BOOKED)
        self.assertEqual(credits_left, 0)
        self.assertTrue(self._booked(self.free))
        self.assertEqual(self._status(self.entry), WaitlistEntry.LEFT)

    def test_enough_credits_no_conflict(self):
        self._set_credits(2)
        result, _ = book(self.anna, self.free.pk)
        self.assertIs(result, BookingResult.BOOKED)
        self.assertEqual(self._status(self.entry), WaitlistEntry.WAITING)

    def test_booking_the_waitlisted_course_itself_is_no_conflict(self):
        Courses.objects.filter(pk=self.full.pk).update(capacity=1)
        result, _ = book(self.anna, self.full.pk)
        self.assertIs(result, BookingResult.BOOKED)
        self.assertEqual(self._status(self.entry), WaitlistEntry.BOOKED)

    def test_two_waitlists_two_credits_release_one(self):
        self._set_credits(2)
        entry2 = WaitlistEntry.objects.create(course=self.full2, user=self.anna)
        result, detail = book(self.anna, self.free.pk)
        self.assertIs(result, BookingResult.WAITLIST_CONFLICT)
        self.assertEqual(sorted(e.pk for e in detail), sorted([self.entry.pk, entry2.pk]))
        result, _ = book(self.anna, self.free.pk, release=entry2.pk)
        self.assertIs(result, BookingResult.BOOKED)
        self.assertEqual(self._status(entry2), WaitlistEntry.LEFT)
        self.assertEqual(self._status(self.entry), WaitlistEntry.WAITING)

    def test_release_not_enough_keeps_everything(self):
        # 1 Credit, 2 Wartelisten (Credit spaeter ausgegeben): eine aufgeben reicht nicht
        entry2 = WaitlistEntry.objects.create(course=self.full2, user=self.anna)
        result, _ = book(self.anna, self.free.pk, release=self.entry.pk)
        self.assertIs(result, BookingResult.WAITLIST_CONFLICT)
        self.assertEqual(self._status(self.entry), WaitlistEntry.WAITING)
        self.assertEqual(self._status(entry2), WaitlistEntry.WAITING)
        self.assertFalse(self._booked(self.free))

    def test_failed_booking_does_not_release(self):
        Courses.objects.filter(pk=self.free.pk).update(capacity=0)
        result, _ = book(self.anna, self.free.pk, release=self.entry.pk)
        self.assertIs(result, BookingResult.FULL)
        self.assertEqual(self._status(self.entry), WaitlistEntry.WAITING)

    def test_cannot_release_someone_elses_entry(self):
        berta = User.objects.create_user('berta', 'b@example.com', 'pw')
        other = WaitlistEntry.objects.create(course=self.full2, user=berta)
        result, _ = book(self.anna, self.free.pk, release=other.pk)
        self.assertIs(result, BookingResult.WAITLIST_CONFLICT)
        self.assertEqual(self._status(other), WaitlistEntry.WAITING)

    def test_past_or_cancelled_waitlists_do_not_block(self):
        WaitlistEntry.objects.filter(pk=self.entry.pk).delete()
        past = Courses.objects.create(name='Vorbei', category=self.full.category, topic='x',
                                      date=timezone.now().date() - timedelta(days=2), start=time(9, 0))
        WaitlistEntry.objects.create(course=past, user=self.anna)
        result, _ = book(self.anna, self.free.pk)
        self.assertIs(result, BookingResult.BOOKED)

    def test_zero_credits_still_says_no_credits(self):
        self._set_credits(0)
        result, _ = book(self.anna, self.free.pk)
        self.assertIs(result, BookingResult.NO_CREDITS)


class BookingConflictDialogTest(BookingWaitlistConflictBase):
    def _book(self, **extra):
        return self.client.get(reverse('create-booking'), {'course': self.free.pk, **extra}).content.decode()

    def test_dialog_with_three_options(self):
        html = self._book()
        self.assertIn('id="booking-conflict"', html)
        self.assertIn('Du bist bereits auf der Warteliste für', html)
        self.assertIn('MamiFit - MamiFit Outdoor', html)
        self.assertIn(self.full.date.strftime('%d.%m.'), html)
        self.assertIn('Sollen wir Dich von der Warteliste entfernen?', html)
        # Ja: gleicher Buchungs-Request mit release=<Eintrag>, Filter bleibt erhalten
        self.assertIn(f"{reverse('create-booking')}?course={self.free.pk}&amp;release={self.entry.pk}", html)
        self.assertIn('hx-include="#active-filter"', html)
        self.assertIn('Abbrechen', html)
        self.assertIn(f"{reverse('my-account')}?tab=credits", html)
        self.assertIn('Credits kaufen', html)
        self.assertFalse(self._booked(self.free))
        self.assertNotIn('Buchung erfolgreich', html)

    def test_yes_books_and_confirms_waitlist_removal(self):
        html = self._book(release=self.entry.pk)
        self.assertIn('Buchung erfolgreich', html)
        self.assertIn('von der Warteliste MamiFit - MamiFit Outdoor entfernt', html)
        self.assertNotIn('id="booking-conflict"', html)
        self.assertTrue(self._booked(self.free))
        self.assertEqual(self._status(self.entry), WaitlistEntry.LEFT)

    def test_dialog_lists_every_waitlist_with_its_own_yes_button(self):
        self._set_credits(2)
        entry2 = WaitlistEntry.objects.create(course=self.full2, user=self.anna)
        html = self._book()
        self.assertIn('MamiFit - MamiFit Indoor', html)
        self.assertIn(f'release={self.entry.pk}', html)
        self.assertIn(f'release={entry2.pk}', html)

    def test_dialog_keeps_filter(self):
        html = self._book(filter='pilates')
        self.assertIn('id="booking-conflict"', html)
        self.assertIn('Pilates Basic', html)
        self.assertNotIn('>MamiFit Indoor<', html)

    def test_no_dialog_without_conflict(self):
        self._set_credits(2)
        html = self._book()
        self.assertNotIn('id="booking-conflict"', html)
        self.assertIn('Buchung erfolgreich', html)


class MyAccountCreditsTabTest(TestCase):
    def setUp(self):
        self.user = User.objects.create_user('anna', 'anna@example.com', 'pw')
        self.user.profile.phone = '+41791234567'
        self.user.profile.save()
        self.client.force_login(self.user, backend=BACKEND)

    def test_tab_credits_opens_credits(self):
        html = self.client.get(reverse('my-account'), {'tab': 'credits'}).content.decode()
        self.assertIn(f"{reverse('my-account')}?navigate=credits&amp;buy=1\"\n    hx-trigger=\"load\"", html)
        self.assertIn("selected: 'credits'", html)

    def test_buy_opens_purchase_section(self):
        html = self.client.get(reverse('my-account'), {'navigate': 'credits', 'buy': '1'}).content.decode()
        self.assertIn('purchaseCredits: true', html)
        html = self.client.get(reverse('my-account'), {'navigate': 'credits'}).content.decode()
        self.assertIn('purchaseCredits: false', html)

    def test_default_and_unknown_tab_open_news(self):
        for params in ({}, {'tab': 'evil"><script>'}):
            html = self.client.get(reverse('my-account'), params).content.decode()
            self.assertIn(f"{reverse('my-account')}?navigate=news\"\n    hx-trigger=\"load\"", html)
            self.assertNotIn('<script>"', html)

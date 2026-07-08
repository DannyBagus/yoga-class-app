from datetime import date, time

from django.contrib.auth.models import User
from django.test import TestCase, override_settings
from django.urls import reverse

from course.models import Category, Courses, Booking
from users.models import Credits

API_KEY = 'test-workbench-key'


@override_settings(WORKBENCH_API_KEY=API_KEY)
class UserBookingsEndpointTest(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.user = User.objects.create_user(
            username='anna', email='Anna@example.com',
            first_name='Anna', last_name='Muster',
        )
        # Signal legt Credits(number=0) an -> auf gewuenschten Wert setzen
        credits = cls.user.credits
        credits.number = 12
        credits.save()

        cls.yoga = Category.objects.create(name='Yoga')
        cls.pilates = Category.objects.create(name='Pilates')

        # Zwei Yoga-Kurse (unterschiedliche Daten) + ein Pilates-Kurs
        cls.yoga_old = Courses.objects.create(
            name='Yoga Basic', category=cls.yoga, topic='Ruecken',
            date=date(2026, 1, 10), start=time(18, 0), duration=1,
        )
        cls.yoga_new = Courses.objects.create(
            name='Yoga Flow', category=cls.yoga, topic='Flow',
            date=date(2026, 5, 20), start=time(9, 30), duration=1,
        )
        cls.pilates_course = Courses.objects.create(
            name='Pilates Core', category=cls.pilates, topic='Core',
            date=date(2026, 3, 1), start=time(19, 0), duration=1,
        )
        Booking.objects.create(user=cls.user, course=cls.yoga_old)
        Booking.objects.create(user=cls.user, course=cls.yoga_new)
        Booking.objects.create(user=cls.user, course=cls.pilates_course)

    def _url(self, email):
        return reverse('user-bookings', args=[email])

    def test_returns_account_and_bookings_with_valid_key(self):
        resp = self.client.get(self._url('anna@example.com'), HTTP_X_API_KEY=API_KEY)
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertEqual(data['email'], 'Anna@example.com')
        self.assertEqual(data['first_name'], 'Anna')
        self.assertEqual(data['last_name'], 'Muster')
        self.assertEqual(data['credits'], 12)
        self.assertIn('/admin/auth/user/', data['admin_url'])
        self.assertEqual(len(data['bookings']), 3)

    def test_bookings_sorted_by_category_then_date_desc(self):
        resp = self.client.get(self._url('anna@example.com'), HTTP_X_API_KEY=API_KEY)
        bookings = resp.json()['bookings']
        # Pilates (alphabetisch vor Yoga) zuerst, dann Yoga; innerhalb Yoga neu zuoberst.
        self.assertEqual(
            [(b['category'], b['course_name']) for b in bookings],
            [
                ('Pilates', 'Pilates Core'),
                ('Yoga', 'Yoga Flow'),   # 20.05.2026 (neuer)
                ('Yoga', 'Yoga Basic'),  # 10.01.2026 (aelter)
            ],
        )
        self.assertEqual(bookings[1]['date'], '20.05.2026')
        self.assertEqual(bookings[1]['start'], '09:30')

    def test_email_lookup_is_case_insensitive(self):
        resp = self.client.get(self._url('ANNA@EXAMPLE.COM'), HTTP_X_API_KEY=API_KEY)
        self.assertEqual(resp.status_code, 200)

    def test_unknown_email_returns_404(self):
        resp = self.client.get(self._url('unbekannt@example.com'), HTTP_X_API_KEY=API_KEY)
        self.assertEqual(resp.status_code, 404)
        self.assertIn('detail', resp.json())

    def test_missing_key_returns_403(self):
        resp = self.client.get(self._url('anna@example.com'))
        self.assertEqual(resp.status_code, 403)

    def test_wrong_key_returns_403(self):
        resp = self.client.get(self._url('anna@example.com'), HTTP_X_API_KEY='falsch')
        self.assertEqual(resp.status_code, 403)

    @override_settings(WORKBENCH_API_KEY='')
    def test_empty_server_key_denies_access(self):
        # Fail-closed: ohne serverseitigen Schluessel kein Zugriff.
        resp = self.client.get(self._url('anna@example.com'), HTTP_X_API_KEY='')
        self.assertEqual(resp.status_code, 403)

from datetime import date, time, timedelta
from unittest import mock

from django.contrib.admin.models import LogEntry
from django.contrib.auth.models import User
from django.core import mail
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from course.cancellation import CourseAlreadyCancelled, cancel_course
from course.models import Booking, Category, Courses
from users.models import Credits


class CourseCancellationBase(TestCase):
    def setUp(self):
        self.category = Category.objects.create(name='Yoga')
        self.course = Courses.objects.create(
            name='Yoga Flow', category=self.category, topic='Flow',
            date=timezone.now().date() + timedelta(days=1), start=time(18, 0), capacity=5,
        )
        self.other_course = Courses.objects.create(
            name='Yoga Basic', category=self.category, topic='Basic',
            date=timezone.now().date() + timedelta(days=2), start=time(9, 0), capacity=5,
        )
        self.anna = self._customer('anna', 'Anna', 2)
        self.berta = self._customer('berta', 'Berta', 0)
        Booking.objects.create(user=self.anna, course=self.course)
        Booking.objects.create(user=self.berta, course=self.course)
        Booking.objects.create(user=self.anna, course=self.other_course)

    def _customer(self, username, first_name, credits):
        user = User.objects.create_user(username, f'{username}@example.com', 'pw',
                                        first_name=first_name, last_name='Muster')
        Credits.objects.filter(user=user).update(number=credits)
        user.profile.phone = '+41791234567'
        user.profile.save()
        return user

    def _credits(self, user):
        return Credits.objects.get(user=user).number


class CancelCourseServiceTest(CourseCancellationBase):
    def test_cancels_bookings_refunds_and_mails(self):
        result = cancel_course(self.course.pk)

        self.course.refresh_from_db()
        self.assertTrue(self.course.is_cancelled)
        self.assertIsNotNone(self.course.cancelled_at)
        self.assertEqual(self.course.capacity, 7)
        self.assertFalse(Booking.objects.filter(course=self.course).exists())
        # Buchung im anderen Kurs bleibt unberuehrt
        self.assertTrue(Booking.objects.filter(course=self.other_course, user=self.anna).exists())
        self.assertEqual(self._credits(self.anna), 3)
        self.assertEqual(self._credits(self.berta), 1)
        self.assertEqual(sorted((u.username, b, a) for u, b, a in result.refunds),
                         [('anna', 2, 3), ('berta', 0, 1)])

        self.assertEqual(result.mails_sent, 2)
        self.assertTrue(result.summary_sent)
        self.assertEqual(sorted(m.to[0] for m in mail.outbox),
                         ['anna@example.com', 'berta@example.com', 'hebammen@mileja.ch'])
        msg = next(m for m in mail.outbox if m.to == ['anna@example.com'])
        self.assertEqual(msg.from_email, 'admin@mileja.ch')
        self.assertEqual(msg.reply_to, ['hebammen@mileja.ch'])
        self.assertIn('Kursabsage: Yoga - Yoga Flow', msg.subject)
        self.assertIn('3 Credit(s)', msg.body)
        self.assertIn('3 Credit(s)', msg.alternatives[0][0])
        self.assertIn('Bitte bestätige kurz, dass Du die Nachricht erhalten hast.', msg.body)
        self.assertIn('Bitte bestätige kurz, dass Du die Nachricht erhalten hast.', msg.alternatives[0][0])

    def test_summary_mail_lists_participants(self):
        boss = User.objects.create_user('boss', 'boss@example.com', 'pw', first_name='Nina', last_name='Chefin')
        cancel_course(self.course.pk, cancelled_by=boss)
        summary = next(m for m in mail.outbox if m.to == ['hebammen@mileja.ch'])
        self.assertEqual(summary.from_email, 'admin@mileja.ch')
        self.assertIn('Kurs abgesagt: Yoga - Yoga Flow', summary.subject)
        self.assertIn('2 Buchung(en) storniert', summary.subject)
        for text in (summary.body, summary.alternatives[0][0]):
            self.assertIn('von Nina Chefin', text.replace('<strong>', '').replace('</strong>', ''))
            self.assertIn('Anna Muster', text)
            self.assertIn('Berta Muster', text)
            self.assertIn('+41791234567', text)
            self.assertIn('anna@example.com', text)
        self.assertIn('Credits: 2 -> 3', summary.body)
        self.assertNotIn('FEHLGESCHLAGEN', summary.body)

    def test_summary_mail_flags_failed_customer_mail(self):
        from course import cancellation
        real_send = cancellation._send_mail

        def flaky(subject, template, context, to, reply_to=None):
            if to == ['berta@example.com']:
                raise OSError('mailbox full')
            return real_send(subject, template, context, to, reply_to)

        with mock.patch('course.cancellation._send_mail', side_effect=flaky):
            result = cancel_course(self.course.pk)
        self.assertTrue(result.summary_sent)
        summary = next(m for m in mail.outbox if m.to == ['hebammen@mileja.ch'])
        self.assertIn('FEHLGESCHLAGEN: 1', summary.body)
        self.assertIn('MAIL FEHLGESCHLAGEN', summary.body)

    def test_summary_mail_without_bookings(self):
        Booking.objects.filter(course=self.course).delete()
        result = cancel_course(self.course.pk)
        self.assertTrue(result.summary_sent)
        self.assertEqual([m.to for m in mail.outbox], [['hebammen@mileja.ch']])
        self.assertIn('keine Teilnehmerinnen', mail.outbox[0].body)

    def test_refunds_even_within_24h(self):
        Courses.objects.filter(pk=self.course.pk).update(date=timezone.now().date())
        cancel_course(self.course.pk)
        self.assertEqual(self._credits(self.anna), 3)

    def test_second_cancel_is_rejected(self):
        cancel_course(self.course.pk)
        with self.assertRaises(CourseAlreadyCancelled):
            cancel_course(self.course.pk)
        self.assertEqual(self._credits(self.anna), 3)

    def test_mail_failure_does_not_undo_cancellation(self):
        with mock.patch('course.cancellation.EmailMultiAlternatives.send', side_effect=OSError('smtp down')):
            result = cancel_course(self.course.pk)
        self.assertEqual(result.mails_sent, 0)
        self.assertEqual(len(result.mail_failures), 2)
        self.assertFalse(result.summary_sent)
        self.course.refresh_from_db()
        self.assertTrue(self.course.is_cancelled)
        self.assertEqual(self._credits(self.anna), 3)

    def test_error_rolls_back_everything(self):
        with mock.patch.object(Booking, 'delete', side_effect=RuntimeError('boom')):
            with self.assertRaises(RuntimeError):
                cancel_course(self.course.pk)
        self.course.refresh_from_db()
        self.assertFalse(self.course.is_cancelled)
        self.assertEqual(self._credits(self.anna), 2)
        self.assertEqual(Booking.objects.filter(course=self.course).count(), 2)


class CancelCourseAdminTest(CourseCancellationBase):
    def setUp(self):
        super().setUp()
        self.admin = User.objects.create_superuser('boss', 'boss@example.com', 'pw')
        self.client.force_login(self.admin, backend='django.contrib.auth.backends.ModelBackend')
        self.change_url = reverse('admin:course_courses_change', args=[self.course.pk])
        self.cancel_url = reverse('admin:course_courses_cancel', args=[self.course.pk])

    def test_change_page_shows_button_with_tooltip(self):
        resp = self.client.get(self.change_url)
        self.assertContains(resp, 'Kurs absagen')
        self.assertContains(resp, f'action="{self.cancel_url}"')
        self.assertContains(resp, '2 Buchung(en)</strong> werden storniert')
        self.assertContains(resp, 'Anna Muster: 2 → 3 Credits')
        self.assertContains(resp, 'Berta Muster: 0 → 1 Credits')
        self.assertContains(resp, 'confirm(')

    def test_booking_inline_shows_phone(self):
        resp = self.client.get(self.change_url)
        self.assertContains(resp, 'Telefon')
        self.assertContains(resp, '<a href="tel:+41791234567">+41791234567</a>', count=2)
        self.assertContains(resp, 'https://wa.me/41791234567', count=2)

    def test_booking_inline_without_phone(self):
        self.berta.profile.phone = ''
        self.berta.profile.save()
        resp = self.client.get(self.change_url)
        self.assertContains(resp, 'tel:+41791234567', count=1)

    def test_post_cancels_and_logs(self):
        resp = self.client.post(self.cancel_url, follow=True)
        self.assertRedirects(resp, self.change_url)
        self.assertContains(resp, 'Kurs abgesagt: 2 Buchung(en) storniert')
        self.assertContains(resp, 'Zusammenfassung an hebammen@mileja.ch: versendet')
        self.assertContains(resp, 'Abgesagt am')
        self.assertNotContains(resp, 'Kurs absagen</button>')
        self.course.refresh_from_db()
        self.assertTrue(self.course.is_cancelled)
        entry = LogEntry.objects.get(object_id=str(self.course.pk))
        self.assertIn('Anna Muster (2→3)', entry.change_message)

    def test_get_does_not_cancel(self):
        self.client.get(self.cancel_url)
        self.course.refresh_from_db()
        self.assertFalse(self.course.is_cancelled)

    def test_non_staff_cannot_cancel(self):
        self.client.force_login(self.anna, backend='django.contrib.auth.backends.ModelBackend')
        self.client.post(self.cancel_url)
        self.course.refresh_from_db()
        self.assertFalse(self.course.is_cancelled)

    def test_double_post_warns(self):
        self.client.post(self.cancel_url)
        resp = self.client.post(self.cancel_url, follow=True)
        self.assertContains(resp, 'bereits abgesagt')
        self.assertEqual(self._credits(self.anna), 3)


class CancelledCourseFrontendTest(CourseCancellationBase):
    def setUp(self):
        super().setUp()
        cancel_course(self.course.pk)
        self.client.force_login(self.berta, backend='django.contrib.auth.backends.ModelBackend')

    def test_card_is_gray_without_booking_button(self):
        resp = self.client.get(reverse('filter-courses'))
        html = resp.content.decode()
        self.assertIn('Abgesagt', html)
        self.assertIn('grayscale', html)
        self.assertNotIn(f'?course={self.course.pk}"', html)
        self.assertIn(f'?course={self.other_course.pk}"', html)

    def test_booking_cancelled_course_is_refused(self):
        resp = self.client.get(reverse('create-booking') + f'?course={self.course.pk}')
        self.assertContains(resp, 'abgesagt und kann nicht gebucht werden')
        self.assertFalse(Booking.objects.filter(course=self.course).exists())
        self.assertEqual(self._credits(self.berta), 1)

    def test_reminder_skips_cancelled_course(self):
        Courses.objects.filter(pk=self.course.pk).update(date=timezone.now().date())
        mail.outbox.clear()
        resp = self.client.get(reverse('send_course_reminder'))
        self.assertContains(resp, 'Es findet heute kein Kurs statt.')
        self.assertEqual(len(mail.outbox), 0)

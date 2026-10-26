import io
import json
import time
from unittest import mock

from django.contrib.auth.models import User
from django.core import mail, signing
from django.core.exceptions import ValidationError
from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import TestCase, SimpleTestCase, override_settings
from django.urls import reverse

from users.models import Profile
from users.phone import normalize_phone


class NormalizePhoneTest(SimpleTestCase):
    def test_swiss_variants(self):
        for raw in ('079 123 45 67', '0791234567', '079-123.45.67', '+41 79 123 45 67',
                    '0041791234567', '+41 (0)79 123 45 67', ' +41791234567 ',
                    '791234567', '+410791234567'):
            self.assertEqual(normalize_phone(raw), '+41791234567', raw)

    def test_foreign_number(self):
        self.assertEqual(normalize_phone('+49 151 23456789'), '+4915123456789')

    def test_invalid(self):
        for raw in ('', 'abc', '12345', '079 123 45', '+41 79 123 45 678', '+0791234567',
                    '0763168673Riehenstrasse 149', '491234567'):
            with self.assertRaises(ValidationError, msg=raw):
                normalize_phone(raw)


class ProfileSignalTest(TestCase):
    def test_profile_created_with_user(self):
        user = User.objects.create_user('anna', 'anna@example.com', 'pw')
        self.assertEqual(user.profile.phone, '')


class RegistrationPhoneTest(TestCase):
    def _post(self, **overrides):
        data = {
            'username': 'anna', 'email': 'anna@example.com', 'phone': '079 123 45 67',
            'first_name': 'Anna', 'last_name': 'Muster',
            'password1': 'Sehr-sicher-123', 'password2': 'Sehr-sicher-123',
            'website': '', 'form_ts': signing.dumps(time.time() - 10),
        }
        data.update(overrides)
        return self.client.post(reverse('register'), data)

    def test_phone_saved_normalized(self):
        resp = self._post()
        self.assertEqual(resp.status_code, 200)
        user = User.objects.get(username='anna')
        self.assertEqual(user.profile.phone, '+41791234567')
        self.assertEqual(len(mail.outbox), 1)

    def test_phone_required(self):
        resp = self._post(phone='')
        self.assertFalse(User.objects.filter(username='anna').exists())
        self.assertTrue(resp.context['form'].errors['phone'])

    def test_phone_invalid(self):
        resp = self._post(phone='12345')
        self.assertFalse(User.objects.filter(username='anna').exists())
        self.assertIn('gültige Natelnummer', resp.context['form'].errors['phone'][0])

    def test_register_page_renders_phone_field(self):
        resp = self.client.get(reverse('register'))
        self.assertContains(resp, 'name="phone"')


class RequirePhoneMiddlewareTest(TestCase):
    def setUp(self):
        self.user = User.objects.create_user('anna', 'anna@example.com', 'pw')
        self.client.force_login(self.user, backend='django.contrib.auth.backends.ModelBackend')

    def test_redirects_without_phone(self):
        resp = self.client.get(reverse('my-account'))
        self.assertRedirects(resp, f"{reverse('phone')}?next=%2Fusers%2Fmein-konto%2F",
                             fetch_redirect_response=False)

    def test_htmx_request_gets_hx_redirect(self):
        resp = self.client.get(reverse('my-account') + '?navigate=credits', HTTP_HX_REQUEST='true',
                               HTTP_HX_CURRENT_URL='http://testserver/users/mein-konto/')
        self.assertEqual(resp.status_code, 200)
        self.assertTrue(resp['HX-Redirect'].startswith(reverse('phone')))

    def test_post_redirects_without_next(self):
        resp = self.client.post(reverse('my-account'))
        self.assertRedirects(resp, reverse('phone'), fetch_redirect_response=False)

    def test_exempt_paths_not_blocked(self):
        self.assertEqual(self.client.get(reverse('phone')).status_code, 200)
        self.assertNotEqual(self.client.get('/api/').get('Location', ''), reverse('phone'))
        resp = self.client.get(reverse('logout'))
        self.assertRedirects(resp, reverse('home'), fetch_redirect_response=False)

    def test_no_redirect_with_phone(self):
        Profile.objects.filter(user=self.user).update(phone='+41791234567')
        resp = self.client.get(reverse('my-account'))
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, '+41791234567')

    def test_missing_profile_also_blocked(self):
        Profile.objects.filter(user=self.user).delete()
        resp = self.client.get(reverse('my-account'))
        self.assertEqual(resp.status_code, 302)

    def test_staff_not_blocked(self):
        self.user.is_staff = True
        self.user.save()
        self.assertEqual(self.client.get(reverse('my-account')).status_code, 200)

    def test_anonymous_not_blocked(self):
        self.client.logout()
        self.assertEqual(self.client.get(reverse('register')).status_code, 200)

    def test_submit_phone_then_continue(self):
        resp = self.client.post(reverse('phone'), {'phone': '079 123 45 67', 'next': '/users/mein-konto/?x=1'})
        self.assertRedirects(resp, '/users/mein-konto/?x=1', fetch_redirect_response=False)
        self.user.profile.refresh_from_db()
        self.assertEqual(self.user.profile.phone, '+41791234567')
        self.assertEqual(self.client.get(reverse('my-account')).status_code, 200)

    def test_invalid_phone_stays_on_form(self):
        resp = self.client.post(reverse('phone'), {'phone': 'abc'})
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, 'gültige Natelnummer')
        self.assertEqual(Profile.objects.get(user=self.user).phone, '')

    def test_external_next_ignored(self):
        resp = self.client.post(reverse('phone'), {'phone': '0791234567', 'next': 'https://evil.example/'})
        self.assertRedirects(resp, reverse('my-account'), fetch_redirect_response=False)


def _workbench_response(payload):
    resp = mock.MagicMock()
    resp.__enter__.return_value = io.BytesIO(json.dumps(payload).encode())
    return resp


@override_settings(WORKBENCH_URL='http://wb', WORKBENCH_OUTBOUND_API_KEY='k')
class SyncPhonesFromWorkbenchTest(TestCase):
    def setUp(self):
        self.match = User.objects.create_user('a', 'Match@example.com', 'pw')
        self.unknown = User.objects.create_user('b', 'unknown@example.com', 'pw')
        self.invalid = User.objects.create_user('c', 'invalid@example.com', 'pw')
        self.has_phone = User.objects.create_user('d', 'has@example.com', 'pw')
        Profile.objects.filter(user=self.has_phone).update(phone='+41790000000')
        self.inactive = User.objects.create_user('e', 'inactive@example.com', 'pw', is_active=False)

        self.workbench = {
            'match@example.com': {'found': True, 'customer': {'phone': '079 111 22 33'}},
            'invalid@example.com': {'found': True, 'customer': {'phone': 'keine'}},
        }
        self.requested = []
        log_patch = mock.patch('users.management.commands.sync_phones_from_workbench.AUDIT_LOG',
                               '/dev/null')
        log_patch.start()
        self.addCleanup(log_patch.stop)

    def _fake_urlopen(self, req, timeout):
        self.assertEqual(req.get_header('X-api-key'), 'k')
        email = req.full_url.split('email=')[1].replace('%40', '@').lower()
        self.requested.append(email)
        return _workbench_response(self.workbench.get(email, {'found': False}))

    def _run(self, *args):
        out = io.StringIO()
        with mock.patch('urllib.request.urlopen', side_effect=self._fake_urlopen):
            call_command('sync_phones_from_workbench', *args, stdout=out)
        return out.getvalue()

    def _phone(self, user):
        return Profile.objects.get(user=user).phone

    def test_dry_run_changes_nothing(self):
        out = self._run()
        self.assertIn('would-update=1', out)
        self.assertEqual(self._phone(self.match), '')

    def test_apply_updates_only_missing_and_valid(self):
        out = self._run('--apply')
        self.assertIn('updated=1', out)
        self.assertIn('invalid-phone=1', out)
        self.assertIn('not-in-workbench=1', out)
        self.assertEqual(self._phone(self.match), '+41791112233')
        self.assertEqual(self._phone(self.invalid), '')
        self.assertEqual(self._phone(self.has_phone), '+41790000000')
        # Nur aktive User ohne Nummer werden abgefragt.
        self.assertEqual(sorted(self.requested),
                         ['invalid@example.com', 'match@example.com', 'unknown@example.com'])

    @override_settings(WORKBENCH_OUTBOUND_API_KEY='')
    def test_missing_key_aborts(self):
        with self.assertRaises(CommandError):
            call_command('sync_phones_from_workbench', stdout=io.StringIO())

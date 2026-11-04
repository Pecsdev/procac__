import base64
import hashlib
import hmac
import io
import json
import re
import urllib.error
from datetime import date, timedelta
from unittest.mock import MagicMock, patch

from django.contrib.auth.models import User
from django.core import mail
from django.test import Client, TestCase, override_settings
from django.urls import reverse
from django.utils import timezone
from dateutil.relativedelta import relativedelta

from .models import (
    ClientIntakeLink,
    ClientProfile,
    ConsultantProfile,
    InjectionAuditLog,
    Subscription,
)
from .utils import calculate_subscription_expiry


@override_settings(EMAIL_BACKEND='django.core.mail.backends.locmem.EmailBackend')
class SubscriptionExpiryUtilityTest(TestCase):
    def test_expiry_clamps_month_end_and_leap_day(self):
        self.assertEqual(
            calculate_subscription_expiry(date(2025, 1, 31), relativedelta(months=1)),
            date(2025, 2, 28),
        )
        self.assertEqual(
            calculate_subscription_expiry(date(2026, 11, 2), 'ultimate_enterprise'),
            date(2027, 1, 2),
        )
        self.assertEqual(
            calculate_subscription_expiry(date(2024, 2, 29), relativedelta(years=1)),
            date(2025, 2, 28),
        )


@override_settings(EMAIL_BACKEND='django.core.mail.backends.locmem.EmailBackend')
class FrontendAuthenticationTest(TestCase):
    def test_landing_login_and_signup_pages_are_public(self):
        response = self.client.get('/')
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, '/static/frontend/assets/js/encoded-links.js')

        for route in ('/login/', '/signup/'):
            with self.subTest(route=route):
                response = self.client.get(route)
                self.assertEqual(response.status_code, 200)
                self.assertContains(response, '/static/frontend/assets/js/encoded-links.js')

    def test_landing_page_uses_native_components_without_bootstrap(self):
        response = self.client.get('/')

        self.assertEqual(response.status_code, 200)
        self.assertNotContains(response, 'bootstrap.min.css')
        self.assertNotContains(response, 'bootstrap.bundle.min.js')
        self.assertContains(response, '<details class="faq-item">')
        self.assertContains(response, 'id="runSimulation"')
        self.assertContains(response, 'data-demo-type="BN"')
        self.assertContains(response, 'data-demo-type="LTD"')
        self.assertContains(response, 'data-demo-type="IT"')
        self.assertContains(response, 'id="payment-csrf-token"')
        self.assertContains(response, 'backdrop-filter: blur(12px)')
        self.assertNotContains(response, 'assets/css/theme.css')
        self.assertContains(response, 'data-subscribe-plan="ultimate_enterprise"')
        self.assertContains(
            response,
            '/static/frontend/assets/images/hero/procac-high-resolution-logo.png',
        )

    def test_signup_form_does_not_ask_for_a_plan(self):
        response = self.client.get('/signup/')

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'name="phone_number"')
        self.assertContains(response, 'name="firm_name"')
        self.assertContains(response, 'Create Consultant Workspace')
        self.assertNotIn('plan', response.context['form'].fields)

    def test_dashboard_pages_still_require_authentication(self):
        for route in ('/dashboard/', '/intake/', '/admin-panel/'):
            with self.subTest(route=route):
                response = self.client.get(route)
                self.assertRedirects(
                    response,
                    f'/login/?next={route}',
                    fetch_redirect_response=False,
                )

    def test_authenticated_user_is_logged_out_on_signup_but_not_login(self):
        user = User.objects.create_user(
            username='existing@example.com',
            email='existing@example.com',
            password='SaferExamplePassword!26',
        )
        self.client.force_login(user)

        login_response = self.client.get('/login/')
        self.assertEqual(login_response.status_code, 200)
        self.assertContains(login_response, 'Welcome back, Consultant')
        self.assertEqual(self.client.session.get('_auth_user_id'), str(user.pk))

        signup_response = self.client.get('/signup/')
        self.assertEqual(signup_response.status_code, 200)
        self.assertContains(signup_response, 'Create your workspace')
        self.assertIsNone(self.client.session.get('_auth_user_id'))
        self.assertFalse(signup_response.context['form'].is_bound)
        for field in ('full_name', 'accreditation_number', 'email'):
            with self.subTest(field=field):
                self.assertIsNone(signup_response.context['form'][field].value())

    def test_signup_creates_user_and_profile_only_after_email_verification(self):
        response = self.client.post('/signup/', {
            'full_name': 'Counsel Ada Legal',
            'accreditation_number': 'NBA/ACC/2026/001',
            'email': 'ada@example.com',
            'phone_number': '+234 800 123 4567',
            'firm_name': 'Ada Legal Partners',
            'plan': 'premium',
            'password1': 'SaferExamplePassword!26',
            'password2': 'SaferExamplePassword!26',
        })

        self.assertRedirects(response, '/verify-otp/', fetch_redirect_response=False)
        self.assertFalse(User.objects.filter(email='ada@example.com').exists())
        self.assertIsNone(self.client.session.get('_auth_user_id'))
        self.assertTrue(
            self.client.session['pending_user_data']['password'].startswith('pbkdf2_')
        )
        self.assertEqual(len(mail.outbox), 1)
        self.assertEqual(mail.outbox[0].to, ['ada@example.com'])

        code = re.search(r'\b(\d{6})\b', mail.outbox[0].body).group(1)
        response = self.client.post('/verify-otp/', {'otp': code})
        self.assertRedirects(
            response,
            '/plans/',
            fetch_redirect_response=False,
        )
        user = User.objects.get(email='ada@example.com')
        self.assertEqual(user.get_full_name(), 'Counsel Ada Legal')
        self.assertTrue(user.check_password('SaferExamplePassword!26'))
        self.assertEqual(user.consultant_profile.accreditation_number, 'NBA/ACC/2026/001')
        self.assertEqual(user.consultant_profile.phone_number, '+234 800 123 4567')
        self.assertEqual(user.consultant_profile.firm_name, 'Ada Legal Partners')
        self.assertEqual(user.consultant_profile.plan, 'starter')
        self.assertTrue(self.client.session.get('_auth_user_id'))
        self.assertNotIn('pending_user_data', self.client.session)

    def test_signup_form_can_replace_an_existing_session_after_registration(self):
        existing_user = User.objects.create_user(
            username='existing@example.com',
            email='existing@example.com',
            password='SaferExamplePassword!26',
        )
        self.client.force_login(existing_user)

        response = self.client.post('/signup/', {
            'full_name': 'Counsel Ada Legal',
            'accreditation_number': 'NBA/ACC/2026/010',
            'email': 'new-account@example.com',
            'plan': 'premium',
            'password1': 'SaferExamplePassword!26',
            'password2': 'SaferExamplePassword!26',
        })

        self.assertRedirects(response, '/verify-otp/', fetch_redirect_response=False)
        self.assertFalse(User.objects.filter(email='new-account@example.com').exists())
        self.assertIsNone(self.client.session.get('_auth_user_id'))
        code = re.search(r'\b(\d{6})\b', mail.outbox[0].body).group(1)
        self.client.post('/verify-otp/', {'otp': code})
        new_user = User.objects.get(email='new-account@example.com')
        self.assertEqual(self.client.session.get('_auth_user_id'), str(new_user.pk))

    def test_json_signup_starts_verification_without_creating_an_account(self):
        response = self.client.post(
            '/signup/',
            data=json.dumps({
                'full_name': 'Counsel Ada Legal',
                'accreditation_number': 'NBA/ACC/2026/011',
                'email': 'json-new-account@example.com',
                'plan': 'standard',
                'password1': 'SaferExamplePassword!26',
                'password2': 'SaferExamplePassword!26',
            }),
            content_type='application/json',
        )

        self.assertEqual(response.status_code, 202)
        self.assertEqual(response.json()['verify_url'], '/verify-otp/')
        self.assertTrue(response.json()['verification_required'])
        self.assertFalse(User.objects.filter(email='json-new-account@example.com').exists())
        self.assertIsNone(self.client.session.get('_auth_user_id'))

    def test_resend_cooldown_and_latest_code_are_enforced(self):
        self.client.post('/signup/', {
            'full_name': 'Counsel Ada Legal',
            'accreditation_number': 'NBA/ACC/2026/012',
            'email': 'resend@example.com',
            'plan': 'standard',
            'password1': 'SaferExamplePassword!26',
            'password2': 'SaferExamplePassword!26',
        })
        initial_code = re.search(r'\b(\d{6})\b', mail.outbox[0].body).group(1)

        page = self.client.get('/verify-otp/')
        self.assertContains(page, 'Verify Code')
        self.assertContains(page, 'Resend Code')
        self.client.post('/verify-otp/', {'action': 'resend'})
        self.assertEqual(len(mail.outbox), 1)

        session = self.client.session
        pending = session['pending_user_data']
        pending['resend_available_at'] = 0
        session['pending_user_data'] = pending
        session.save()
        self.client.post('/verify-otp/', {'action': 'resend'})
        self.assertEqual(len(mail.outbox), 2)

        self.client.post('/verify-otp/', {'otp': initial_code})
        self.assertFalse(User.objects.filter(email='resend@example.com').exists())
        latest_code = re.search(r'\b(\d{6})\b', mail.outbox[1].body).group(1)
        self.client.post('/verify-otp/', {'otp': latest_code})
        self.assertTrue(User.objects.filter(email='resend@example.com').exists())

    def test_verified_json_signup_can_continue_to_payment(self):
        client = Client(enforce_csrf_checks=True)
        signup_page = client.get('/signup/')
        csrf_token = signup_page.cookies['csrftoken'].value
        signup_response = client.post(
            '/signup/',
            data=json.dumps({
                'full_name': 'Counsel Ada Legal',
                'accreditation_number': 'NBA/ACC/2026/002',
                'email': 'onboarding@example.com',
                'plan': 'standard',
                'password1': 'SaferExamplePassword!26',
                'password2': 'SaferExamplePassword!26',
            }),
            content_type='application/json',
            HTTP_X_CSRFTOKEN=csrf_token,
        )

        self.assertEqual(signup_response.status_code, 202)
        self.assertFalse(User.objects.filter(email='onboarding@example.com').exists())
        verification_code = re.search(r'\b(\d{6})\b', mail.outbox[0].body).group(1)
        verification_response = client.post(
            '/verify-otp/',
            data={'otp': verification_code},
            HTTP_X_CSRFTOKEN=csrf_token,
        )
        self.assertRedirects(
            verification_response,
            '/plans/',
            fetch_redirect_response=False,
        )
        self.assertTrue(client.session.get('_auth_user_id'))

        provider_response = MagicMock()
        provider_response.__enter__.return_value.read.return_value = json.dumps({
            'status': True,
            'data': {
                'authorization_url': 'https://checkout.paystack.com/onboarding',
                'access_code': 'access-onboarding',
                'reference': 'procac-onboarding',
            },
        }).encode()
        with (
            override_settings(PAYSTACK_SECRET_KEY='sk_test_example'),
            patch('frontend.views.secrets.token_urlsafe', return_value='onboarding'),
            patch('frontend.views.urllib.request.urlopen', return_value=provider_response),
        ):
            payment_response = client.post(
                '/api/payments/initialize/',
                data=json.dumps({'plan_tier': 'standard'}),
                content_type='application/json',
                HTTP_X_CSRFTOKEN=client.cookies['csrftoken'].value,
            )

        self.assertEqual(payment_response.status_code, 201)
        self.assertEqual(payment_response.json()['authorization_url'], 'https://checkout.paystack.com/onboarding')
        subscription = Subscription.objects.get(reference='procac-onboarding')
        self.assertEqual(subscription.plan, 'standard')
        self.assertEqual(subscription.amount, 300_000)

    def test_dashboard_shows_checkout_retry_for_signup_fallback(self):
        user = User.objects.create_user(
            username='retry@example.com',
            email='retry@example.com',
            password='SaferExamplePassword!26',
        )
        ConsultantProfile.objects.create(
            user=user,
            accreditation_number='NBA/ACC/2026/003',
            plan='enterprise',
        )
        self.client.force_login(user)

        response = self.client.get('/dashboard/?payment=required')

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Choose a plan to activate your account.')
        self.assertContains(response, 'data-subscribe-plan="enterprise"')
        self.assertContains(response, 'assets/js/payments.js')

    def test_dashboard_displays_the_active_subscription_tier(self):
        user = User.objects.create_user(
            username='active-plan@example.com',
            email='active-plan@example.com',
            password='SaferExamplePassword!26',
        )
        ConsultantProfile.objects.create(
            user=user,
            accreditation_number='NBA/ACC/ACTIVE/001',
            plan='starter',
        )
        Subscription.objects.create(
            user=user,
            plan='standard',
            amount=300_000,
            reference='active-plan-standard',
            status=Subscription.Status.SUCCESSFUL,
        )
        self.client.force_login(user)

        response = self.client.get('/dashboard/')

        self.assertEqual(response.context['active_plan'], 'Standard')
        self.assertContains(response, 'Standard')

    def test_dashboard_displays_checkout_initialization_error(self):
        user = User.objects.create_user(
            username='retry-error@example.com',
            email='retry-error@example.com',
            password='SaferExamplePassword!26',
        )
        ConsultantProfile.objects.create(
            user=user,
            accreditation_number='NBA/ACC/2026/004',
            plan='standard',
        )
        self.client.force_login(user)

        response = self.client.get(
            '/dashboard/',
            {'payment': 'required', 'payment_error': 'Payment service is not configured.'},
        )

        self.assertContains(response, 'Payment service is not configured.')

    def test_login_authenticates_by_email(self):
        User.objects.create_user(
            username='ada@example.com',
            email='ada@example.com',
            password='SaferExamplePassword!26',
        )

        response = self.client.post('/login/', {
            'email': 'ADA@example.com',
            'password': 'SaferExamplePassword!26',
        })

        self.assertRedirects(response, '/dashboard/', fetch_redirect_response=False)
        self.assertTrue(self.client.session.get('_auth_user_id'))

    def test_login_form_can_switch_an_existing_session_after_authentication(self):
        existing_user = User.objects.create_user(
            username='existing@example.com',
            email='existing@example.com',
            password='SaferExamplePassword!26',
        )
        target_user = User.objects.create_user(
            username='target@example.com',
            email='target@example.com',
            password='SaferExamplePassword!26',
        )
        self.client.force_login(existing_user)

        response = self.client.post('/login/', {
            'email': 'target@example.com',
            'password': 'SaferExamplePassword!26',
        })

        self.assertRedirects(response, '/dashboard/', fetch_redirect_response=False)
        self.assertEqual(
            self.client.session.get('_auth_user_id'),
            str(target_user.pk),
        )

    def test_non_staff_users_cannot_access_admin_panel(self):
        user = User.objects.create_user(
            username='consultant@example.com',
            email='consultant@example.com',
            password='SaferExamplePassword!26',
        )
        self.client.force_login(user)

        response = self.client.get('/admin-panel/')

        self.assertEqual(response.status_code, 403)

    def test_staff_users_can_access_admin_panel(self):
        user = User.objects.create_user(
            username='admin@example.com',
            email='admin@example.com',
            password='SaferExamplePassword!26',
            is_staff=True,
        )
        self.client.force_login(user)

        self.assertEqual(self.client.get('/admin-panel/').status_code, 200)

    def test_encoded_links_redirect_only_to_known_local_pages(self):
        valid_token = base64.urlsafe_b64encode(b'/login/').decode().rstrip('=')
        agency_profile_token = base64.urlsafe_b64encode(b'/agency-profile/').decode().rstrip('=')
        invalid_token = base64.urlsafe_b64encode(b'https://example.com/').decode().rstrip('=')

        self.assertRedirects(
            self.client.get(reverse('encoded_page_link', args=[valid_token])),
            '/login/',
            fetch_redirect_response=False,
        )
        self.assertRedirects(
            self.client.get(reverse('encoded_page_link', args=[agency_profile_token])),
            '/agency-profile/',
            fetch_redirect_response=False,
        )
        self.assertEqual(
            self.client.get(reverse('encoded_page_link', args=[invalid_token])).status_code,
            400,
        )

    def test_logout_requires_post_and_ends_session(self):
        user = User.objects.create_user(
            username='consultant@example.com',
            email='consultant@example.com',
            password='SaferExamplePassword!26',
        )
        self.client.force_login(user)

        self.assertEqual(self.client.get('/logout/').status_code, 405)
        response = self.client.post('/logout/')

        self.assertRedirects(response, '/login/', fetch_redirect_response=False)
        self.assertNotIn('_auth_user_id', self.client.session)


class ClientIntakeLinkWorkflowTest(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(
            username='intake-consultant@example.com',
            email='intake-consultant@example.com',
            password='SaferExamplePassword!26',
        )
        ConsultantProfile.objects.create(
            user=self.user,
            accreditation_number='NBA/ACC/INTAKE/001',
            plan='starter',
        )
        self.client.force_login(self.user)

    def test_consultant_can_generate_and_share_a_unique_intake_link(self):
        response = self.client.post(reverse('generate_intake_link'), {
            'filing_type': 'BN',
            'client_name_hint': 'Remote client',
        })

        self.assertEqual(response.status_code, 200)
        link = ClientIntakeLink.objects.get(consultant=self.user)
        self.assertEqual(response.json()['id'], str(link.pk))
        self.assertTrue(response.json()['url'].endswith(
            f'/portal/fill/{link.token}/',
        ))
        self.assertLessEqual(
            abs((link.expires_at - link.created_at) - timedelta(hours=10)),
            timedelta(seconds=2),
        )
        dashboard = self.client.get(reverse('dashboard'))
        self.assertContains(dashboard, 'Link Sent / Pending Client Entry')
        self.assertContains(dashboard, 'Remote client')

    def test_public_intake_renders_state_lga_and_activity_selects(self):
        link = ClientIntakeLink.objects.create(
            consultant=self.user,
            filing_type='BN',
        )

        response = self.client.get(reverse('client_fill_view', args=[link.token]))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'id="id_state"')
        self.assertContains(response, 'id="id_lga"')
        self.assertContains(response, 'This form expires in 10hrs')
        self.assertContains(response, '10 hours')
        self.assertIn('Ibadan Central', response.context['state_lga_data']['OYO'])
        self.assertIn(
            'Transport & Logistics Services',
            response.context['business_activity_data'][
                'Digital Services - Transport & Logistics Services'
            ],
        )
        self.assertEqual(
            response.context['business_activity_data']['Manufacturing'],
            ('General Manufacturing & Processing',),
        )

    def test_pending_links_reserve_the_remaining_plan_quota(self):
        for index in range(4):
            ClientProfile.objects.create(
                user=self.user,
                entity_name=f'Existing client {index}',
                entity_type='BN',
                email=f'existing-{index}@example.com',
            )

        first_response = self.client.post(reverse('generate_intake_link'), {
            'filing_type': 'BN',
        })
        second_response = self.client.post(reverse('generate_intake_link'), {
            'filing_type': 'LTD',
        })

        self.assertEqual(first_response.status_code, 200)
        self.assertEqual(second_response.status_code, 403)
        self.assertEqual(ClientIntakeLink.objects.filter(consultant=self.user).count(), 1)

    def test_submission_binds_consultant_and_filing_type_and_invalidates_link(self):
        link = ClientIntakeLink.objects.create(
            consultant=self.user,
            filing_type='BN',
            client_name_hint='Expected reference',
        )

        response = self.client.post(reverse('client_fill_view', args=[link.token]), {
            'entity_type': 'IT',
            'proposed_name_1': 'Remote Business',
            'proposed_name_2': 'Remote Business Two',
            'email': 'remote-client@example.com',
            'nin': '12345678901',
            'state': 'LAGOS',
            'lga': 'Ikeja',
            'principal_activity': 'Real Estate Activities',
            'specific_activity': 'Real Estate Activities',
            'street_address': '12 Main Street',
            'city': 'Lagos',
            'proprietor_name': 'Ada Client',
            'identity_type': 'NIN',
            'identity_number': '12345678901',
            'proprietor_address': '12 Main Street, Lagos',
        })

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Details securely transmitted to your legal counsel')
        client_profile = ClientProfile.objects.get(intake_link=link)
        self.assertEqual(client_profile.user, self.user)
        self.assertEqual(client_profile.entity_type, 'BN')
        self.assertEqual(client_profile.entity_name, 'Remote Business')
        self.assertEqual(client_profile.nin, '12345678901')
        self.assertEqual(client_profile.state, 'LAGOS')
        self.assertEqual(client_profile.lga, 'Ikeja')
        self.assertEqual(
            client_profile.principal_activity,
            'Real Estate Activities',
        )
        self.assertEqual(
            client_profile.specific_activity,
            'Real Estate Activities',
        )
        self.assertEqual(client_profile.directors[0]['full_name'], 'Ada Client')
        link.refresh_from_db()
        self.assertTrue(link.is_used)
        status_response = self.client.get(reverse('intake_link_status'))
        self.assertEqual(status_response.status_code, 200)
        submitted_link = next(
            item for item in status_response.json()['links']
            if item['id'] == str(link.pk)
        )
        self.assertEqual(submitted_link['client']['entity_name'], 'Remote Business')
        self.assertEqual(
            self.client.get(reverse('client_fill_view', args=[link.token])).status_code,
            404,
        )

    def test_invalid_submission_does_not_consume_link(self):
        link = ClientIntakeLink.objects.create(
            consultant=self.user,
            filing_type='LTD',
        )

        response = self.client.post(reverse('client_fill_view', args=[link.token]), {
            'proposed_name_1': 'Missing contact',
        })

        self.assertEqual(response.status_code, 400)
        self.assertContains(response, 'This field is required.', status_code=400)
        link.refresh_from_db()
        self.assertFalse(link.is_used)
        self.assertFalse(ClientProfile.objects.filter(intake_link=link).exists())

    def test_public_intake_rejects_lga_or_activity_outside_selected_options(self):
        link = ClientIntakeLink.objects.create(
            consultant=self.user,
            filing_type='BN',
        )
        submission = {
            'proposed_name_1': 'Remote Business',
            'email': 'remote-client@example.com',
            'state': 'LAGOS',
            'lga': 'Ibadan North',
            'principal_activity': 'Manufacturing',
            'specific_activity': 'Real Estate Activities',
            'proprietor_name': 'Ada Client',
        }

        response = self.client.post(
            reverse('client_fill_view', args=[link.token]),
            submission,
        )

        self.assertEqual(response.status_code, 400)
        self.assertContains(response, 'Choose an LGA for the selected state.', status_code=400)
        self.assertContains(
            response,
            'Choose a specific activity for the selected principal activity.',
            status_code=400,
        )
        link.refresh_from_db()
        self.assertFalse(link.is_used)

    def test_expired_and_unknown_links_show_safe_error_pages(self):
        expired_link = ClientIntakeLink.objects.create(
            consultant=self.user,
            filing_type='IT',
            expires_at=timezone.now() - timedelta(seconds=1),
        )

        expired_response = self.client.get(
            reverse('client_fill_view', args=[expired_link.token]),
        )
        invalid_response = self.client.get(
            reverse('client_fill_view', args=['00000000-0000-0000-0000-000000000000']),
        )

        self.assertEqual(expired_response.status_code, 410)
        self.assertContains(expired_response, 'Link expired', status_code=410)
        self.assertEqual(invalid_response.status_code, 404)
        self.assertContains(invalid_response, 'Link already used or invalid', status_code=404)

    def test_intake_status_is_private_to_the_consultant(self):
        link = ClientIntakeLink.objects.create(
            consultant=self.user,
            filing_type='BN',
        )
        other_user = User.objects.create_user(
            username='other-intake-consultant@example.com',
            email='other-intake-consultant@example.com',
            password='SaferExamplePassword!26',
        )
        self.client.force_login(other_user)

        response = self.client.get(reverse('intake_link_status'))

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()['links'], [])
        self.assertNotIn(str(link.pk), response.content.decode())


class SuperAdminDashboardTest(TestCase):
    def setUp(self):
        self.admin = User.objects.create_superuser(
            username='platform-admin',
            email='platform-admin@example.com',
            password='SaferExamplePassword!26',
        )
        self.consultant = User.objects.create_user(
            username='audit-consultant@example.com',
            email='audit-consultant@example.com',
            password='SaferExamplePassword!26',
        )
        self.profile = ConsultantProfile.objects.create(
            user=self.consultant,
            accreditation_number='NBA/ACC/SUPERADMIN/001',
            firm_name='Audit Legal',
            plan='standard',
        )

    def test_super_admin_routes_reject_anonymous_and_regular_users(self):
        regular_client = Client()
        anonymous_response = regular_client.get('/super-admin/')
        self.assertRedirects(
            anonymous_response,
            '/login/?next=/super-admin/',
            fetch_redirect_response=False,
        )

        regular_client.force_login(self.consultant)
        regular_response = regular_client.get('/super-admin/')
        self.assertRedirects(
            regular_response,
            '/login/?next=/super-admin/',
            fetch_redirect_response=False,
        )
        self.assertEqual(
            regular_client.get(
                f'/super-admin/consultant/{self.consultant.pk}/',
            ).status_code,
            302,
        )

    def test_dashboard_aggregates_metrics_and_paginates_consultants(self):
        client_profile = ClientProfile.objects.create(
            user=self.consultant,
            entity_name='Admin inspected client',
            entity_type='BN',
            email='admin-client@example.com',
        )
        ClientIntakeLink.objects.create(
            consultant=self.consultant,
            filing_type='BN',
            is_used=True,
        )
        ClientIntakeLink.objects.create(
            consultant=self.consultant,
            filing_type='LTD',
        )
        self.client.force_login(self.admin)

        response = self.client.get('/super-admin/')

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context['metrics'], {
            'consultants': 1,
            'filings': 1,
            'daily_links': 2,
            'conversion_rate': 50.0,
        })
        self.assertEqual(response.context['consultants'][0]['client_count'], 1)
        self.assertEqual(response.context['consultants'][0]['quota_display'], '2 / 15')
        self.assertEqual(client_profile.user, self.consultant)

        ajax_response = self.client.get(
            '/super-admin/?q=audit&page=1',
            HTTP_X_REQUESTED_WITH='XMLHttpRequest',
        )
        self.assertEqual(ajax_response.status_code, 200)
        self.assertEqual(ajax_response.json()['count'], 1)
        self.assertEqual(ajax_response.json()['results'][0]['email'], self.consultant.email)

    def test_admin_can_set_numeric_and_unlimited_quota_overrides(self):
        self.client.force_login(self.admin)
        detail_url = f'/super-admin/consultant/{self.consultant.pk}/'
        quota_url = f'{detail_url}quota/'

        custom_response = self.client.post(quota_url, {
            'quota_mode': 'custom',
            'profile_limit': '2',
        })
        self.assertRedirects(custom_response, detail_url)
        self.profile.refresh_from_db()
        self.assertTrue(self.profile.has_profile_limit_override)
        self.assertEqual(self.profile.profile_limit_for_plan(), 2)

        unlimited_response = self.client.post(quota_url, {
            'quota_mode': 'unlimited',
        })
        self.assertRedirects(unlimited_response, detail_url)
        self.profile.refresh_from_db()
        self.assertTrue(self.profile.has_profile_limit_override)
        self.assertIsNone(self.profile.profile_limit_for_plan())

        plan_response = self.client.post(quota_url, {'quota_mode': 'plan'})
        self.assertRedirects(plan_response, detail_url)
        self.profile.refresh_from_db()
        self.assertFalse(self.profile.has_profile_limit_override)
        self.assertEqual(self.profile.profile_limit_for_plan(), 15)

    def test_quota_override_is_enforced_by_consultant_profile_creation(self):
        self.profile.has_profile_limit_override = True
        self.profile.profile_limit_override = 0
        self.profile.save(update_fields=['has_profile_limit_override', 'profile_limit_override'])
        self.client.force_login(self.consultant)

        blocked_response = self.client.post('/dashboard/', {
            'entity_type': 'BN',
            'proposed_name_1': 'Blocked by custom quota',
            'email': 'blocked@example.com',
        })

        self.assertRedirects(blocked_response, '/plans/', fetch_redirect_response=False)
        self.assertFalse(ClientProfile.objects.filter(user=self.consultant).exists())

        self.profile.profile_limit_override = None
        self.profile.save(update_fields=['profile_limit_override'])
        allowed_response = self.client.post('/dashboard/', {
            'entity_type': 'BN',
            'proposed_name_1': 'Allowed by unlimited quota',
            'email': 'allowed@example.com',
        })

        self.assertRedirects(allowed_response, '/dashboard/', fetch_redirect_response=False)
        self.assertEqual(ClientProfile.objects.filter(user=self.consultant).count(), 1)

    def test_admin_can_deactivate_consultant_and_inspect_links_and_audit_logs(self):
        client_profile = ClientProfile.objects.create(
            user=self.consultant,
            entity_name='Inspection client',
            entity_type='BN',
            email='inspection@example.com',
        )
        active_link = ClientIntakeLink.objects.create(
            consultant=self.consultant,
            filing_type='BN',
            client_name_hint='Active link',
        )
        expired_link = ClientIntakeLink.objects.create(
            consultant=self.consultant,
            filing_type='LTD',
            expires_at=timezone.now() - timedelta(hours=1),
        )
        InjectionAuditLog.objects.create(
            consultant=self.consultant,
            client_profile=client_profile,
            status=InjectionAuditLog.Status.SUCCESS,
            fields_populated=7,
        )
        self.client.force_login(self.admin)

        response = self.client.get(
            f'/super-admin/consultant/{self.consultant.pk}/',
        )
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Inspection client')
        self.assertContains(response, 'Active link')
        self.assertContains(response, 'Active')
        self.assertContains(response, 'Expired')
        self.assertContains(response, 'DOM injection audit')
        self.assertContains(response, '7')

        deactivate_response = self.client.post(
            f'/super-admin/consultant/{self.consultant.pk}/status/',
            {'active': 'false', 'next': 'detail'},
        )
        self.assertRedirects(
            deactivate_response,
            f'/super-admin/consultant/{self.consultant.pk}/',
        )
        self.consultant.refresh_from_db()
        self.assertFalse(self.consultant.is_active)
        self.assertEqual(active_link.consultant, self.consultant)
        self.assertEqual(expired_link.consultant, self.consultant)


class ExtensionApiTest(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(
            username='extension@example.com',
            email='extension@example.com',
            password='SaferExamplePassword!26',
        )

    def test_extension_endpoints_report_unauthenticated_status_as_json(self):
        for path in ('/api/extension/status/', '/api/extension/clients/'):
            with self.subTest(path=path):
                response = self.client.get(path)
                self.assertEqual(response.status_code, 401)
                self.assertFalse(response.json()['authenticated'])
                self.assertEqual(response['Cache-Control'], 'private, no-store')

    def test_status_returns_only_a_successful_subscription_tier(self):
        self.client.force_login(self.user)
        subscription = Subscription.objects.create(
            user=self.user,
            plan='standard',
            amount=300_000,
            reference='extension-pending',
        )

        pending_response = self.client.get('/api/extension/status/')
        self.assertIsNone(pending_response.json()['active_subscription_tier'])

        subscription.status = Subscription.Status.SUCCESSFUL
        subscription.save(update_fields=['status', 'updated_at'])
        active_response = self.client.get('/api/extension/status/')

        self.assertEqual(active_response.status_code, 200)
        self.assertEqual(active_response.json()['user'], 'extension@example.com')
        self.assertEqual(active_response.json()['active_subscription_tier'], 'standard')
        self.assertEqual(active_response['Cache-Control'], 'private, no-store')

    def test_agency_profile_saves_firm_and_presenter_settings(self):
        ConsultantProfile.objects.create(
            user=self.user,
            accreditation_number='CAC/ACC/2024/0918',
            firm_name='Old Firm',
        )
        self.client.force_login(self.user)

        response = self.client.post('/agency-profile/', {
            'full_name': 'Ada Consultant',
            'email': 'ada-consultant@example.com',
            'accreditation_number': 'tampered accreditation',
            'phone_number': '+234 800 111 2222',
            'firm_name': 'Adebayo & Co. Legal Practitioners',
            'office_address': '12 Marina Road, Lagos',
            'call_to_bar_number': 'NBA/2018/12345',
            'presenter_state': 'Lagos',
            'presenter_lga': 'Eti-Osa',
            'presenter_phone': '+234 800 333 4444',
            'presenter_email': 'presenter@example.com',
        })

        self.assertRedirects(response, '/agency-profile/', fetch_redirect_response=False)
        profile = ConsultantProfile.objects.get(user=self.user)
        self.user.refresh_from_db()
        self.assertEqual(profile.accreditation_number, 'CAC/ACC/2024/0918')
        self.assertEqual(profile.firm_name, 'Adebayo & Co. Legal Practitioners')
        self.assertEqual(profile.call_to_bar_number, 'NBA/2018/12345')
        self.assertEqual(profile.presenter_state, 'Lagos')
        self.assertEqual(profile.presenter_lga, 'Eti-Osa')
        self.assertEqual(profile.presenter_phone, '+234 800 333 4444')
        self.assertEqual(profile.presenter_email, 'presenter@example.com')
        self.assertEqual(self.user.email, 'ada-consultant@example.com')
        self.assertEqual(self.user.username, 'ada-consultant@example.com')

    def test_regenerated_extension_key_authenticates_api_and_returns_presenter_defaults(self):
        profile = ConsultantProfile.objects.create(
            user=self.user,
            accreditation_number='CAC/ACC/KEY/001',
            presenter_state='Lagos',
            presenter_lga='Eti-Osa',
            presenter_phone='+234 800 333 4444',
            presenter_email='presenter@example.com',
        )
        self.client.force_login(self.user)

        response = self.client.post('/agency-profile/', {'action': 'regenerate_token'})

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Copy this key into your ProCAC Chrome Extension now.')
        profile.refresh_from_db()
        token = response.context['token_revealed']
        self.assertTrue(token)
        self.assertNotEqual(profile.extension_token_hash, token)
        self.assertEqual(
            profile.extension_token_hash,
            hashlib.sha256(token.encode()).hexdigest(),
        )

        status_response = self.client.get(
            '/api/extension/status/',
            headers={'Authorization': f'Bearer {token}'},
        )
        self.assertEqual(status_response.status_code, 200)
        self.assertEqual(
            status_response.json()['presenter_defaults'],
            {
                'state': 'Lagos',
                'lga': 'Eti-Osa',
                'phone': '+234 800 333 4444',
                'email': 'presenter@example.com',
            },
        )

        second_response = self.client.post(
            '/agency-profile/',
            {'action': 'regenerate_token'},
        )
        replacement_token = second_response.context['token_revealed']
        self.assertNotEqual(token, replacement_token)
        revoked_response = self.client.get(
            '/api/extension/status/',
            headers={'Authorization': f'Bearer {token}'},
        )
        self.assertEqual(revoked_response.status_code, 401)
        profile.refresh_from_db()
        self.assertEqual(
            profile.extension_token_hash,
            hashlib.sha256(replacement_token.encode()).hexdigest(),
        )
        self.assertNotContains(self.client.get('/agency-profile/'), replacement_token)

    def test_invalid_extension_key_does_not_fall_back_to_signed_in_session(self):
        self.client.force_login(self.user)

        response = self.client.get(
            '/api/extension/status/',
            headers={'Authorization': 'Bearer invalid-key'},
        )

        self.assertEqual(response.status_code, 401)
        self.assertFalse(response.json()['authenticated'])

    def test_extension_key_can_create_a_client_without_a_session_cookie(self):
        token = 'one-time-extension-secret'
        ConsultantProfile.objects.create(
            user=self.user,
            accreditation_number='CAC/ACC/KEY/002',
            extension_token_hash=hashlib.sha256(token.encode()).hexdigest(),
        )

        csrf_client = Client(enforce_csrf_checks=True)
        response = csrf_client.post(
            '/api/extension/clients/',
            data=json.dumps({
                'entity_type': 'BN',
                'entity_name': 'Token Created Client',
                'proposed_name_1': 'Token Created Client',
                'email': 'token-client@example.com',
            }),
            content_type='application/json',
            headers={'Authorization': f'Bearer {token}'},
        )

        self.assertEqual(response.status_code, 201)
        self.assertEqual(
            ClientProfile.objects.get(user=self.user).entity_name,
            'Token Created Client',
        )

    def test_extension_key_records_an_injection_audit_for_its_own_client(self):
        token = 'injection-audit-extension-secret'
        ConsultantProfile.objects.create(
            user=self.user,
            accreditation_number='CAC/ACC/AUDIT/001',
            extension_token_hash=hashlib.sha256(token.encode()).hexdigest(),
        )
        client_profile = ClientProfile.objects.create(
            user=self.user,
            entity_name='Audited Client',
            entity_type='BN',
            email='audited-client@example.com',
        )
        other_user = User.objects.create_user(
            username='audit-other@example.com',
            email='audit-other@example.com',
            password='SaferExamplePassword!26',
        )
        other_profile = ClientProfile.objects.create(
            user=other_user,
            entity_name='Private Client',
            entity_type='BN',
            email='private-client@example.com',
        )
        audit_client = Client(enforce_csrf_checks=True)
        endpoint = '/api/extension/injection-audits/'

        response = audit_client.post(
            endpoint,
            data=json.dumps({
                'client_id': client_profile.pk,
                'status': 'success',
                'fields_populated': 9,
            }),
            content_type='application/json',
            headers={'Authorization': f'Bearer {token}'},
        )
        denied_response = audit_client.post(
            endpoint,
            data=json.dumps({
                'client_id': other_profile.pk,
                'status': 'failure',
                'fields_populated': 0,
            }),
            content_type='application/json',
            headers={'Authorization': f'Bearer {token}'},
        )

        self.assertEqual(response.status_code, 201)
        self.assertEqual(denied_response.status_code, 404)
        audit = InjectionAuditLog.objects.get()
        self.assertEqual(audit.consultant, self.user)
        self.assertEqual(audit.client_profile, client_profile)
        self.assertEqual(audit.status, InjectionAuditLog.Status.SUCCESS)
        self.assertEqual(audit.fields_populated, 9)

    def test_deactivated_consultant_extension_key_is_rejected(self):
        token = 'inactive-extension-secret'
        ConsultantProfile.objects.create(
            user=self.user,
            accreditation_number='CAC/ACC/AUDIT/INACTIVE',
            extension_token_hash=hashlib.sha256(token.encode()).hexdigest(),
        )
        self.user.is_active = False
        self.user.save(update_fields=['is_active'])

        response = self.client.get(
            '/api/extension/status/',
            headers={'Authorization': f'Bearer {token}'},
        )

        self.assertEqual(response.status_code, 401)
        self.assertFalse(response.json()['authenticated'])

    def test_cookie_authenticated_extension_post_still_requires_csrf(self):
        csrf_client = Client(enforce_csrf_checks=True)
        csrf_client.force_login(self.user)

        response = csrf_client.post('/api/extension/clients/', data=json.dumps({
            'entity_type': 'BN',
            'entity_name': 'CSRF protected',
            'email': 'csrf@example.com',
        }), content_type='application/json')

        self.assertEqual(response.status_code, 403)

    def test_agency_profile_page_shows_account_status_and_settings_sections(self):
        ConsultantProfile.objects.create(
            user=self.user,
            accreditation_number='CAC/ACC/PROFILE/001',
            firm_name='Adebayo & Co. Legal Practitioners',
            plan='standard',
        )
        Subscription.objects.create(
            user=self.user,
            plan='standard',
            amount=300_000,
            reference='agency-profile-standard',
            status=Subscription.Status.SUCCESSFUL,
        )
        self.client.force_login(self.user)

        response = self.client.get('/agency-profile/')

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'ProCAC')
        self.assertContains(response, 'CAC/ACC/PROFILE/001')
        self.assertContains(response, 'Standard Plan · Active')
        self.assertContains(response, 'Firm details')
        self.assertContains(response, 'Lead consultant / agent')
        self.assertContains(response, 'CAC portal integration defaults')
        self.assertContains(response, 'Regenerate Token')
        self.assertContains(response, 'name="csrfmiddlewaretoken"')

    def test_clients_endpoint_returns_only_the_signed_in_users_profiles(self):
        other_user = User.objects.create_user(
            username='other-extension@example.com',
            email='other-extension@example.com',
            password='SaferExamplePassword!26',
        )
        own_profile = ClientProfile.objects.create(
            user=self.user,
            entity_name='My Client Limited',
            entity_type='LTD',
            nin='12345678901',
            email='client@example.com',
            state='LAGOS',
            lga='Ikeja',
            principal_activity='Real Estate Activities',
            specific_activity='Real Estate Activities',
            nature_category='Information and communication',
            specific_nature='Software development',
            objectives='Consulting services',
        )
        ClientProfile.objects.create(
            user=other_user,
            entity_name='Other Client',
            entity_type='BN',
            nin='10987654321',
            email='other-client@example.com',
        )
        self.client.force_login(self.user)

        response = self.client.get('/api/extension/clients/')

        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            response.json()['clients'],
            [{
                'id': own_profile.pk,
                'entity_name': 'My Client Limited',
                'entity_type': 'LTD',
                'nin': '12345678901',
                'email': 'client@example.com',
                'proposed_name_1': '',
                'proposed_name_2': '',
                'classification': '',
                'business_type': '',
                'principal_activity': 'Real Estate Activities',
                'specific_activity': 'Real Estate Activities',
                'principal_business_activity': 'Real Estate Activities',
                'specific_business_activity': 'Real Estate Activities',
                'location': {'state': 'LAGOS', 'lga': 'Ikeja'},
                'business_activities': {
                    'principal': 'Real Estate Activities',
                    'specific': 'Real Estate Activities',
                },
                'nature_category': 'Information and communication',
                'specific_nature': 'Software development',
                'objectives': 'Consulting services',
                'street_address': '',
                'city': '',
                'lga': 'Ikeja',
                'state': 'LAGOS',
                'phone': '',
                'commencement_date': None,
                'directors': [],
            }],
        )
        self.assertEqual(response['Cache-Control'], 'private, no-store')

    def test_clients_endpoint_does_not_expose_draft_profiles(self):
        ClientProfile.objects.create(
            user=self.user,
            entity_name='Unfinished client',
            entity_type='BN',
            email='',
            status=ClientProfile.Status.DRAFT,
        )
        self.client.force_login(self.user)

        response = self.client.get('/api/extension/clients/')

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()['clients'], [])

    def test_intake_page_uses_workspace_layout_and_persists_a_draft(self):
        self.client.force_login(self.user)

        page = self.client.get('/intake/')
        self.assertEqual(page.status_code, 200)
        self.assertContains(page, 'ProCAC')
        self.assertContains(page, 'New Client Intake')
        self.assertContains(page, 'Validate NIN Format')
        self.assertContains(page, 'name="csrfmiddlewaretoken"')

        response = self.client.post('/intake/', {
            'entity_type': 'BN',
            'action': 'draft',
            'directors_json': '',
        })

        draft = ClientProfile.objects.get(user=self.user)
        self.assertRedirects(response, f'/intake/?draft={draft.pk}', fetch_redirect_response=False)
        self.assertEqual(draft.status, ClientProfile.Status.DRAFT)
        self.assertEqual(draft.entity_name, '')
        self.assertEqual(draft.email, '')

    def test_intake_generate_saves_a_ready_profile_with_primary_applicant(self):
        self.client.force_login(self.user)

        response = self.client.post('/intake/', {
            'entity_type': 'BN',
            'entity_name': 'Northstar Services',
            'proposed_name_1': 'Northstar Services',
            'proposed_name_2': 'Northstar Trading',
            'email': 'applicant@example.com',
            'phone': '+2348012345678',
            'street_address': '12 Marina Road',
            'nin': '12345678901',
            'directors_json': json.dumps([{
                'full_name': 'Ada Applicant',
                'gender': 'Female',
                'identity_type': 'nin',
                'identity_number': '12345678901',
                'email': 'applicant@example.com',
            }]),
            'action': 'generate',
        })

        self.assertRedirects(response, '/dashboard/', fetch_redirect_response=False)
        profile = ClientProfile.objects.get(user=self.user)
        self.assertEqual(profile.status, ClientProfile.Status.READY)
        self.assertEqual(profile.entity_name, 'Northstar Services')
        self.assertEqual(profile.directors[0]['full_name'], 'Ada Applicant')

    def test_existing_draft_can_be_resumed_and_generated_without_a_second_record(self):
        draft = ClientProfile.objects.create(
            user=self.user,
            entity_name='Draft name',
            entity_type='BN',
            email='',
            status=ClientProfile.Status.DRAFT,
        )
        self.client.force_login(self.user)

        page = self.client.get(f'/intake/?draft={draft.pk}')
        self.assertEqual(page.status_code, 200)
        self.assertContains(page, f'name="draft_id" value="{draft.pk}"')
        self.assertContains(page, 'value="Draft name"')

        response = self.client.post('/intake/', {
            'draft_id': str(draft.pk),
            'entity_type': 'BN',
            'entity_name': 'Completed draft name',
            'proposed_name_1': 'Completed draft name',
            'email': 'completed@example.com',
            'phone': '+2348012345678',
            'street_address': '12 Marina Road',
            'directors_json': json.dumps([{'full_name': 'Ada Applicant'}]),
            'action': 'generate',
        })

        self.assertRedirects(response, '/dashboard/', fetch_redirect_response=False)
        self.assertEqual(ClientProfile.objects.filter(user=self.user).count(), 1)
        draft.refresh_from_db()
        self.assertEqual(draft.status, ClientProfile.Status.READY)
        self.assertEqual(draft.entity_name, 'Completed draft name')

    def test_resuming_a_draft_cannot_exceed_a_different_type_allocation(self):
        ConsultantProfile.objects.create(
            user=self.user,
            accreditation_number='NBA/ACC/INTAKE/ALLOCATION',
            plan='standard',
        )
        draft = ClientProfile.objects.create(
            user=self.user,
            entity_name='Business draft',
            entity_type='BN',
            email='',
            status=ClientProfile.Status.DRAFT,
        )
        ClientProfile.objects.bulk_create([
            ClientProfile(
                user=self.user,
                entity_name=f'Limited company {index}',
                entity_type='LTD',
                email=f'limited-{index}@example.com',
            )
            for index in range(5)
        ])
        self.client.force_login(self.user)

        response = self.client.post('/intake/', {
            'draft_id': str(draft.pk),
            'entity_type': 'LTD',
            'entity_name': 'Business draft',
            'proposed_name_1': 'Business draft',
            'email': 'draft@example.com',
            'directors_json': '[]',
            'action': 'generate',
        })

        self.assertRedirects(response, '/plans/', fetch_redirect_response=False)
        draft.refresh_from_db()
        self.assertEqual(draft.entity_type, 'BN')
        self.assertEqual(draft.status, ClientProfile.Status.DRAFT)

    def test_dashboard_saves_client_profiles_for_the_signed_in_user(self):
        self.client.force_login(self.user)

        response = self.client.post('/dashboard/', {
            'entity_name': 'New Client Name',
            'entity_type': 'BN',
            'nin': '12345678901',
            'email': 'new-client@example.com',
            'nature_category': 'Retail trade',
            'specific_nature': 'Retail sale of clothing',
            'objectives': 'Retail trade',
        })

        self.assertRedirects(response, '/dashboard/', fetch_redirect_response=False)
        client = ClientProfile.objects.get(user=self.user)
        self.assertEqual(client.entity_name, 'New Client Name')
        self.assertEqual(client.entity_type, 'BN')
        self.assertEqual(client.nin, '12345678901')
        self.assertEqual(client.nature_category, 'Retail trade')
        self.assertEqual(client.specific_nature, 'Retail sale of clothing')
        dashboard_response = self.client.get('/dashboard/')
        self.assertContains(dashboard_response, 'New Client Name')
        self.assertContains(dashboard_response, 'new-client@example.com')

    def test_enterprise_plan_caps_creation_at_twenty_five_profiles(self):
        profile = ConsultantProfile.objects.create(
            user=self.user,
            accreditation_number='NBA/ACC/LIMIT/ENTERPRISE',
            plan='enterprise',
        )
        ClientProfile.objects.bulk_create([
            ClientProfile(
                user=self.user,
                entity_name=f'Enterprise Client {index}',
                entity_type='BN',
                email=f'enterprise-{index}@example.com',
            )
            for index in range(25)
        ])

        can_add, error = profile.can_add_client('LTD')

        self.assertFalse(can_add)
        self.assertIn('profile limit', error)

    def test_starter_plan_blocks_profile_creation_after_five_profiles(self):
        ConsultantProfile.objects.create(
            user=self.user,
            accreditation_number='NBA/ACC/LIMIT/STARTER',
            plan='starter',
        )
        for index in range(5):
            ClientProfile.objects.create(
                user=self.user,
                entity_name=f'Starter Client {index}',
                entity_type='BN',
                email=f'starter-{index}@example.com',
            )
        self.client.force_login(self.user)

        response = self.client.post('/dashboard/', {
            'entity_name': 'Sixth Starter Client',
            'entity_type': 'LTD',
            'email': 'starter-sixth@example.com',
        })

        self.assertRedirects(response, '/plans/', fetch_redirect_response=False)
        self.assertEqual(ClientProfile.objects.filter(user=self.user).count(), 5)
        plans_response = self.client.get('/plans/')
        self.assertContains(
            plans_response,
            'Your plan profile limit is reached. Upgrade your plan to add more clients.',
        )

    def test_standard_plan_enforces_five_profiles_per_entity_type(self):
        ConsultantProfile.objects.create(
            user=self.user,
            accreditation_number='NBA/ACC/LIMIT/STANDARD',
            plan='standard',
        )
        for index in range(5):
            ClientProfile.objects.create(
                user=self.user,
                entity_name=f'Standard BN {index}',
                entity_type='BN',
                email=f'standard-bn-{index}@example.com',
            )
        self.client.force_login(self.user)

        response = self.client.post('/dashboard/', {
            'entity_name': 'Sixth Standard BN',
            'entity_type': 'BN',
            'email': 'standard-bn-sixth@example.com',
        })

        self.assertRedirects(response, '/plans/', fetch_redirect_response=False)
        self.assertEqual(ClientProfile.objects.filter(user=self.user).count(), 5)

    def test_platinum_plan_allows_more_than_twenty_five_profiles(self):
        ConsultantProfile.objects.create(
            user=self.user,
            accreditation_number='NBA/ACC/LIMIT/PLATINUM',
            plan='ultimate_enterprise',
        )
        for index in range(25):
            ClientProfile.objects.create(
                user=self.user,
                entity_name=f'Platinum Client {index}',
                entity_type='BN',
                email=f'platinum-{index}@example.com',
            )
        self.client.force_login(self.user)

        response = self.client.post('/dashboard/', {
            'entity_name': 'Twenty-sixth Platinum Client',
            'entity_type': 'IT',
            'email': 'platinum-26@example.com',
        })

        self.assertRedirects(response, '/dashboard/', fetch_redirect_response=False)
        self.assertEqual(ClientProfile.objects.filter(user=self.user).count(), 26)

    def test_dashboard_displays_live_client_profile_counts(self):
        ClientProfile.objects.create(
            user=self.user,
            entity_name='Ready Client One',
            entity_type='BN',
            email='ready-one@example.com',
        )
        ClientProfile.objects.create(
            user=self.user,
            entity_name='Ready Client Two',
            entity_type='LTD',
            email='ready-two@example.com',
        )
        ClientProfile.objects.create(
            user=self.user,
            entity_name='Registered Client',
            entity_type='IT',
            email='registered@example.com',
            status=ClientProfile.Status.COMPLETED,
        )
        self.client.force_login(self.user)

        response = self.client.get('/dashboard/')

        self.assertEqual(response.context['total_clients'], 3)
        self.assertEqual(response.context['ready_for_fill'], 2)
        self.assertEqual(response.context['registered_clients'], 1)
        self.assertContains(response, '3 / 5 profiles used')
        rendered_html = response.content.decode()
        for count in (3, 2, 1):
            with self.subTest(count=count):
                self.assertRegex(rendered_html, rf'<h3[^>]*>\s*{count}\s*</h3>')

    def test_dashboard_shows_profile_form_errors(self):
        self.client.force_login(self.user)

        response = self.client.post('/dashboard/', {
            'entity_name': 'Invalid Client',
            'entity_type': 'BN',
            'nin': '123',
            'email': 'invalid-client@example.com',
            'objectives': '',
        })

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Enter an 11-digit NIN.')
        self.assertContains(response, 'data-show-on-load="true"')
        self.assertEqual(ClientProfile.objects.count(), 0)

    def test_extension_status_is_read_only_but_clients_endpoint_accepts_json_posts(self):
        self.client.force_login(self.user)

        self.assertEqual(self.client.post('/api/extension/status/').status_code, 405)
        self.assertEqual(self.client.post('/api/extension/clients/').status_code, 400)

    def test_extension_client_creation_returns_actionable_403_at_plan_limit(self):
        ConsultantProfile.objects.create(
            user=self.user,
            accreditation_number='NBA/ACC/EXTENSION/LIMIT',
            plan='starter',
        )
        ClientProfile.objects.bulk_create([
            ClientProfile(
                user=self.user,
                entity_name=f'Starter Extension Client {index}',
                entity_type='BN',
                email=f'starter-extension-{index}@example.com',
            )
            for index in range(5)
        ])
        self.client.force_login(self.user)

        response = self.client.post(
            '/api/extension/clients/',
            data=json.dumps({
                'entity_name': 'Blocked Extension Client',
                'entity_type': 'IT',
                'email': 'blocked-extension@example.com',
            }),
            content_type='application/json',
        )

        self.assertEqual(response.status_code, 403)
        self.assertIn('Upgrade your plan', response.json()['error'])
        self.assertEqual(response.json()['upgrade_url'], '/plans/')
        self.assertEqual(ClientProfile.objects.filter(user=self.user).count(), 5)

    def test_extension_client_creation_saves_valid_profile(self):
        ConsultantProfile.objects.create(
            user=self.user,
            accreditation_number='NBA/ACC/EXTENSION/CREATE',
            plan='starter',
        )
        self.client.force_login(self.user)

        response = self.client.post(
            '/api/extension/clients/',
            data=json.dumps({
                'entity_name': 'Extension Created Client',
                'entity_type': 'BN',
                'email': 'created-extension@example.com',
            }),
            content_type='application/json',
        )

        self.assertEqual(response.status_code, 201)
        self.assertTrue(response.json()['created'])
        self.assertEqual(
            ClientProfile.objects.get(user=self.user).entity_name,
            'Extension Created Client',
        )

    def test_extension_client_creation_enforces_standard_category_allocation(self):
        ConsultantProfile.objects.create(
            user=self.user,
            accreditation_number='NBA/ACC/EXTENSION/STANDARD',
            plan='standard',
        )
        Subscription.objects.create(
            user=self.user,
            plan='standard',
            amount=300_000,
            reference='extension-standard-active',
            status=Subscription.Status.SUCCESSFUL,
        )
        ClientProfile.objects.bulk_create([
            ClientProfile(
                user=self.user,
                entity_name=f'Standard Extension BN {index}',
                entity_type='BN',
                email=f'standard-extension-bn-{index}@example.com',
            )
            for index in range(5)
        ])
        self.client.force_login(self.user)

        response = self.client.post(
            '/api/extension/clients/',
            data=json.dumps({
                'entity_name': 'Sixth Standard Extension BN',
                'entity_type': 'BN',
                'email': 'standard-extension-sixth@example.com',
            }),
            content_type='application/json',
        )

        self.assertEqual(response.status_code, 403)
        self.assertIn('Business Name allocation is full', response.json()['error'])

    def test_dashboard_shows_standard_plan_allocation_usage(self):
        ConsultantProfile.objects.create(
            user=self.user,
            accreditation_number='NBA/ACC/DASHBOARD/STANDARD',
            plan='standard',
        )
        for entity_type, label in (('BN', 'BN'), ('LTD', 'LTD'), ('IT', 'IT')):
            ClientProfile.objects.create(
                user=self.user,
                entity_name=f'Standard {label}',
                entity_type=entity_type,
                email=f'standard-{label.lower()}-dashboard@example.com',
            )
        self.client.force_login(self.user)

        response = self.client.get('/dashboard/')

        self.assertContains(response, '3 / 15 profiles used')
        self.assertContains(response, 'BN 1/5')
        self.assertContains(response, 'LTD 1/5')
        self.assertContains(response, 'IT 1/5')

    @override_settings(
        CORS_ALLOWED_ORIGINS=['chrome-extension://abcdefghijklmnopabcdefghijklmnop'],
        CORS_ALLOW_CREDENTIALS=True,
        CORS_URLS_REGEX=r'^/api/extension/.*$',
    )
    def test_extension_api_allows_configured_credentialed_origin_only(self):
        self.client.force_login(self.user)
        allowed_origin = 'chrome-extension://abcdefghijklmnopabcdefghijklmnop'

        allowed_response = self.client.get(
            '/api/extension/status/',
            HTTP_ORIGIN=allowed_origin,
        )
        denied_response = self.client.get(
            '/api/extension/status/',
            HTTP_ORIGIN='chrome-extension://ponmlkjihgfedcbaponmlkjihgfedcba',
        )
        unrelated_response = self.client.get(
            '/dashboard/',
            HTTP_ORIGIN=allowed_origin,
        )

        self.assertEqual(
            allowed_response['Access-Control-Allow-Origin'],
            allowed_origin,
        )
        self.assertEqual(allowed_response['Access-Control-Allow-Credentials'], 'true')
        self.assertNotIn('Access-Control-Allow-Origin', denied_response)
        self.assertNotIn('Access-Control-Allow-Origin', unrelated_response)


class PaystackPaymentTest(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(
            username='payer@example.com',
            email='payer@example.com',
            password='SaferExamplePassword!26',
        )
        self.client.force_login(self.user)

    def test_initialize_creates_subscription_with_kobo_amount(self):
        provider_response = MagicMock()
        provider_response.__enter__.return_value.read.return_value = json.dumps({
            'status': True,
            'data': {
                'authorization_url': 'https://checkout.paystack.com/example',
                'access_code': 'access-example',
                'reference': 'procac-reference',
            },
        }).encode()
        with (
            override_settings(PAYSTACK_SECRET_KEY='sk_test_example'),
            patch('frontend.views.secrets.token_urlsafe', return_value='reference'),
            patch('frontend.views.urllib.request.urlopen', return_value=provider_response) as urlopen,
        ):
            response = self.client.post(
                '/api/payments/initialize/',
                data=json.dumps({'plan': 'starter'}),
                content_type='application/json',
            )

        self.assertEqual(response.status_code, 201)
        subscription = Subscription.objects.get(reference='procac-reference')
        self.assertEqual(subscription.amount, 50_000)
        self.assertEqual(subscription.status, Subscription.Status.PENDING)
        self.assertEqual(response.json()['authorization_url'], 'https://checkout.paystack.com/example')
        provider_request = urlopen.call_args.args[0]
        self.assertEqual(
            provider_request.get_header('User-agent'),
            'Mozilla/5.0 (Windows NT 10.0; Win64; x64) '
            'AppleWebKit/537.36 (KHTML, like Gecko) '
            'Chrome/120.0.0.0 Safari/537.36',
        )
        self.assertEqual(provider_request.get_header('Authorization'), 'Bearer sk_test_example')
        self.assertEqual(
            json.loads(provider_request.data)['amount'],
            50_000,
        )

    def test_enterprise_checkout_uses_ten_thousand_naira_amount(self):
        provider_response = MagicMock()
        provider_response.__enter__.return_value.read.return_value = json.dumps({
            'status': True,
            'data': {
                'authorization_url': 'https://checkout.paystack.com/enterprise',
                'access_code': 'access-enterprise',
                'reference': 'procac-enterprise',
            },
        }).encode()
        with (
            override_settings(PAYSTACK_SECRET_KEY='sk_test_example'),
            patch('frontend.views.secrets.token_urlsafe', return_value='enterprise'),
            patch('frontend.views.urllib.request.urlopen', return_value=provider_response),
        ):
            response = self.client.post(
                '/api/payments/initialize/',
                data=json.dumps({'plan': 'enterprise'}),
                content_type='application/json',
            )

        self.assertEqual(response.status_code, 201)
        self.assertEqual(
            Subscription.objects.get(reference='procac-enterprise').amount,
            1_000_000,
        )

    def test_platinum_checkout_uses_thirty_five_thousand_naira_amount(self):
        provider_response = MagicMock()
        provider_response.__enter__.return_value.read.return_value = json.dumps({
            'status': True,
            'data': {
                'authorization_url': 'https://checkout.paystack.com/platinum',
                'access_code': 'access-platinum',
                'reference': 'procac-platinum',
            },
        }).encode()
        with (
            override_settings(PAYSTACK_SECRET_KEY='sk_test_example'),
            patch('frontend.views.secrets.token_urlsafe', return_value='platinum'),
            patch('frontend.views.urllib.request.urlopen', return_value=provider_response),
        ):
            response = self.client.post(
                '/api/payments/initialize/',
                data=json.dumps({'plan': 'ultimate_enterprise'}),
                content_type='application/json',
            )

        self.assertEqual(response.status_code, 201)
        self.assertEqual(
            Subscription.objects.get(reference='procac-platinum').amount,
            3_500_000,
        )

    def test_initialize_rejects_invalid_plan_and_json(self):
        invalid_plan = self.client.post(
            '/api/payments/initialize/',
            data=json.dumps({'plan': []}),
            content_type='application/json',
        )
        invalid_json = self.client.post(
            '/api/payments/initialize/',
            data='{',
            content_type='application/json',
        )

        self.assertEqual(invalid_plan.status_code, 400)
        self.assertEqual(invalid_json.status_code, 400)
        self.assertEqual(Subscription.objects.count(), 0)

    def test_initialize_exposes_actionable_error_when_paystack_rejects_key(self):
        provider_error_body = '{"status":false,"message":"Invalid key"}'
        error = urllib.error.HTTPError(
            'https://api.paystack.co/transaction/initialize',
            401,
            'Unauthorized',
            {},
            io.BytesIO(provider_error_body.encode()),
        )
        with (
            override_settings(PAYSTACK_SECRET_KEY='sk_test_invalid'),
            patch('frontend.views.secrets.token_urlsafe', return_value='rejected'),
            patch('frontend.views.urllib.request.urlopen', side_effect=error),
            patch('frontend.views.logger.error') as log_error,
        ):
            response = self.client.post(
                '/api/payments/initialize/',
                data=json.dumps({'plan_tier': 'premium'}),
                content_type='application/json',
            )

        self.assertEqual(response.status_code, 502)
        self.assertIn('secret key', response.json()['error'])
        self.assertIn(
            provider_error_body,
            ' '.join(str(arg) for arg in log_error.call_args.args),
        )
        self.assertIn('401', ' '.join(str(arg) for arg in log_error.call_args.args))
        self.assertEqual(
            Subscription.objects.get(reference='procac-rejected').status,
            Subscription.Status.FAILED,
        )

    def test_initialize_requires_authentication(self):
        self.client.logout()

        response = self.client.post(
            '/api/payments/initialize/',
            data=json.dumps({'plan': 'premium'}),
            content_type='application/json',
        )

        self.assertEqual(response.status_code, 401)
        self.assertEqual(response.json()['error'], 'Please sign in to start a subscription.')
        self.assertEqual(Subscription.objects.count(), 0)

    def test_initialize_accepts_csrf_cookie_header_from_landing_page(self):
        client = Client(enforce_csrf_checks=True)
        client.force_login(self.user)
        client.get('/')
        csrf_token = client.cookies['csrftoken'].value

        provider_response = MagicMock()
        provider_response.__enter__.return_value.read.return_value = json.dumps({
            'status': True,
            'data': {
                'authorization_url': 'https://checkout.paystack.com/csrf-test',
                'access_code': 'access-csrf-test',
                'reference': 'procac-csrf-test',
            },
        }).encode()
        with (
            override_settings(PAYSTACK_SECRET_KEY='sk_test_example'),
            patch('frontend.views.secrets.token_urlsafe', return_value='csrf-test'),
            patch('frontend.views.urllib.request.urlopen', return_value=provider_response),
        ):
            response = client.post(
                '/api/payments/initialize/',
                data=json.dumps({'plan': 'starter'}),
                content_type='application/json',
                HTTP_X_CSRFTOKEN=csrf_token,
            )

        self.assertEqual(response.status_code, 201)
        self.assertEqual(response.json()['reference'], 'procac-csrf-test')

    def test_initialize_rejects_missing_csrf_header(self):
        client = Client(enforce_csrf_checks=True)
        client.force_login(self.user)

        response = client.post(
            '/api/payments/initialize/',
            data=json.dumps({'plan': 'starter'}),
            content_type='application/json',
        )

        self.assertEqual(response.status_code, 403)
        self.assertEqual(Subscription.objects.count(), 0)

    def test_pricing_buttons_load_payment_handler_for_each_plan(self):
        response = self.client.get('/')

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'assets/js/payments.js')
        for plan in ('starter', 'standard', 'enterprise', 'ultimate_enterprise'):
            with self.subTest(plan=plan):
                self.assertContains(response, f'data-subscribe-plan="{plan}"')

    def test_authenticated_plans_page_displays_checkout_tiers(self):
        response = self.client.get('/plans/')

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'assets/js/payments.js')
        for plan in ('starter', 'standard', 'enterprise', 'ultimate_enterprise'):
            with self.subTest(plan=plan):
                self.assertContains(response, f'data-subscribe-plan="{plan}"')
        self.assertContains(response, '₦500')
        self.assertContains(response, '₦3,000')
        self.assertContains(response, '₦10,000')
        self.assertContains(response, '₦35,000')
        self.assertContains(response, 'per 2 months')
        self.assertContains(response, 'id="payment-error"')
        self.assertContains(response, 'Up to 25 client profiles')
        self.assertContains(response, '5 Business')
        rendered_html = response.content.decode()
        self.assertRegex(rendered_html, r'Unlimited\s+client profiles')
        self.assertRegex(rendered_html, r'NIN document\s+OCR auto-extract')

    def test_plans_page_displays_active_expiry_and_profile_quota(self):
        ConsultantProfile.objects.create(
            user=self.user,
            accreditation_number='NBA/ACC/PLANS/001',
            plan='standard',
        )
        subscription = Subscription.objects.create(
            user=self.user,
            plan='standard',
            amount=300_000,
            reference='plans-standard-active',
            status=Subscription.Status.SUCCESSFUL,
            expires_at=timezone.now() + relativedelta(days=7),
        )
        ClientProfile.objects.create(
            user=self.user,
            entity_name='Plans page client',
            entity_type='BN',
            email='plans-client@example.com',
        )
        self.client.force_login(self.user)

        response = self.client.get('/plans/')

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context['active_subscription'], subscription)
        self.assertEqual(response.context['clients_used'], 1)
        self.assertContains(response, 'Standard Plan · Active')
        self.assertContains(response, '1 / 15 client profiles utilized')
        self.assertContains(response, 'Expires')

    def test_platinum_plan_has_unlimited_quota_on_subscription_banner(self):
        ConsultantProfile.objects.create(
            user=self.user,
            accreditation_number='NBA/ACC/PLANS/PLATINUM',
            plan='ultimate_enterprise',
        )
        Subscription.objects.create(
            user=self.user,
            plan='ultimate_enterprise',
            amount=3_500_000,
            reference='plans-platinum-active',
            status=Subscription.Status.SUCCESSFUL,
            expires_at=timezone.now() + relativedelta(months=2),
        )
        self.client.force_login(self.user)

        response = self.client.get('/plans/')

        self.assertEqual(response.context['total_plan_limit'], None)
        self.assertContains(response, 'Platinum Plan · Active')
        self.assertContains(response, 'Unlimited quota')

    @staticmethod
    def _signed_webhook(payload, secret='webhook-test-secret'):
        body = json.dumps(payload).encode('utf-8')
        signature = hmac.new(secret.encode(), body, hashlib.sha512).hexdigest()
        return body, signature

    @override_settings(PAYSTACK_SECRET_KEY='webhook-test-secret')
    def test_webhook_rejects_invalid_signature(self):
        response = self.client.post(
            '/api/payments/paystack-webhook/',
            data=b'{"event":"charge.success"}',
            content_type='application/json',
            HTTP_X_PAYSTACK_SIGNATURE='invalid',
        )

        self.assertEqual(response.status_code, 400)

    def test_paystack_callback_verifies_payment_and_activates_profile_tier(self):
        profile = ConsultantProfile.objects.create(
            user=self.user,
            accreditation_number='NBA/ACC/CALLBACK/001',
            plan='starter',
        )
        subscription = Subscription.objects.create(
            user=self.user,
            plan='enterprise',
            amount=1_000_000,
            reference='paystack-callback-success',
        )
        provider_response = MagicMock()
        provider_response.__enter__.return_value.read.return_value = json.dumps({
            'status': True,
            'data': {
                'status': 'success',
                'reference': subscription.reference,
                'amount': subscription.amount,
                'currency': subscription.currency,
            },
        }).encode()

        with (
            override_settings(PAYSTACK_SECRET_KEY='sk_test_example'),
            patch('frontend.views.urllib.request.urlopen', return_value=provider_response),
        ):
            response = self.client.get(
                '/payments/callback/',
                {'reference': subscription.reference},
            )

        subscription.refresh_from_db()
        profile.refresh_from_db()
        self.assertRedirects(response, '/dashboard/', fetch_redirect_response=False)
        self.assertEqual(subscription.status, Subscription.Status.SUCCESSFUL)
        self.assertEqual(profile.plan, 'enterprise')

    def test_paystack_callback_does_not_activate_mismatched_payment(self):
        profile = ConsultantProfile.objects.create(
            user=self.user,
            accreditation_number='NBA/ACC/CALLBACK/002',
            plan='starter',
        )
        subscription = Subscription.objects.create(
            user=self.user,
            plan='enterprise',
            amount=1_000_000,
            reference='paystack-callback-mismatch',
        )
        provider_response = MagicMock()
        provider_response.__enter__.return_value.read.return_value = json.dumps({
            'status': True,
            'data': {
                'status': 'success',
                'reference': subscription.reference,
                'amount': subscription.amount + 1,
                'currency': subscription.currency,
            },
        }).encode()

        with (
            override_settings(PAYSTACK_SECRET_KEY='sk_test_example'),
            patch('frontend.views.urllib.request.urlopen', return_value=provider_response),
        ):
            response = self.client.get(
                '/payments/callback/',
                {'reference': subscription.reference},
            )

        subscription.refresh_from_db()
        profile.refresh_from_db()
        self.assertRedirects(response, '/plans/', fetch_redirect_response=False)
        self.assertEqual(subscription.status, Subscription.Status.PENDING)
        self.assertEqual(profile.plan, 'starter')

    @override_settings(PAYSTACK_SECRET_KEY='webhook-test-secret')
    def test_signed_success_webhook_marks_subscription_paid_idempotently(self):
        profile = ConsultantProfile.objects.create(
            user=self.user,
            accreditation_number='NBA/ACC/WEBHOOK/001',
            plan='starter',
        )
        subscription = Subscription.objects.create(
            user=self.user,
            plan='enterprise',
            amount=1_000_000,
            reference='paystack-success',
        )
        body, signature = self._signed_webhook({
            'event': 'charge.success',
            'data': {
                'reference': subscription.reference,
                'amount': subscription.amount,
                'currency': 'NGN',
            },
        })

        first_response = self.client.post(
            '/api/payments/paystack-webhook/',
            data=body,
            content_type='application/json',
            HTTP_X_PAYSTACK_SIGNATURE=signature,
        )
        first_paid_at = Subscription.objects.get(pk=subscription.pk).paid_at
        second_response = self.client.post(
            '/api/payments/paystack-webhook/',
            data=body,
            content_type='application/json',
            HTTP_X_PAYSTACK_SIGNATURE=signature,
        )

        subscription.refresh_from_db()
        profile.refresh_from_db()
        self.assertEqual(first_response.status_code, 200)
        self.assertEqual(second_response.status_code, 200)
        self.assertEqual(subscription.status, Subscription.Status.SUCCESSFUL)
        self.assertEqual(subscription.paid_at, first_paid_at)
        self.assertEqual(profile.plan, 'enterprise')
        self.assertIsNotNone(subscription.expires_at)

    @override_settings(PAYSTACK_SECRET_KEY='webhook-test-secret')
    def test_success_webhook_syncs_paystack_next_payment_date(self):
        subscription = Subscription.objects.create(
            user=self.user,
            plan='enterprise',
            amount=1_000_000,
            reference='paystack-next-payment-date',
        )
        body, signature = self._signed_webhook({
            'event': 'charge.success',
            'data': {
                'reference': subscription.reference,
                'amount': subscription.amount,
                'currency': 'NGN',
                'next_payment_date': '2027-02-28T12:30:00Z',
            },
        })

        response = self.client.post(
            '/api/payments/paystack-webhook/',
            data=body,
            content_type='application/json',
            HTTP_X_PAYSTACK_SIGNATURE=signature,
        )

        subscription.refresh_from_db()
        self.assertEqual(response.status_code, 200)
        self.assertEqual(subscription.expires_at.date(), date(2027, 2, 28))
        self.assertEqual(subscription.expires_at.hour, 12)
        self.assertEqual(subscription.expires_at.minute, 30)

    @override_settings(PAYSTACK_SECRET_KEY='webhook-test-secret')
    def test_success_webhook_rejects_mismatched_amount(self):
        subscription = Subscription.objects.create(
            user=self.user,
            plan='starter',
            amount=50_000,
            reference='paystack-mismatch',
        )
        body, signature = self._signed_webhook({
            'event': 'charge.success',
            'data': {
                'reference': subscription.reference,
                'amount': 50_001,
                'currency': 'NGN',
            },
        })

        response = self.client.post(
            '/api/payments/paystack-webhook/',
            data=body,
            content_type='application/json',
            HTTP_X_PAYSTACK_SIGNATURE=signature,
        )

        subscription.refresh_from_db()
        self.assertEqual(response.status_code, 400)
        self.assertEqual(subscription.status, Subscription.Status.PENDING)

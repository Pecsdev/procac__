import base64
import binascii
import hashlib
import hmac
import json
import logging
import re
import secrets
import urllib.error
import urllib.request
from datetime import datetime, time, timedelta
from urllib.parse import quote, urlsplit

from django.conf import settings
from django.contrib import messages
from django.contrib.auth import authenticate, login, logout
from django.contrib.auth.decorators import login_required
from django.contrib.auth.models import User
from django.core.exceptions import PermissionDenied
from django.core.mail import send_mail
from django.db import transaction
from django.db.models import Q
from django.forms import HiddenInput
from django.http import HttpResponseBadRequest, HttpResponseRedirect, JsonResponse
from django.middleware.csrf import get_token
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import Resolver404, resolve, reverse
from django.utils.http import url_has_allowed_host_and_scheme
from django.utils import timezone
from django.utils.dateparse import parse_date, parse_datetime
from django.views.decorators.csrf import csrf_exempt, csrf_protect
from django.views.decorators.http import require_GET, require_http_methods, require_POST

from .business_activities import BUSINESS_ACTIVITY_MAP
from .forms import ClientProfileForm, ConsultantProfileForm, ConsultantSignupForm
from .locations import STATE_LGA_MAP
from .models import (
    ClientIntakeLink,
    ClientProfile,
    ConsultantProfile,
    InjectionAuditLog,
    Subscription,
)
from .utils import calculate_subscription_expiry

logger = logging.getLogger(__name__)

PLAN_AMOUNTS_KOBO = {
    'starter': 500 * 100,
    'standard': 3_000 * 100,
    'premium': 10_000 * 100,
    'enterprise': 10_000 * 100,
    'ultimate_enterprise': 35_000 * 100,
}
PAYSTACK_INITIALIZE_URL = 'https://api.paystack.co/transaction/initialize'
PAYSTACK_VERIFY_URL = 'https://api.paystack.co/transaction/verify/'
PAYSTACK_USER_AGENT = (
    'Mozilla/5.0 (Windows NT 10.0; Win64; x64) '
    'AppleWebKit/537.36 (KHTML, like Gecko) '
    'Chrome/120.0.0.0 Safari/537.36'
)
PENDING_SIGNUP_SESSION_KEY = 'pending_user_data'
OTP_MAX_AGE_SECONDS = 10 * 60
OTP_MAX_ATTEMPTS = 5
OTP_RESEND_COOLDOWN_SECONDS = 60
OTP_MAX_RESENDS = 5


def home(request):
    return render(request, 'frontend/index.html')


def login_view(request):
    next_url = request.POST.get('next') or request.GET.get('next', '')
    if request.method == 'POST':
        email = request.POST.get('email', '').strip()
        password = request.POST.get('password', '')
        try:
            user = User.objects.get(email__iexact=email)
        except User.DoesNotExist:
            user = None

        authenticated_user = (
            authenticate(request, username=user.username, password=password)
            if user is not None
            else None
        )
        if authenticated_user is not None:
            login(request, authenticated_user)
            if not request.POST.get('remember'):
                request.session.set_expiry(0)
            if url_has_allowed_host_and_scheme(
                next_url,
                allowed_hosts={request.get_host()},
                require_https=request.is_secure(),
            ):
                return redirect(next_url)
            return redirect('dashboard')
        messages.error(request, 'Email or password is incorrect.')

    return render(request, 'frontend/login.html', {'next': next_url})


def signup(request):
    if request.user.is_authenticated:
        logout(request)

    if request.method == 'POST' and request.content_type == 'application/json':
        try:
            data = json.loads(request.body)
        except (json.JSONDecodeError, UnicodeDecodeError):
            return JsonResponse({'error': 'Request body must be valid JSON.'}, status=400)
        if not isinstance(data, dict):
            return JsonResponse({'error': 'Signup details must be a JSON object.'}, status=400)
        form = ConsultantSignupForm(data)
        if not form.is_valid():
            return JsonResponse(
                {'errors': form.errors.get_json_data()},
                status=400,
            )
        return _begin_signup_verification(request, form, json_response=True)

    form = ConsultantSignupForm(request.POST or None)
    if request.method == 'POST' and form.is_valid():
        return _begin_signup_verification(request, form)

    return render(request, 'frontend/signup.html', {'form': form})


def _otp_digest(code):
    return hmac.new(
        settings.SECRET_KEY.encode(),
        code.encode(),
        hashlib.sha256,
    ).hexdigest()


def _send_signup_otp(email, code):
    send_mail(
        subject='Your ProCAC verification code',
        message=(
            f'Your ProCAC email verification code is {code}. '
            f'It expires in {OTP_MAX_AGE_SECONDS // 60} minutes.'
        ),
        from_email=settings.DEFAULT_FROM_EMAIL,
        recipient_list=[email],
        fail_silently=False,
    )


def _begin_signup_verification(request, form, json_response=False):
    user = form.save(commit=False)
    code = f'{secrets.randbelow(1_000_000):06d}'
    try:
        _send_signup_otp(form.cleaned_data['email'], code)
    except Exception:
        logger.exception('Could not send consultant signup verification email.')
        if json_response:
            return JsonResponse({'error': 'Unable to send a verification email. Please try again.'}, status=503)
        messages.error(request, 'Unable to send a verification email. Please try again.')
        return render(request, 'frontend/signup.html', {'form': form}, status=503)

    request.session.cycle_key()
    request.session[PENDING_SIGNUP_SESSION_KEY] = {
        'email': user.email,
        'full_name': user.first_name,
        'accreditation_no': form.cleaned_data['accreditation_number'],
        'phone_number': form.cleaned_data['phone_number'],
        'firm_name': form.cleaned_data['firm_name'],
        'password': user.password,
        'otp_digest': _otp_digest(code),
        'created_at': timezone.now().timestamp(),
        'attempts': 0,
        'resends': 0,
        'resend_available_at': timezone.now().timestamp() + OTP_RESEND_COOLDOWN_SECONDS,
    }
    request.session.set_expiry(OTP_MAX_AGE_SECONDS)
    if json_response:
        return JsonResponse(
            {'verification_required': True, 'verify_url': reverse('verify_otp')},
            status=202,
        )
    return redirect('verify_otp')


def verify_otp(request):
    pending_data = request.session.get('pending_user_data')
    if not pending_data:
        messages.info(request, 'Start signup to receive a verification code.')
        return redirect('signup')

    now = timezone.now().timestamp()
    if now - pending_data.get('created_at', 0) > OTP_MAX_AGE_SECONDS:
        request.session.pop(PENDING_SIGNUP_SESSION_KEY, None)
        messages.error(request, 'Your verification code expired. Please sign up again.')
        return redirect('signup')

    if request.method == 'POST' and request.POST.get('action') == 'resend':
        if pending_data.get('resends', 0) >= OTP_MAX_RESENDS:
            messages.error(request, 'You have reached the maximum number of resend attempts.')
        elif now < pending_data.get('resend_available_at', 0):
            messages.error(request, 'Please wait before requesting another code.')
        else:
            code = f'{secrets.randbelow(1_000_000):06d}'
            try:
                _send_signup_otp(pending_data['email'], code)
            except Exception:
                logger.exception('Could not resend consultant signup verification email.')
                messages.error(request, 'Unable to resend the code. Please try again.')
            else:
                pending_data.update({
                    'otp_digest': _otp_digest(code),
                    'created_at': now,
                    'attempts': 0,
                    'resends': pending_data.get('resends', 0) + 1,
                    'resend_available_at': now + OTP_RESEND_COOLDOWN_SECONDS,
                })
                request.session[PENDING_SIGNUP_SESSION_KEY] = pending_data
                request.session.set_expiry(OTP_MAX_AGE_SECONDS)
                messages.success(request, 'A new verification code has been sent.')
        return redirect('verify_otp')

    if request.method == 'POST':
        code = request.POST.get('otp', '').strip()
        if not re.fullmatch(r'\d{6}', code) or not hmac.compare_digest(
            _otp_digest(code), pending_data.get('otp_digest', '')
        ):
            pending_data['attempts'] = pending_data.get('attempts', 0) + 1
            if pending_data['attempts'] >= OTP_MAX_ATTEMPTS:
                request.session.pop(PENDING_SIGNUP_SESSION_KEY, None)
                messages.error(request, 'Too many incorrect codes. Please sign up again.')
                return redirect('signup')
            request.session[PENDING_SIGNUP_SESSION_KEY] = pending_data
            messages.error(request, 'That verification code is incorrect. Please try again.')
            return redirect('verify_otp')

        try:
            with transaction.atomic():
                if User.objects.filter(email__iexact=pending_data['email']).exists():
                    raise ValueError('An account with this email already exists.')
                if ConsultantProfile.objects.filter(
                    accreditation_number__iexact=pending_data.get('accreditation_no', '')
                ).exists():
                    raise ValueError('This accreditation number is already registered.')
                user = User.objects.create_user(
                    username=pending_data['email'],
                    email=pending_data['email'],
                    password=None,
                    first_name=pending_data.get('full_name', ''),
                )
                user.password = pending_data['password']
                user.save()
                ConsultantProfile.objects.create(
                    user=user,
                    accreditation_number=pending_data.get('accreditation_no', ''),
                    phone_number=pending_data.get('phone_number', ''),
                    firm_name=pending_data.get('firm_name', ''),
                )
        except ValueError as error:
            request.session.pop(PENDING_SIGNUP_SESSION_KEY, None)
            messages.error(request, str(error))
            return redirect('signup')

        request.session.pop(PENDING_SIGNUP_SESSION_KEY, None)
        login(request, user)
        return redirect('plans')

    return render(request, 'frontend/authenticate.html', {'email': pending_data['email']})


@login_required
def plans(request):
    active_subscription = _active_subscription_for_user(request.user)
    plan = _active_plan_for_user(request.user)
    clients_used = request.user.client_profiles.count() + ClientIntakeLink.objects.filter(
        consultant=request.user,
        is_used=False,
        expires_at__gt=timezone.now(),
    ).count()
    consultant_profile = ConsultantProfile.objects.filter(user=request.user).first()
    profile_limit = (
        consultant_profile.profile_limit_for_plan(plan)
        if consultant_profile
        else ConsultantProfile.PLAN_PROFILE_LIMITS.get(plan)
    )
    return render(
        request,
        'frontend/plans.html',
        {
            'active_subscription': active_subscription,
            'active_plan': plan,
            'active_plan_label': (
                'Platinum'
                if plan == 'ultimate_enterprise'
                else dict(ConsultantProfile.PLAN_CHOICES).get(
                    plan,
                    plan.replace('_', ' ').title(),
                )
            ),
            'clients_used': clients_used,
            'profile_limit': profile_limit,
            'profile_usage_percent': (
                min(round(clients_used * 100 / profile_limit), 100)
                if profile_limit
                else None
            ),
            'total_plan_limit': profile_limit,
        },
    )


def _active_plan_for_user(user):
    subscription = _active_subscription_for_user(user)
    if subscription:
        return subscription.plan
    if user.subscriptions.filter(status=Subscription.Status.SUCCESSFUL).exists():
        return 'starter'
    profile = ConsultantProfile.objects.filter(user=user).first()
    return profile.plan if profile else 'starter'


def _active_subscription_for_user(user):
    return user.subscriptions.filter(
        status=Subscription.Status.SUCCESSFUL,
    ).filter(
        Q(expires_at__isnull=True) | Q(expires_at__gt=timezone.now()),
    ).first()


def _can_user_add_client(
    user,
    registration_type,
    exclude_client_id=None,
    exclude_intake_link_id=None,
):
    subscription = _active_subscription_for_user(user)
    profile = ConsultantProfile.objects.filter(user=user).first()
    if profile is None:
        if subscription is not None:
            can_add, error = subscription.can_add_client(
                registration_type,
                exclude_client_id=exclude_client_id,
            )
        elif user.subscriptions.filter(status=Subscription.Status.SUCCESSFUL).exists():
            return False, 'Your subscription has expired. Upgrade or renew your plan to add clients.'
        else:
            starter_limit = ConsultantProfile.PLAN_PROFILE_LIMITS['starter']
            clients = user.client_profiles.all()
            if exclude_client_id is not None:
                clients = clients.exclude(pk=exclude_client_id)
            can_add = clients.count() < starter_limit
            error = (
                ''
                if can_add
                else 'Your plan profile limit is reached. Upgrade your plan to add more clients.'
            )
    elif subscription is not None:
        can_add, error = subscription.can_add_client(
            registration_type,
            exclude_client_id=exclude_client_id,
        )
    elif user.subscriptions.filter(status=Subscription.Status.SUCCESSFUL).exists():
        return False, 'Your subscription has expired. Upgrade or renew your plan to add clients.'
    else:
        can_add, error = profile.can_add_client(
            registration_type,
            exclude_client_id=exclude_client_id,
        )

    if not can_add:
        return can_add, error

    clients = ClientProfile.objects.filter(user=user)
    if exclude_client_id is not None:
        clients = clients.exclude(pk=exclude_client_id)
    pending_links = ClientIntakeLink.objects.filter(
        consultant=user,
        is_used=False,
        expires_at__gt=timezone.now(),
    )
    if exclude_intake_link_id is not None:
        pending_links = pending_links.exclude(pk=exclude_intake_link_id)

    plan = _active_plan_for_user(user)
    total_limit = (
        profile.profile_limit_for_plan(plan)
        if profile
        else ConsultantProfile.PLAN_PROFILE_LIMITS.get(plan)
    )
    if total_limit is not None and clients.count() + pending_links.count() >= total_limit:
        return False, 'Your plan profile limit is reached. Upgrade your plan to add more clients.'

    category_limit = ConsultantProfile.PLAN_ENTITY_PROFILE_LIMITS.get(plan, {}).get(
        registration_type,
    )
    if (
        category_limit is not None
        and clients.filter(entity_type=registration_type).count()
        + pending_links.filter(filing_type=registration_type).count()
        >= category_limit
    ):
        category_label = dict(ClientProfile.ENTITY_TYPES)[registration_type]
        return False, f'Your {category_label} allocation is full. Upgrade your plan to add more clients.'

    return True, ''


@login_required
def agency_profile_view(request):
    profile = ConsultantProfile.objects.filter(user=request.user).first()
    token_revealed = ''
    if request.method == 'POST' and request.POST.get('action') == 'regenerate_token':
        if profile is None:
            messages.error(request, 'Save your agency credentials before creating an extension key.')
            return redirect('agency_profile')
        token_revealed = secrets.token_urlsafe(32)
        profile.extension_token_hash = hashlib.sha256(
            token_revealed.encode(),
        ).hexdigest()
        profile.save(update_fields=['extension_token_hash'])
        messages.success(
            request,
            'A new extension key was created. Copy it now; it will only be shown once.',
        )
        form = ConsultantProfileForm(instance=profile, user=request.user)
    else:
        form = ConsultantProfileForm(
            request.POST or None,
            request.FILES or None,
            instance=profile,
            user=request.user,
        )
    if request.method == 'POST' and request.POST.get('action') != 'regenerate_token':
        if form.is_valid():
            form.save()
            messages.success(
                request,
                'Agency profile and profile picture updated; extension settings synced.',
            )
            return redirect('agency_profile')
        messages.error(request, 'Please correct the errors below.')

    active_subscription = _active_subscription_for_user(request.user)
    plan_labels = dict(ConsultantProfile.PLAN_CHOICES)
    active_plan = (
        plan_labels.get(active_subscription.plan, active_subscription.plan.title())
        if active_subscription
        else None
    )
    recent_payments = [
        {
            'reference': payment.reference,
            'plan': plan_labels.get(payment.plan, payment.plan.title()),
            'amount_naira': payment.amount / 100,
            'currency': payment.currency,
            'status': payment.get_status_display(),
            'date': payment.paid_at or payment.created_at,
        }
        for payment in request.user.subscriptions.order_by('-created_at')[:10]
    ]
    return render(
        request,
        'frontend/agency_profile.html',
        {
            'form': form,
            'active_plan': active_plan,
            'plan_active': active_subscription is not None,
            'extension_key_active': profile.extension_key_active if profile else False,
            'extension_version': '1.2.0',
            'token_revealed': token_revealed,
            'recent_payments': recent_payments,
        },
    )


@login_required
@require_GET
def paystack_callback(request):
    reference = request.GET.get('reference') or request.GET.get('trxref', '')
    subscription = Subscription.objects.filter(
        reference=reference,
        user=request.user,
    ).first()
    if subscription is None:
        messages.error(request, 'We could not find that checkout. Please choose a plan and try again.')
        return redirect('plans')
    if not settings.PAYSTACK_SECRET_KEY:
        messages.error(request, 'Payment verification is not configured. Please contact support.')
        return redirect('plans')

    provider_request = urllib.request.Request(
        f'{PAYSTACK_VERIFY_URL}{quote(reference, safe="")}',
        headers={
            'Authorization': f'Bearer {settings.PAYSTACK_SECRET_KEY}',
            'Accept': 'application/json',
            'User-Agent': PAYSTACK_USER_AGENT,
        },
        method='GET',
    )
    try:
        with urllib.request.urlopen(provider_request, timeout=15) as response:
            provider_response = json.loads(response.read().decode('utf-8'))
    except (
        urllib.error.HTTPError,
        urllib.error.URLError,
        TimeoutError,
        json.JSONDecodeError,
        UnicodeDecodeError,
    ) as error:
        logger.warning('Paystack callback verification failed for %s: %s', reference, error)
        messages.error(request, 'We could not verify your payment yet. Please check your plans and try again.')
        return redirect('plans')

    data = provider_response.get('data') if isinstance(provider_response, dict) else None
    if (
        not isinstance(provider_response, dict)
        or provider_response.get('status') is not True
        or not isinstance(data, dict)
        or data.get('status') != 'success'
        or data.get('reference') != subscription.reference
        or type(data.get('amount')) is not int
        or data['amount'] != subscription.amount
        or data.get('currency') != subscription.currency
    ):
        messages.error(request, 'Payment is not confirmed yet. Please choose a plan or contact support.')
        return redirect('plans')

    with transaction.atomic():
        subscription = Subscription.objects.select_for_update().get(pk=subscription.pk)
        _activate_subscription(subscription, _paystack_expiry(data))
    plan_name = dict(ConsultantProfile.PLAN_CHOICES).get(subscription.plan, subscription.plan.title())
    messages.success(request, f'{plan_name} plan activated successfully.')
    return redirect('dashboard')


def _activate_subscription(subscription, expires_at=None):
    if subscription.status != Subscription.Status.SUCCESSFUL:
        subscription.status = Subscription.Status.SUCCESSFUL
    if subscription.paid_at is None:
        subscription.paid_at = timezone.now()
    if expires_at is not None:
        subscription.expires_at = expires_at
    elif subscription.expires_at is None:
        subscription.expires_at = calculate_subscription_expiry(
            subscription.paid_at or timezone.now(),
            subscription.plan,
        )
    subscription.save(update_fields=['status', 'paid_at', 'expires_at', 'updated_at'])
    ConsultantProfile.objects.filter(user_id=subscription.user_id).update(plan=subscription.plan)


def _paystack_expiry(data):
    candidates = [data.get('expires_at'), data.get('next_payment_date')]
    nested_subscription = data.get('subscription')
    if isinstance(nested_subscription, dict):
        candidates.extend((
            nested_subscription.get('expires_at'),
            nested_subscription.get('next_payment_date'),
        ))
    for candidate in candidates:
        if not isinstance(candidate, str):
            continue
        parsed = parse_datetime(candidate)
        if parsed is None:
            parsed_date = parse_date(candidate)
            if parsed_date is not None:
                parsed = datetime.combine(parsed_date, time.min)
        if parsed is not None:
            if timezone.is_naive(parsed):
                parsed = timezone.make_aware(parsed, timezone.get_current_timezone())
            return parsed
    return None


def _paystack_expiry(data):
    candidates = [data.get('expires_at'), data.get('next_payment_date')]
    nested_subscription = data.get('subscription')
    if isinstance(nested_subscription, dict):
        candidates.extend((
            nested_subscription.get('expires_at'),
            nested_subscription.get('next_payment_date'),
        ))
    for candidate in candidates:
        if not isinstance(candidate, str):
            continue
        parsed = parse_datetime(candidate)
        if parsed is None:
            parsed_date = parse_date(candidate)
            if parsed_date is not None:
                parsed = datetime.combine(parsed_date, time.min)
        if parsed is not None:
            if timezone.is_naive(parsed):
                parsed = timezone.make_aware(parsed, timezone.get_current_timezone())
            return parsed
    return None


@require_POST
def logout_view(request):
    logout(request)
    return redirect('login')


@login_required
def dashboard(request):
    if request.method == 'POST':
        form = ClientProfileForm(request.POST)
        if form.is_valid():
            with transaction.atomic():
                User.objects.select_for_update().get(pk=request.user.pk)
                entity_type = form.cleaned_data['entity_type']
                can_add, allocation_error = _can_user_add_client(request.user, entity_type)
                if can_add:
                    client_profile = form.save(commit=False)
                    client_profile.user = request.user
                    client_profile.save()
            if not can_add:
                messages.error(request, allocation_error)
                return redirect('plans')
            messages.success(request, 'Client profile saved and ready for the extension.')
            return redirect('dashboard')
    else:
        form = ClientProfileForm()

    clients = ClientProfile.objects.filter(user=request.user)
    pending_intake_links = ClientIntakeLink.objects.filter(
        consultant=request.user,
        is_used=False,
        expires_at__gt=timezone.now(),
    )
    total_clients = clients.count()
    pending_intake_count = pending_intake_links.count()
    allocated_profile_count = total_clients + pending_intake_count
    ready_for_fill = clients.filter(status=ClientProfile.Status.READY).count()
    registered_clients = clients.filter(status=ClientProfile.Status.COMPLETED).count()

    plan = _active_plan_for_user(request.user)
    consultant_profile = ConsultantProfile.objects.filter(user=request.user).first()
    profile_limit = (
        consultant_profile.profile_limit_for_plan(plan)
        if consultant_profile
        else ConsultantProfile.PLAN_PROFILE_LIMITS.get(plan)
    )
    active_plan = dict(ConsultantProfile.PLAN_CHOICES).get(plan, 'Starter')
    return render(
        request,
        'frontend/dashboard.html',
        {
            'payment_required': request.GET.get('payment') == 'required',
            'payment_error': request.GET.get('payment_error', ''),
            'active_plan': active_plan,
            'client_profiles': clients,
            'pending_intake_links': pending_intake_links,
            'client_record_count': total_clients + pending_intake_links.count(),
            'allocated_profile_count': allocated_profile_count,
            'client_profile_form': form,
            'total_clients': total_clients,
            'ready_for_fill': ready_for_fill,
            'registered_clients': registered_clients,
            'profile_limit': profile_limit,
            'profile_usage_percent': (
                min(round(allocated_profile_count * 100 / profile_limit), 100)
                if profile_limit
                else None
            ),
            'profile_usage': (
                f'{allocated_profile_count} / {profile_limit} profiles used'
                if profile_limit is not None
                else f'{allocated_profile_count} / Unlimited profiles used'
            ),
            'entity_profile_limits': ConsultantProfile.PLAN_ENTITY_PROFILE_LIMITS.get(
                plan,
                {},
            ),
            'entity_profile_capacities': {
                entity_type: ConsultantProfile.PLAN_ENTITY_PROFILE_LIMITS.get(plan, {}).get(entity_type)
                for entity_type in ('BN', 'LTD', 'IT')
            },
            'business_name_count': clients.filter(entity_type='BN').count(),
            'limited_company_count': clients.filter(entity_type='LTD').count(),
            'incorporated_trustee_count': clients.filter(entity_type='IT').count(),
        },
    )


@login_required
@require_POST
def generate_intake_link(request):
    filing_type = request.POST.get('filing_type', '').strip()
    if filing_type not in dict(ClientIntakeLink.FILING_TYPES):
        return JsonResponse({'error': 'Choose a valid filing type.'}, status=400)

    client_name_hint = request.POST.get('client_name_hint', '').strip()
    if len(client_name_hint) > 255:
        return JsonResponse({'error': 'The client reference must be 255 characters or fewer.'}, status=400)

    with transaction.atomic():
        User.objects.select_for_update().get(pk=request.user.pk)
        if not ConsultantProfile.objects.filter(user=request.user).exists():
            return JsonResponse(
                {'error': 'A consultant profile is required to generate intake links.'},
                status=403,
            )

        can_add, allocation_error = _can_user_add_client(request.user, filing_type)
        if not can_add:
            return JsonResponse({'error': allocation_error}, status=403)

        intake_link = ClientIntakeLink.objects.create(
            consultant=request.user,
            filing_type=filing_type,
            client_name_hint=client_name_hint or None,
            expires_at=timezone.now() + timedelta(hours=10),
        )

    intake_url = request.build_absolute_uri(
        reverse('client_fill_view', kwargs={'token': intake_link.token}),
    )
    response = JsonResponse({
        'id': str(intake_link.pk),
        'url': intake_url,
        'filing_type': intake_link.filing_type,
        'filing_type_label': intake_link.get_filing_type_display(),
        'client_name_hint': intake_link.client_name_hint or '',
        'created_at': intake_link.created_at.isoformat(),
        'expires_at': intake_link.expires_at.isoformat(),
    })
    response['Cache-Control'] = 'private, no-store'
    return response


@login_required
@require_GET
def intake_link_status(request):
    links = ClientIntakeLink.objects.filter(
        consultant=request.user,
        expires_at__gt=timezone.now(),
    ).filter(
        Q(is_used=False) | Q(client_profile__isnull=False),
    ).select_related('client_profile')
    response = JsonResponse({
        'links': [
            {
                'id': str(link.pk),
                'is_used': link.is_used,
                'filing_type': link.filing_type,
                'filing_type_label': link.get_filing_type_display(),
                'client_name_hint': link.client_name_hint or '',
                'client': (
                    {
                        'entity_name': link.client_profile.entity_name,
                        'email': link.client_profile.email,
                        'entity_type': link.client_profile.entity_type,
                        'nin': link.client_profile.nin,
                        'created_at': link.client_profile.created_at.isoformat(),
                    }
                    if link.is_used
                    else None
                ),
            }
            for link in links
        ],
    })
    response['Cache-Control'] = 'private, no-store'
    return response


def _render_client_intake_page(
    request,
    state,
    *,
    form=None,
    stakeholder_data=None,
    status=200,
):
    response = render(
        request,
        'client_portal/fill_intake.html',
        {
            'state': state,
            'form': form,
            'stakeholder_data': stakeholder_data or {},
            'state_lga_data': STATE_LGA_MAP if state == 'form' else {},
            'business_activity_data': BUSINESS_ACTIVITY_MAP if state == 'form' else {},
        },
        status=status,
    )
    response['Cache-Control'] = 'private, no-store'
    return response


@require_http_methods(['GET', 'POST'])
def client_fill_view(request, token):
    intake_link = ClientIntakeLink.objects.filter(token=token).first()
    if intake_link is None or intake_link.is_used:
        return _render_client_intake_page(request, 'invalid', status=404)
    if intake_link.expires_at <= timezone.now():
        return _render_client_intake_page(request, 'expired', status=410)

    if request.method == 'GET':
        form = ClientProfileForm()
        form.fields['entity_type'].widget = HiddenInput()
        form.initial['entity_type'] = intake_link.filing_type
        _require_public_intake_fields(form)
        return _render_client_intake_page(request, 'form', form=form)

    submission_data = request.POST.copy()
    submission_data['entity_type'] = intake_link.filing_type
    stakeholder_data = {
        'full_name': request.POST.get('proprietor_name', '')[:255],
        'dob': request.POST.get('proprietor_dob', '')[:10],
        'gender': request.POST.get('proprietor_gender', '')[:20],
        'nationality': request.POST.get('proprietor_nationality', '')[:100],
        'identity_type': request.POST.get('identity_type', '')[:50],
        'identity_number': request.POST.get('identity_number', '')[:100],
        'residential_address': request.POST.get('proprietor_address', '')[:255],
    }
    submission_data['directors_json'] = json.dumps([
        stakeholder_data,
    ]) if any(stakeholder_data.values()) else '[]'
    form = ClientProfileForm(submission_data)
    form.fields['entity_type'].widget = HiddenInput()
    _require_public_intake_fields(form)
    form_is_valid = form.is_valid()
    if not stakeholder_data['full_name']:
        form.add_error(None, 'Enter the primary proprietor, director, or trustee name.')
    if stakeholder_data['gender'] not in ('', 'Male', 'Female'):
        form.add_error(None, 'Choose a valid gender.')
    if stakeholder_data['identity_type'] not in ('', 'NIN', 'Passport', 'Other'):
        form.add_error(None, 'Choose a valid identity type.')
    if stakeholder_data['dob'] and parse_date(stakeholder_data['dob']) is None:
        form.add_error(None, 'Enter a valid date of birth.')
    if not form_is_valid or form.non_field_errors():
        return _render_client_intake_page(
            request,
            'form',
            form=form,
            stakeholder_data=stakeholder_data,
            status=400,
        )

    with transaction.atomic():
        locked_link = (
            ClientIntakeLink.objects.select_for_update()
            .filter(token=token)
            .first()
        )
        if locked_link is None or locked_link.is_used:
            return _render_client_intake_page(request, 'invalid', status=404)
        if locked_link.expires_at <= timezone.now():
            return _render_client_intake_page(request, 'expired', status=410)

        User.objects.select_for_update().get(pk=locked_link.consultant_id)
        can_add, allocation_error = _can_user_add_client(
            locked_link.consultant,
            locked_link.filing_type,
            exclude_intake_link_id=locked_link.pk,
        )
        if not can_add:
            form.add_error(None, allocation_error)
            return _render_client_intake_page(
                request,
                'form',
                form=form,
                stakeholder_data=stakeholder_data,
                status=403,
            )

        link_claimed = ClientIntakeLink.objects.filter(
            pk=locked_link.pk,
            is_used=False,
            expires_at__gt=timezone.now(),
        ).update(is_used=True)
        if not link_claimed:
            return _render_client_intake_page(request, 'invalid', status=404)

        client_profile = form.save(commit=False)
        client_profile.user = locked_link.consultant
        client_profile.intake_link = locked_link
        client_profile.status = ClientProfile.Status.READY
        client_profile.save()

    return _render_client_intake_page(request, 'success')


def _require_public_intake_fields(form):
    for field_name in (
        'state',
        'lga',
        'principal_activity',
        'specific_activity',
    ):
        form.fields[field_name].required = True


@require_GET
def extension_status(request):
    user = _extension_authenticated_user(request)
    if user is None:
        response = JsonResponse({'authenticated': False}, status=401)
        response['Cache-Control'] = 'private, no-store'
        return response

    active_subscription = _active_subscription_for_user(user)
    profile = ConsultantProfile.objects.filter(user=user).first()
    response = JsonResponse({
        'authenticated': True,
        'user': user.get_full_name() or user.email,
        'csrf_token': get_token(request),
        'active_subscription_tier': (
            active_subscription.plan if active_subscription else None
        ),
        'presenter_defaults': {
            'state': profile.presenter_state if profile else '',
            'lga': profile.presenter_lga if profile else '',
            'phone': profile.presenter_phone if profile else '',
            'email': profile.presenter_email if profile else '',
        },
    })
    response['Cache-Control'] = 'private, no-store'
    return response


def _extension_authenticated_user(request):
    authorization = request.headers.get('Authorization', '')
    if authorization:
        scheme, _, token = authorization.partition(' ')
        if scheme.lower() != 'bearer' or not token.strip():
            return None
        token_hash = hashlib.sha256(token.strip().encode()).hexdigest()
        profile = ConsultantProfile.objects.select_related('user').filter(
            extension_token_hash=token_hash,
        ).first()
        return profile.user if profile and profile.user.is_active else None
    return request.user if request.user.is_authenticated else None


def _extension_unauthorized():
    response = JsonResponse(
        {'authenticated': False, 'clients': []},
        status=401,
    )
    response['Cache-Control'] = 'private, no-store'
    return response


@require_http_methods(['GET', 'POST'])
@csrf_exempt
def extension_clients(request):
    if request.headers.get('Authorization'):
        user = _extension_authenticated_user(request)
        if user is None:
            return _extension_unauthorized()
        return _extension_clients_for_user(request, user)
    return _extension_clients_session(request)


@require_POST
@csrf_exempt
def extension_injection_audit(request):
    if request.headers.get('Authorization'):
        user = _extension_authenticated_user(request)
        if user is None:
            return _extension_unauthorized()
        return _save_extension_injection_audit(request, user)
    return _extension_injection_audit_session(request)


@require_POST
@csrf_protect
def _extension_injection_audit_session(request):
    if not request.user.is_authenticated:
        return _extension_unauthorized()
    return _save_extension_injection_audit(request, request.user)


def _save_extension_injection_audit(request, user):
    try:
        payload = json.loads(request.body)
    except (json.JSONDecodeError, UnicodeDecodeError):
        return JsonResponse({'error': 'Request body must be valid JSON.'}, status=400)
    if not isinstance(payload, dict):
        return JsonResponse({'error': 'Audit details must be a JSON object.'}, status=400)

    client_id = payload.get('client_id')
    if isinstance(client_id, bool) or not isinstance(client_id, int):
        return JsonResponse({'error': 'A valid client profile is required.'}, status=400)
    client = ClientProfile.objects.filter(pk=client_id, user=user).first()
    if client is None:
        return JsonResponse({'error': 'Client profile not found.'}, status=404)

    status = payload.get('status')
    if status not in InjectionAuditLog.Status.values:
        return JsonResponse({'error': 'Choose a valid injection status.'}, status=400)
    fields_populated = payload.get('fields_populated')
    if (
        isinstance(fields_populated, bool)
        or not isinstance(fields_populated, int)
        or fields_populated < 0
        or fields_populated > 1000
    ):
        return JsonResponse({'error': 'Field count must be between 0 and 1000.'}, status=400)

    audit_log = InjectionAuditLog.objects.create(
        consultant=user,
        client_profile=client,
        status=status,
        fields_populated=fields_populated,
    )
    response = JsonResponse({'recorded': True, 'id': audit_log.pk}, status=201)
    response['Cache-Control'] = 'private, no-store'
    return response


@require_http_methods(['GET', 'POST'])
@csrf_protect
def _extension_clients_session(request):
    if not request.user.is_authenticated:
        return _extension_unauthorized()
    return _extension_clients_for_user(request, request.user)


def _extension_clients_for_user(request, user):
    if request.method == 'POST':
        try:
            payload = json.loads(request.body)
        except (json.JSONDecodeError, UnicodeDecodeError):
            return JsonResponse({'error': 'Request body must be valid JSON.'}, status=400)
        if not isinstance(payload, dict):
            return JsonResponse({'error': 'Client details must be a JSON object.'}, status=400)
        form = ClientProfileForm(payload)
        if not form.is_valid():
            return JsonResponse(
                {'error': 'Client details are invalid.', 'errors': form.errors.get_json_data()},
                status=400,
            )
        with transaction.atomic():
            User.objects.select_for_update().get(pk=user.pk)
            can_add, allocation_error = _can_user_add_client(
                user,
                form.cleaned_data['entity_type'],
            )
            if not can_add:
                return JsonResponse(
                    {'error': allocation_error, 'upgrade_url': reverse('plans')},
                    status=403,
                )
            client = form.save(commit=False)
            client.user = user
            client.save()
        return JsonResponse({
            'created': True,
            'client': {
                'id': client.pk,
                'entity_name': client.entity_name,
                'entity_type': client.entity_type,
            },
        }, status=201)

    clients = [
        {
            'id': client.pk,
            'entity_name': client.entity_name,
            'entity_type': client.entity_type,
            'nin': client.nin,
            'email': client.email,
            'proposed_name_1': client.proposed_name_1,
            'proposed_name_2': client.proposed_name_2,
            'classification': client.classification,
            'business_type': client.business_type,
            'principal_activity': client.principal_activity,
            'specific_activity': client.specific_activity,
            'principal_business_activity': client.principal_activity,
            'specific_business_activity': client.specific_activity,
            'location': {
                'state': client.state,
                'lga': client.lga,
            },
            'business_activities': {
                'principal': client.principal_activity,
                'specific': client.specific_activity,
            },
            'nature_category': client.nature_category,
            'specific_nature': client.specific_nature,
            'objectives': client.objectives,
            'street_address': client.street_address,
            'city': client.city,
            'lga': client.lga,
            'state': client.state,
            'phone': client.phone,
            'commencement_date': client.commencement_date,
            'directors': client.directors,
        }
        for client in user.client_profiles.exclude(
            status=ClientProfile.Status.DRAFT,
        )
    ]
    response = JsonResponse({'authenticated': True, 'clients': clients})
    response['Cache-Control'] = 'private, no-store'
    return response


@login_required
def intake(request):
    clients = ClientProfile.objects.filter(user=request.user)
    plan = _active_plan_for_user(request.user)
    if request.method == 'POST':
        draft_id = request.POST.get('draft_id')
        draft = (
            get_object_or_404(
                clients,
                pk=draft_id,
                status=ClientProfile.Status.DRAFT,
            )
            if draft_id
            else None
        )
        form = ClientProfileForm(request.POST, instance=draft)
        if request.POST.get('action') == 'draft':
            form.fields['email'].required = False

        if form.is_valid():
            with transaction.atomic():
                User.objects.select_for_update().get(pk=request.user.pk)
                entity_type = form.cleaned_data['entity_type']
                can_add, allocation_error = _can_user_add_client(
                    request.user,
                    entity_type,
                    exclude_client_id=draft.pk if draft else None,
                )
                if can_add:
                    client_profile = form.save(commit=False)
                    client_profile.user = request.user
                    if request.POST.get('action') == 'draft':
                        client_profile.status = ClientProfile.Status.DRAFT
                    else:
                        client_profile.status = ClientProfile.Status.READY
                    client_profile.save()
            if not can_add:
                messages.error(request, allocation_error)
                return redirect('plans')
            if client_profile.status == ClientProfile.Status.DRAFT:
                messages.success(request, 'Draft record saved to your client registry.')
                return redirect(f"{reverse('intake')}?draft={client_profile.pk}")
            else:
                messages.success(request, 'Client profile saved and ready for the extension.')
                return redirect('dashboard')
    else:
        draft_id = request.GET.get('draft')
        draft = (
            get_object_or_404(
                clients,
                pk=draft_id,
                status=ClientProfile.Status.DRAFT,
            )
            if draft_id
            else None
        )
        form = ClientProfileForm(instance=draft)
        if draft:
            form.initial['directors_json'] = json.dumps(draft.directors)

    return render(
        request,
        'frontend/intake.html',
        {
            'form': form,
            'business_name_count': clients.filter(entity_type='BN').count(),
            'limited_company_count': clients.filter(entity_type='LTD').count(),
            'incorporated_trustee_count': clients.filter(entity_type='IT').count(),
            'entity_profile_capacities': {
                entity_type: ConsultantProfile.PLAN_ENTITY_PROFILE_LIMITS.get(plan, {}).get(entity_type)
                for entity_type in ('BN', 'LTD', 'IT')
            },
        },
    )


@login_required
def admin_dashboard(request):
    if not request.user.is_staff:
        raise PermissionDenied
    return render(request, 'frontend/admin.html')


def encoded_page_link(request, token):
    try:
        padded_token = token + '=' * (-len(token) % 4)
        decoded_url = base64.urlsafe_b64decode(padded_token.encode('ascii')).decode('utf-8')
        parsed_url = urlsplit(decoded_url)
        if parsed_url.scheme or parsed_url.netloc or not parsed_url.path.startswith('/'):
            return HttpResponseBadRequest('Invalid encoded page link.')
        route = resolve(parsed_url.path)
    except (UnicodeDecodeError, ValueError, binascii.Error, Resolver404):
        return HttpResponseBadRequest('Invalid encoded page link.')

    if route.url_name not in {
        'home',
        'login',
        'signup',
        'dashboard',
        'agency_profile',
        'intake',
        'admin_dashboard',
        'logout',
    }:
        return HttpResponseBadRequest('Invalid encoded page link.')

    return HttpResponseRedirect(decoded_url)


@require_POST
def initialize_payment(request):
    if not request.user.is_authenticated:
        return JsonResponse({'error': 'Please sign in to start a subscription.'}, status=401)

    if not settings.PAYSTACK_SECRET_KEY:
        logger.error('Paystack payment initialization requested without a configured secret key.')
        return JsonResponse({'error': 'Payment service is not configured.'}, status=503)

    try:
        payload = json.loads(request.body)
    except (json.JSONDecodeError, UnicodeDecodeError):
        return JsonResponse({'error': 'Request body must be valid JSON.'}, status=400)

    plan = (
        payload.get('plan_tier', payload.get('plan'))
        if isinstance(payload, dict)
        else None
    )
    if not isinstance(plan, str) or plan not in PLAN_AMOUNTS_KOBO:
        return JsonResponse({'error': 'Choose a valid subscription plan.'}, status=400)
    if not request.user.email:
        return JsonResponse({'error': 'An email address is required to initialize payment.'}, status=400)

    reference = f'procac-{secrets.token_urlsafe(24)}'
    subscription = Subscription.objects.create(
        user=request.user,
        plan=plan,
        amount=PLAN_AMOUNTS_KOBO[plan],
        reference=reference,
    )
    callback_url = settings.PAYSTACK_CALLBACK_URL or request.build_absolute_uri(
        reverse('payment_callback')
    )
    paystack_payload = json.dumps({
        'email': request.user.email,
        'amount': subscription.amount,
        'currency': subscription.currency,
        'reference': subscription.reference,
        'callback_url': callback_url,
        'metadata': {
            'user_id': request.user.pk,
            'plan': subscription.plan,
        },
    }).encode('utf-8')
    provider_request = urllib.request.Request(
        PAYSTACK_INITIALIZE_URL,
        data=paystack_payload,
        headers={
            'Authorization': f'Bearer {settings.PAYSTACK_SECRET_KEY}',
            'Content-Type': 'application/json',
            'Accept': 'application/json',
            'User-Agent': PAYSTACK_USER_AGENT,
        },
        method='POST',
    )

    try:
        with urllib.request.urlopen(provider_request, timeout=15) as response:
            provider_response = json.loads(response.read().decode('utf-8'))
    except urllib.error.HTTPError as error:
        subscription.status = Subscription.Status.FAILED
        subscription.save(update_fields=['status', 'updated_at'])
        response_body = error.read().decode('utf-8', errors='replace')
        logger.error(
            'Paystack rejected initialization for subscription %s: HTTP %s %s; '
            'response body: %s',
            subscription.reference,
            error.code,
            error.reason,
            response_body,
        )
        return JsonResponse(
            {
                'error': (
                    'Paystack rejected the checkout request. Check that the secret key '
                    'is active for this environment, then try again.'
                ),
            },
            status=502,
        )
    except (
        urllib.error.URLError,
        TimeoutError,
        json.JSONDecodeError,
        UnicodeDecodeError,
    ) as error:
        subscription.status = Subscription.Status.FAILED
        subscription.save(update_fields=['status', 'updated_at'])
        logger.error(
            'Paystack initialization failed for subscription %s: %s',
            subscription.reference,
            error,
            exc_info=True,
        )
        return JsonResponse(
            {'error': 'Unable to reach Paystack checkout. Please try again.'},
            status=502,
        )

    data = provider_response.get('data') if isinstance(provider_response, dict) else None
    if (
        not isinstance(provider_response, dict)
        or provider_response.get('status') is not True
        or not isinstance(data, dict)
        or not data.get('authorization_url')
        or not data.get('access_code')
        or data.get('reference') != subscription.reference
    ):
        subscription.status = Subscription.Status.FAILED
        subscription.save(update_fields=['status', 'updated_at'])
        logger.error(
            'Paystack returned an unsuccessful or invalid initialization response '
            'for subscription %s: %r',
            reference,
            provider_response,
        )
        return JsonResponse({'error': 'Unable to initialize payment. Please try again.'}, status=502)

    subscription.authorization_url = data['authorization_url']
    subscription.access_code = data['access_code']
    subscription.save(update_fields=['authorization_url', 'access_code', 'updated_at'])

    return JsonResponse({
        'authorization_url': subscription.authorization_url,
        'access_code': subscription.access_code,
        'reference': subscription.reference,
    }, status=201)


@csrf_exempt
@require_POST
def paystack_webhook(request):
    webhook_secret = settings.PAYSTACK_SECRET_KEY
    if not webhook_secret:
        logger.error('Paystack webhook received without a configured signature secret.')
        return JsonResponse({'error': 'Webhook verification is not configured.'}, status=503)

    signature = request.headers.get('x-paystack-signature', '')
    expected_signature = hmac.new(
        webhook_secret.encode('utf-8'),
        request.body,
        hashlib.sha512,
    ).hexdigest()
    if not signature or not hmac.compare_digest(signature, expected_signature):
        return JsonResponse({'error': 'Invalid webhook signature.'}, status=400)

    try:
        event = json.loads(request.body)
    except (json.JSONDecodeError, UnicodeDecodeError):
        return JsonResponse({'error': 'Webhook body must be valid JSON.'}, status=400)

    if not isinstance(event, dict):
        return JsonResponse({'error': 'Webhook body must be a JSON object.'}, status=400)

    event_type = event.get('event')
    data = event.get('data')
    if not isinstance(event_type, str):
        return JsonResponse({'error': 'Webhook is missing an event type.'}, status=400)
    if event_type not in {'charge.success', 'charge.failed'}:
        return JsonResponse({'status': 'ignored'})
    if not isinstance(data, dict) or not isinstance(data.get('reference'), str):
        return JsonResponse({'error': 'Webhook is missing a payment reference.'}, status=400)

    with transaction.atomic():
        subscription = (
            Subscription.objects.select_for_update()
            .filter(reference=data['reference'])
            .first()
        )
        if subscription is None:
            logger.warning('Paystack webhook received for an unknown payment reference.')
            return JsonResponse({'status': 'ignored'})

        if event_type == 'charge.success':
            if (
                type(data.get('amount')) is not int
                or data['amount'] != subscription.amount
                or data.get('currency') != subscription.currency
            ):
                logger.warning(
                    'Paystack payment amount or currency mismatch for subscription %s.',
                    subscription.reference,
                )
                return JsonResponse({'error': 'Payment details do not match subscription.'}, status=400)
            _activate_subscription(subscription, _paystack_expiry(data))
        elif subscription.status == Subscription.Status.PENDING:
            subscription.status = Subscription.Status.FAILED
            subscription.save(update_fields=['status', 'updated_at'])

    return JsonResponse({'status': 'received'})

from django.contrib import messages
from django.contrib.auth import get_user_model
from django.contrib.auth.decorators import user_passes_test
from django.core.paginator import Paginator
from django.db.models import (
    CharField,
    Case,
    Count,
    Exists,
    F,
    OuterRef,
    Q,
    Subquery,
    Value,
    When,
)
from django.db.models.functions import Coalesce
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.http import require_POST

from frontend.models import (
    ClientIntakeLink,
    ClientProfile,
    ConsultantProfile,
    InjectionAuditLog,
    Subscription,
)

User = get_user_model()
PAGE_SIZE = 25


def _consultant_queryset(search=''):
    successful_subscription = Subscription.objects.filter(
        user_id=OuterRef('pk'),
        status=Subscription.Status.SUCCESSFUL,
    )
    active_subscription = (
        Subscription.objects.filter(
            user_id=OuterRef('pk'),
            status=Subscription.Status.SUCCESSFUL,
        )
        .filter(Q(expires_at__isnull=True) | Q(expires_at__gt=timezone.now()))
        .order_by('-created_at')
        .values('plan')[:1]
    )
    consultants = (
        User.objects.filter(is_superuser=False)
        .select_related('consultant_profile')
        .annotate(
            client_profile_count=Count('client_profiles', distinct=True),
            pending_link_count=Count(
                'client_intake_links',
                filter=Q(
                    client_intake_links__is_used=False,
                    client_intake_links__expires_at__gt=timezone.now(),
                ),
                distinct=True,
            ),
            active_plan=Coalesce(
                Subquery(active_subscription, output_field=CharField()),
                Case(
                    When(
                        Exists(successful_subscription),
                        then=Value('starter'),
                    ),
                    default=F('consultant_profile__plan'),
                    output_field=CharField(),
                ),
                Value('starter'),
                output_field=CharField(),
            ),
        )
        .order_by('email', 'username')
    )
    if search:
        consultants = consultants.filter(
            Q(email__icontains=search) | Q(username__icontains=search),
        )
    return consultants


def _consultant_row(consultant):
    profile = getattr(consultant, 'consultant_profile', None)
    used = consultant.client_profile_count + consultant.pending_link_count
    plan = consultant.active_plan
    if profile:
        limit = profile.profile_limit_for_plan(plan)
        has_override = profile.has_profile_limit_override
    else:
        limit = ConsultantProfile.PLAN_PROFILE_LIMITS.get(
            plan,
            ConsultantProfile.PLAN_PROFILE_LIMITS['starter'],
        )
        has_override = False
    return {
        'id': consultant.pk,
        'email': consultant.email,
        'username': consultant.username,
        'agency': profile.firm_name if profile and profile.firm_name else '',
        'plan': dict(ConsultantProfile.PLAN_CHOICES).get(plan, plan.title()),
        'plan_code': plan,
        'client_count': consultant.client_profile_count,
        'quota_used': used,
        'quota_limit': limit,
        'quota_display': f'{used} / {limit if limit is not None else "Unlimited"}',
        'has_quota_override': has_override,
        'date_joined': (
            f'{timezone.localtime(consultant.date_joined):%b} '
            f'{timezone.localtime(consultant.date_joined).day}, '
            f'{timezone.localtime(consultant.date_joined):%Y}'
        )
        if consultant.date_joined
        else '',
        'is_active': consultant.is_active,
        'detail_url': reverse('super_admin:consultant_detail', args=[consultant.pk]),
        'quota_url': reverse('super_admin:consultant_quota', args=[consultant.pk]),
        'status_url': reverse('super_admin:consultant_status', args=[consultant.pk]),
    }


@user_passes_test(lambda u: u.is_superuser)
def dashboard(request):
    search = request.GET.get('q', '').strip()[:100]
    paginator = Paginator(_consultant_queryset(search), PAGE_SIZE)
    page = paginator.get_page(request.GET.get('page', 1))
    consultant_rows = [_consultant_row(consultant) for consultant in page.object_list]

    if request.headers.get('x-requested-with') == 'XMLHttpRequest':
        return JsonResponse({
            'results': consultant_rows,
            'page': page.number,
            'pages': paginator.num_pages,
            'has_previous': page.has_previous(),
            'has_next': page.has_next(),
            'previous_page': page.previous_page_number() if page.has_previous() else None,
            'next_page': page.next_page_number() if page.has_next() else None,
            'count': paginator.count,
        })

    link_metrics = ClientIntakeLink.objects.aggregate(
        total=Count('pk'),
        used=Count('pk', filter=Q(is_used=True)),
    )
    total_links = link_metrics['total'] or 0
    conversion_rate = (
        round((link_metrics['used'] or 0) * 100 / total_links, 1)
        if total_links
        else 0
    )
    metrics = {
        'consultants': User.objects.filter(is_superuser=False).count(),
        'filings': ClientProfile.objects.count(),
        'daily_links': ClientIntakeLink.objects.filter(
            created_at__date=timezone.localdate(),
        ).count(),
        'conversion_rate': conversion_rate,
    }

    return render(
        request,
        'super_admin/dashboard.html',
        {
            'metrics': metrics,
            'consultants': consultant_rows,
            'page_obj': page,
            'search': search,
        },
    )


@user_passes_test(lambda u: u.is_superuser)
def consultant_detail(request, consultant_id):
    consultant = get_object_or_404(
        User.objects.filter(is_superuser=False).select_related('consultant_profile'),
        pk=consultant_id,
    )
    profile = getattr(consultant, 'consultant_profile', None)
    active_subscription = (
        Subscription.objects.filter(
            user=consultant,
            status=Subscription.Status.SUCCESSFUL,
        )
        .filter(Q(expires_at__isnull=True) | Q(expires_at__gt=timezone.now()))
        .order_by('-created_at')
        .first()
    )
    if active_subscription:
        plan = active_subscription.plan
    elif consultant.subscriptions.filter(status=Subscription.Status.SUCCESSFUL).exists():
        plan = 'starter'
    else:
        plan = profile.plan if profile else 'starter'
    client_page = Paginator(
        ClientProfile.objects.filter(user=consultant)
        .select_related('intake_link')
        .order_by('-created_at', '-pk'),
        PAGE_SIZE,
    ).get_page(request.GET.get('clients_page', 1))
    link_page = Paginator(
        ClientIntakeLink.objects.filter(consultant=consultant).order_by('-created_at'),
        PAGE_SIZE,
    ).get_page(request.GET.get('links_page', 1))
    now = timezone.now()
    link_rows = [
        {
            'link': link,
            'status': (
                'Used' if link.is_used
                else 'Active' if link.expires_at > now
                else 'Expired'
            ),
        }
        for link in link_page.object_list
    ]
    audit_logs = InjectionAuditLog.objects.filter(
        consultant=consultant,
    ).select_related('client_profile').order_by('-timestamp')[:50]
    limit = profile.profile_limit_for_plan(plan) if profile else ConsultantProfile.PLAN_PROFILE_LIMITS.get(plan)
    used = (
        ClientProfile.objects.filter(user=consultant).count()
        + ClientIntakeLink.objects.filter(
            consultant=consultant,
            is_used=False,
            expires_at__gt=timezone.now(),
        ).count()
    )
    return render(
        request,
        'super_admin/consultant_detail.html',
        {
            'consultant': consultant,
            'profile': profile,
            'plan': dict(ConsultantProfile.PLAN_CHOICES).get(plan, plan.title()),
            'quota_used': used,
            'quota_limit': limit,
            'client_page': client_page,
            'link_page': link_page,
            'link_rows': link_rows,
            'audit_logs': audit_logs,
            'now': now,
        },
    )


@user_passes_test(lambda u: u.is_superuser)
@require_POST
def consultant_quota(request, consultant_id):
    consultant = get_object_or_404(User.objects.filter(is_superuser=False), pk=consultant_id)
    profile = ConsultantProfile.objects.filter(user=consultant).first()
    if profile is None:
        messages.error(request, 'This account has no consultant profile to manage.')
        return redirect('super_admin:dashboard')

    mode = request.POST.get('quota_mode')
    if mode == 'plan':
        profile.has_profile_limit_override = False
        profile.profile_limit_override = None
    elif mode == 'unlimited':
        profile.has_profile_limit_override = True
        profile.profile_limit_override = None
    elif mode == 'custom':
        raw_limit = request.POST.get('profile_limit', '').strip()
        try:
            limit = int(raw_limit)
        except ValueError:
            messages.error(request, 'Enter a whole-number quota of zero or greater.')
            return redirect('super_admin:consultant_detail', consultant_id=consultant.pk)
        if limit < 0 or limit > 2_147_483_647:
            messages.error(request, 'Enter a quota between zero and 2,147,483,647.')
            return redirect('super_admin:consultant_detail', consultant_id=consultant.pk)
        profile.has_profile_limit_override = True
        profile.profile_limit_override = limit
    else:
        messages.error(request, 'Choose a valid quota setting.')
        return redirect('super_admin:consultant_detail', consultant_id=consultant.pk)

    profile.save(update_fields=['has_profile_limit_override', 'profile_limit_override'])
    messages.success(request, 'Consultant quota updated.')
    return redirect('super_admin:consultant_detail', consultant_id=consultant.pk)


@user_passes_test(lambda u: u.is_superuser)
@require_POST
def consultant_status(request, consultant_id):
    consultant = get_object_or_404(User.objects.filter(is_superuser=False), pk=consultant_id)
    requested_status = request.POST.get('active')
    if requested_status not in {'true', 'false'}:
        messages.error(request, 'Choose a valid account status.')
        return redirect('super_admin:dashboard')

    consultant.is_active = requested_status == 'true'
    consultant.save(update_fields=['is_active'])
    messages.success(
        request,
        'Consultant account activated.' if consultant.is_active else 'Consultant account deactivated.',
    )
    next_url = request.POST.get('next', '')
    if next_url == 'detail':
        return redirect('super_admin:consultant_detail', consultant_id=consultant.pk)
    return redirect('super_admin:dashboard')

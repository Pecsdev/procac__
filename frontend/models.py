import uuid
from datetime import timedelta

from django.conf import settings
from django.core.validators import RegexValidator
from django.db import models
from django.utils import timezone

from .utils import calculate_subscription_expiry


def intake_link_expiry():
    return timezone.now() + timedelta(hours=10)


class ConsultantProfile(models.Model):
    PLAN_CHOICES = [
        ('starter', 'Starter'),
        ('standard', 'Standard'),
        ('premium', 'Premium'),
        ('enterprise', 'Enterprise'),
        ('ultimate_enterprise', 'Ultimate Enterprise'),
    ]
    PLAN_PROFILE_LIMITS = {
        'starter': 5,
        'standard': 15,
        'premium': 25,
        'enterprise': 25,
        'ultimate_enterprise': None,
    }
    PLAN_ENTITY_PROFILE_LIMITS = {
        'standard': {'BN': 5, 'LTD': 5, 'IT': 5},
    }

    user = models.OneToOneField(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='consultant_profile',
    )
    accreditation_number = models.CharField(max_length=100, unique=True)
    profile_picture = models.ImageField(
        upload_to='profile_pictures/',
        blank=True,
        null=True,
    )
    phone_number = models.CharField(max_length=30, blank=True)
    firm_name = models.CharField(max_length=255, blank=True)
    office_address = models.CharField(max_length=255, blank=True)
    call_to_bar_number = models.CharField(max_length=100, blank=True)
    presenter_state = models.CharField(max_length=100, blank=True)
    presenter_lga = models.CharField(max_length=100, blank=True)
    presenter_phone = models.CharField(max_length=30, blank=True)
    presenter_email = models.EmailField(blank=True)
    extension_token_hash = models.CharField(max_length=64, blank=True)
    plan = models.CharField(max_length=20, choices=PLAN_CHOICES, default='starter')
    has_profile_limit_override = models.BooleanField(default=False)
    profile_limit_override = models.PositiveIntegerField(null=True, blank=True)

    def __str__(self):
        return f'{self.user.get_full_name()} ({self.accreditation_number})'

    @property
    def extension_key_active(self):
        return bool(self.extension_token_hash)

    def profile_limit_for_plan(self, plan=None):
        if self.has_profile_limit_override:
            return self.profile_limit_override
        plan = plan or self.plan
        return self.PLAN_PROFILE_LIMITS.get(plan, self.PLAN_PROFILE_LIMITS['starter'])

    def can_add_client(self, registration_type, plan=None, exclude_client_id=None):
        plan = plan or self.plan
        if registration_type not in dict(ClientProfile.ENTITY_TYPES):
            return False, 'Choose a valid client registration type.'

        clients = ClientProfile.objects.filter(user=self.user)
        if exclude_client_id is not None:
            clients = clients.exclude(pk=exclude_client_id)
        total_limit = self.profile_limit_for_plan(plan)
        if total_limit is not None and clients.count() >= total_limit:
            return False, 'Your plan profile limit is reached. Upgrade your plan to add more clients.'

        category_limit = self.PLAN_ENTITY_PROFILE_LIMITS.get(plan, {}).get(registration_type)
        if category_limit is not None and clients.filter(entity_type=registration_type).count() >= category_limit:
            category_label = dict(ClientProfile.ENTITY_TYPES)[registration_type]
            return False, f'Your {category_label} allocation is full. Upgrade your plan to add more clients.'

        return True, ''


class ClientProfile(models.Model):
    class Status(models.TextChoices):
        DRAFT = 'DRAFT', 'Draft'
        READY = 'READY', 'Ready for Portal Fill'
        COMPLETED = 'COMPLETED', 'Successfully Registered'

    ENTITY_TYPES = [
        ('BN', 'Business Name'),
        ('LTD', 'Private Limited'),
        ('IT', 'Incorporated Trustee'),
    ]

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='client_profiles',
        db_index=True,
    )
    intake_link = models.OneToOneField(
        'ClientIntakeLink',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='client_profile',
    )
    status = models.CharField(
        max_length=9,
        choices=Status.choices,
        default=Status.READY,
    )
    entity_name = models.CharField(max_length=255)
    entity_type = models.CharField(max_length=3, choices=ENTITY_TYPES)
    nin = models.CharField(
        max_length=11,
        blank=True,
        validators=[RegexValidator(r'^\d{11}$', 'Enter an 11-digit NIN.')],
    )
    email = models.EmailField()
    proposed_name_1 = models.CharField(max_length=255, blank=True)
    proposed_name_2 = models.CharField(max_length=255, blank=True)
    classification = models.CharField(max_length=255, blank=True)
    business_type = models.CharField(max_length=255, blank=True)
    principal_activity = models.CharField(max_length=255, blank=True, db_index=True)
    specific_activity = models.CharField(max_length=255, blank=True, db_index=True)
    nature_category = models.CharField(max_length=255, blank=True)
    specific_nature = models.CharField(max_length=255, blank=True)
    objectives = models.TextField(blank=True)
    street_address = models.CharField(max_length=255, blank=True)
    city = models.CharField(max_length=100, blank=True)
    lga = models.CharField(max_length=100, blank=True)
    state = models.CharField(max_length=100, blank=True)
    phone = models.CharField(max_length=30, blank=True)
    commencement_date = models.DateField(null=True, blank=True)
    directors = models.JSONField(default=list, blank=True)
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-updated_at']

    def __str__(self):
        return f'{self.entity_name} ({self.get_entity_type_display()})'


class ClientIntakeLink(models.Model):
    FILING_TYPES = ClientProfile.ENTITY_TYPES

    consultant = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='client_intake_links',
        db_index=True,
    )
    token = models.UUIDField(default=uuid.uuid4, unique=True)
    filing_type = models.CharField(max_length=3, choices=FILING_TYPES)
    client_name_hint = models.CharField(max_length=255, blank=True, null=True)
    is_used = models.BooleanField(default=False, db_index=True)
    expires_at = models.DateTimeField(default=intake_link_expiry, db_index=True)
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)

    class Meta:
        ordering = ['-created_at']

    def __str__(self):
        return f'{self.get_filing_type_display()} intake for {self.consultant}'


class InjectionAuditLog(models.Model):
    class Status(models.TextChoices):
        SUCCESS = 'success', 'Success'
        FAILURE = 'failure', 'Failure'

    timestamp = models.DateTimeField(auto_now_add=True, db_index=True)
    consultant = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='injection_audit_logs',
        db_index=True,
    )
    client_profile = models.ForeignKey(
        ClientProfile,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='injection_audit_logs',
    )
    status = models.CharField(max_length=8, choices=Status.choices, db_index=True)
    fields_populated = models.PositiveSmallIntegerField(default=0)

    class Meta:
        ordering = ['-timestamp']


class Subscription(models.Model):
    class Status(models.TextChoices):
        PENDING = 'pending', 'Pending'
        SUCCESSFUL = 'successful', 'Successful'
        FAILED = 'failed', 'Failed'

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='subscriptions',
    )
    plan = models.CharField(max_length=20, choices=ConsultantProfile.PLAN_CHOICES)
    amount = models.PositiveIntegerField(help_text='Amount in the currency minor unit (kobo).')
    currency = models.CharField(max_length=3, default='NGN')
    reference = models.CharField(max_length=100, unique=True)
    status = models.CharField(
        max_length=20,
        choices=Status.choices,
        default=Status.PENDING,
    )
    authorization_url = models.URLField(max_length=500, blank=True)
    access_code = models.CharField(max_length=100, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    paid_at = models.DateTimeField(null=True, blank=True)
    expires_at = models.DateTimeField(null=True, blank=True, db_index=True)

    class Meta:
        ordering = ['-created_at']

    def __str__(self):
        return f'{self.reference} ({self.get_status_display()})'

    def can_add_client(self, registration_type, exclude_client_id=None):
        if self.status != self.Status.SUCCESSFUL or (
            self.expires_at is not None and self.expires_at <= timezone.now()
        ):
            return False, 'Your subscription is inactive. Upgrade or renew your plan to add clients.'
        profile = ConsultantProfile.objects.filter(user_id=self.user_id).first()
        if profile is None:
            return False, 'Complete your consultant profile before adding clients.'
        return profile.can_add_client(
            registration_type,
            plan=self.plan,
            exclude_client_id=exclude_client_id,
        )

import json

from django import forms
from django.contrib.auth import get_user_model
from django.contrib.auth.forms import UserCreationForm
from django.core.exceptions import ValidationError
from django.db import transaction

from .business_activities import (
    BUSINESS_ACTIVITY_MAP,
    PRINCIPAL_ACTIVITY_CHOICES,
    SPECIFIC_ACTIVITY_CHOICES,
)
from .locations import STATE_CHOICES, STATE_LGA_MAP, lga_choices_for_state
from .models import ClientProfile, ConsultantProfile

User = get_user_model()


class ConsultantSignupForm(UserCreationForm):
    full_name = forms.CharField(max_length=150)
    accreditation_number = forms.CharField(max_length=100)
    email = forms.EmailField(max_length=150)
    phone_number = forms.CharField(max_length=30, required=False)
    firm_name = forms.CharField(max_length=255, required=False)

    class Meta(UserCreationForm.Meta):
        model = User
        fields = (
            'full_name',
            'accreditation_number',
            'email',
            'phone_number',
            'firm_name',
        )
        field_classes = {}

    def clean_phone_number(self):
        return self.cleaned_data['phone_number'].strip()

    def clean_firm_name(self):
        return self.cleaned_data['firm_name'].strip()

    def clean_email(self):
        email = self.cleaned_data['email'].strip().lower()
        if User.objects.filter(email__iexact=email).exists():
            raise ValidationError('An account with this email already exists.')
        if User.objects.filter(username__iexact=email).exists():
            raise ValidationError('An account with this email already exists.')
        return email

    def clean_accreditation_number(self):
        number = self.cleaned_data['accreditation_number'].strip()
        if ConsultantProfile.objects.filter(accreditation_number__iexact=number).exists():
            raise ValidationError('This accreditation number is already registered.')
        return number

    @transaction.atomic
    def save(self, commit=True):
        user = super().save(commit=False)
        user.username = self.cleaned_data['email']
        user.email = self.cleaned_data['email']
        user.first_name = self.cleaned_data['full_name'].strip()
        if commit:
            user.save()
            ConsultantProfile.objects.create(
                user=user,
                accreditation_number=self.cleaned_data['accreditation_number'],
                phone_number=self.cleaned_data['phone_number'],
                firm_name=self.cleaned_data['firm_name'],
            )
        return user


class ConsultantProfileForm(forms.ModelForm):
    full_name = forms.CharField(max_length=150)
    email = forms.EmailField(max_length=150)

    class Meta:
        model = ConsultantProfile
        fields = (
            'full_name',
            'email',
            'accreditation_number',
            'profile_picture',
            'phone_number',
            'firm_name',
            'office_address',
            'call_to_bar_number',
            'presenter_state',
            'presenter_lga',
            'presenter_phone',
            'presenter_email',
        )
        widgets = {
            'office_address': forms.Textarea(attrs={'rows': 3}),
            'profile_picture': forms.ClearableFileInput(
                attrs={'accept': 'image/*', 'class': 'form-control'},
            ),
        }

    def __init__(self, *args, user, **kwargs):
        self.user = user
        initial = kwargs.setdefault('initial', {})
        initial.setdefault('full_name', user.get_full_name())
        initial.setdefault('email', user.email)
        super().__init__(*args, **kwargs)
        self.fields['accreditation_number'].disabled = True

    def clean_email(self):
        email = self.cleaned_data['email'].strip().lower()
        if User.objects.filter(email__iexact=email).exclude(pk=self.user.pk).exists():
            raise ValidationError('An account with this email already exists.')
        if User.objects.filter(username__iexact=email).exclude(pk=self.user.pk).exists():
            raise ValidationError('An account with this email already exists.')
        return email

    @transaction.atomic
    def save(self, commit=True):
        profile = super().save(commit=False)
        profile.user = self.user
        self.user.first_name = self.cleaned_data['full_name'].strip()
        self.user.email = self.cleaned_data['email']
        self.user.username = self.cleaned_data['email']
        if commit:
            self.user.save(update_fields=['first_name', 'email', 'username'])
            profile.save()
        return profile


class ClientProfileForm(forms.ModelForm):
    entity_name = forms.CharField(required=False, widget=forms.HiddenInput)
    directors_json = forms.CharField(required=False, widget=forms.HiddenInput)

    class Meta:
        model = ClientProfile
        fields = (
            'entity_name',
            'entity_type',
            'nin',
            'email',
            'proposed_name_1',
            'proposed_name_2',
            'classification',
            'business_type',
            'principal_activity',
            'specific_activity',
            'nature_category',
            'specific_nature',
            'objectives',
            'street_address',
            'city',
            'lga',
            'state',
            'phone',
            'commencement_date',
        )
        widgets = {
            'entity_type': forms.Select(attrs={'class': 'form-select'}),
            'commencement_date': forms.DateInput(attrs={'type': 'date'}),
            'state': forms.Select(attrs={'id': 'id_state'}),
            'lga': forms.Select(attrs={'id': 'id_lga'}),
            'principal_activity': forms.Select(
                attrs={'id': 'id_principal_activity'},
            ),
            'specific_activity': forms.Select(
                attrs={'id': 'id_specific_activity'},
            ),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['nin'].required = False
        state = (
            self.data.get('state', '')
            if self.is_bound
            else self.initial.get('state', self.instance.state)
        )
        principal_activity = (
            self.data.get('principal_activity', '')
            if self.is_bound
            else self.initial.get(
                'principal_activity',
                self.instance.principal_activity,
            )
        )
        self.fields['state'].widget.choices = (('', 'Select a state'),) + STATE_CHOICES
        self.fields['lga'].widget.choices = lga_choices_for_state(state)
        principal_choices = (
            ('', 'Select a principal business activity'),
        ) + PRINCIPAL_ACTIVITY_CHOICES
        specific_choices = (
            ('', 'Select a specific business activity'),
        ) + tuple(
            (activity, activity)
            for activity in BUSINESS_ACTIVITY_MAP.get(principal_activity, ())
        )
        self.fields['principal_activity'].widget.choices = principal_choices
        self.fields['specific_activity'].widget.choices = specific_choices

    def clean(self):
        cleaned_data = super().clean()
        proposed_name = cleaned_data.get('proposed_name_1', '').strip()
        legacy_name = cleaned_data.get('entity_name', '').strip()
        cleaned_data['entity_name'] = proposed_name or legacy_name
        if not cleaned_data.get('proposed_name_1'):
            cleaned_data['proposed_name_1'] = legacy_name

        directors = cleaned_data.get('directors_json', '')
        try:
            parsed_directors = json.loads(directors) if directors else []
        except json.JSONDecodeError as error:
            raise ValidationError({'directors_json': 'Enter valid stakeholder details.'}) from error
        if not isinstance(parsed_directors, list) or any(
            not isinstance(director, dict) for director in parsed_directors
        ):
            raise ValidationError({'directors_json': 'Stakeholder details must be a list of objects.'})

        director_fields = {
            'full_name', 'dob', 'gender', 'nationality', 'identity_type',
            'identity_number', 'email', 'phone', 'residential_address',
            'share_allocation', 'designation',
        }
        normalized_directors = []
        for director in parsed_directors:
            if director.keys() - director_fields:
                raise ValidationError({'directors_json': 'Stakeholder details contain unsupported fields.'})
            normalized_directors.append({
                key: str(director.get(key, '')).strip()
                for key in director_fields
                if director.get(key) is not None
            })
        cleaned_data['directors'] = normalized_directors

        primary_director = normalized_directors[0] if normalized_directors else {}
        if (
            not cleaned_data.get('nin')
            and primary_director.get('identity_type', '').lower() == 'nin'
        ):
            cleaned_data['nin'] = primary_director.get('identity_number', '')

        principal_activity = cleaned_data.get('principal_activity', '')
        specific_activity = cleaned_data.get('specific_activity', '')
        valid_specific_activities = BUSINESS_ACTIVITY_MAP.get(principal_activity)
        if principal_activity and valid_specific_activities is None:
            self.add_error(
                'principal_activity',
                'Choose a listed principal business activity.',
            )
        elif principal_activity and specific_activity not in valid_specific_activities:
            self.add_error(
                'specific_activity',
                'Choose a specific activity for the selected principal activity.',
            )

        state = cleaned_data.get('state', '')
        lga = cleaned_data.get('lga', '')
        if state and state not in STATE_LGA_MAP:
            self.add_error('state', 'Choose a listed Nigerian state.')
        if lga and lga not in STATE_LGA_MAP.get(state, ()):
            self.add_error('lga', 'Choose an LGA for the selected state.')
        return cleaned_data

    def clean_entity_name(self):
        return self.cleaned_data['entity_name'].strip()

    def clean_nin(self):
        return self.cleaned_data['nin'].strip()

    def clean_email(self):
        return self.cleaned_data['email'].strip()

    def clean_nature_category(self):
        return self.cleaned_data['nature_category'].strip()

    def clean_specific_nature(self):
        return self.cleaned_data['specific_nature'].strip()

    def save(self, commit=True):
        profile = super().save(commit=False)
        profile.entity_name = self.cleaned_data['entity_name']
        profile.directors = self.cleaned_data['directors']
        if commit:
            profile.save()
            self.save_m2m()
        return profile

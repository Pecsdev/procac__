from django.contrib import admin

from .models import (
    ClientIntakeLink,
    ClientProfile,
    ConsultantProfile,
    InjectionAuditLog,
    Subscription,
)


@admin.register(ClientIntakeLink)
class ClientIntakeLinkAdmin(admin.ModelAdmin):
    list_display = ('client_name_hint', 'consultant', 'filing_type', 'is_used', 'expires_at', 'created_at')
    search_fields = ('client_name_hint', 'consultant__email', 'token')
    list_filter = ('filing_type', 'is_used')
    readonly_fields = ('token', 'created_at')


@admin.register(InjectionAuditLog)
class InjectionAuditLogAdmin(admin.ModelAdmin):
    list_display = ('timestamp', 'consultant', 'client_profile', 'status', 'fields_populated')
    search_fields = ('consultant__email', 'client_profile__entity_name')
    list_filter = ('status',)
    readonly_fields = ('timestamp',)


@admin.register(ClientProfile)
class ClientProfileAdmin(admin.ModelAdmin):
    list_display = ('entity_name', 'user', 'entity_type', 'status', 'updated_at')
    search_fields = ('entity_name', 'user__email')
    list_filter = ('status', 'entity_type')


@admin.register(ConsultantProfile)
class ConsultantProfileAdmin(admin.ModelAdmin):
    list_display = ('user', 'accreditation_number', 'plan')
    search_fields = ('user__email', 'accreditation_number')
    list_filter = ('plan',)


@admin.register(Subscription)
class SubscriptionAdmin(admin.ModelAdmin):
    list_display = ('reference', 'user', 'plan', 'amount', 'currency', 'status', 'created_at')
    search_fields = ('reference', 'user__email')
    list_filter = ('status', 'plan', 'currency')
    readonly_fields = ('created_at', 'updated_at', 'paid_at')

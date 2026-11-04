from django.urls import path, re_path

from . import views

urlpatterns = [
    re_path(r'^go/(?P<token>[A-Za-z0-9_-]+)/$', views.encoded_page_link, name='encoded_page_link'),
    path('', views.home, name='home'),
    path('login/', views.login_view, name='login'),
    path('signup/', views.signup, name='signup'),
    path('verify-otp/', views.verify_otp, name='verify_otp'),
    path('plans/', views.plans, name='plans'),
    path('agency-profile/', views.agency_profile_view, name='agency_profile'),
    path('logout/', views.logout_view, name='logout'),
    path('dashboard/', views.dashboard, name='dashboard'),
    path('dashboard/intake-links/', views.generate_intake_link, name='generate_intake_link'),
    path('dashboard/intake-links/status/', views.intake_link_status, name='intake_link_status'),
    path('portal/fill/<uuid:token>/', views.client_fill_view, name='client_fill_view'),
    path('payments/callback/', views.paystack_callback, name='payment_callback'),
    path('intake/', views.intake, name='intake'),
    path('admin-panel/', views.admin_dashboard, name='admin_dashboard'),
    path('api/payments/initialize/', views.initialize_payment, name='payment_initialize'),
    path('api/payments/paystack-webhook/', views.paystack_webhook, name='paystack_webhook'),
    path('api/extension/status/', views.extension_status, name='extension_status'),
    path('api/extension/clients/', views.extension_clients, name='extension_clients'),
    path('api/extension/injection-audits/', views.extension_injection_audit, name='extension_injection_audit'),
]

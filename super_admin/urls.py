from django.urls import path

from . import views

app_name = 'super_admin'

urlpatterns = [
    path('', views.dashboard, name='dashboard'),
    path('consultant/<int:consultant_id>/', views.consultant_detail, name='consultant_detail'),
    path('consultant/<int:consultant_id>/quota/', views.consultant_quota, name='consultant_quota'),
    path('consultant/<int:consultant_id>/status/', views.consultant_status, name='consultant_status'),
]

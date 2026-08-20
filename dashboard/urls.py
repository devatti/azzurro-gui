from django.urls import path

from . import views

urlpatterns = [
    path('', views.dashboard, name='dashboard'),
    path('history/', views.history, name='history'),
    path('settings/', views.portal_settings, name='settings'),
    path('api/realtime/', views.api_realtime, name='api-realtime'),
    path('api/history/', views.api_history, name='api-history'),
]
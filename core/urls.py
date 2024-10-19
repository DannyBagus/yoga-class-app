from django.contrib import admin
from django.urls import path, include
from core import views

urlpatterns = [
    path('', views.home, name='home'),
    path('users/', include('users.urls')),
    path('api/', include('api.urls')),
    path('kurse/', include('course.urls')),
    path('yoga/', views.yoga, name='yoga'),
    path('pilates/', views.pilates, name='pilates'),
    path('impressum/', views.impressum, name='impressum'),
]
from django.urls import path
from .views import *

urlpatterns = [
    path('courses/', CoursesListView.as_view(), name='courses-list'),
    path('user-bookings/<str:email>/', UserBookingsView.as_view(), name='user-bookings'),
]

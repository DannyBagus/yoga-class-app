from django.urls import path
from .views import *

urlpatterns = [
    path('', CourseListView.as_view(), name="courses"),
    path('filter-courses/', filter_courses, name="filter-courses"),
    path('booking/', create_booking, name="create-booking"),
    path('cancel-booking/', cancel_booking, name="cancel-booking"),
    path('show-attendees/', show_attendees, name="show-attendees"),
    ]
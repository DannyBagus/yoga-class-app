from django.contrib import admin

from .models import Courses, Category, Booking

admin.site.register(Courses)
admin.site.register(Category)
admin.site.register(Booking)
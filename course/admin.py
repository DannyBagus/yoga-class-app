from django.contrib import admin

from .models import Courses, Category, Booking

class BookingInline(admin.TabularInline):
    model = Booking
    # Felder die im Inline angezeigt werden sollen
    fields = ['user', 'date']

    extra = 0  # Anzahl der zusätzlichen leeren Formulare
    
class CourseAdmin(admin.ModelAdmin):
    list_display = ('name',)
    inlines = [BookingInline]

admin.site.register(Courses, CourseAdmin)
admin.site.register(Category)
admin.site.register(Booking)
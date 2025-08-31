from django.contrib import admin

from .models import Courses, Category, Booking

class BookingInline(admin.TabularInline):
    model = Booking
    # Felder die im Inline angezeigt werden sollen
    fields = ['customer_full_name', 'date']
    readonly_fields = ['customer_full_name', 'date']
    can_delete = False  # Verhindert das Löschen von Buchungen im Inline

    extra = 0  # Anzahl der zusätzlichen leeren Formulare
    
    def customer_full_name(self, obj):
        if obj.user:
            return f"{obj.user.first_name} {obj.user.last_name}"
        else:
            return "No user"
    
class CourseAdmin(admin.ModelAdmin):
    list_display = ('name','date', 'start', 'category', 'topic', 'capacity')
    ordering = ['-date']
    inlines = [BookingInline]

admin.site.register(Courses, CourseAdmin)
admin.site.register(Category)
admin.site.register(Booking)
from django.contrib import admin
from django.contrib.auth.admin import UserAdmin as BaseUserAdmin
from django.contrib.auth.models import User

# Import der eigenen Models
from .models import Credits, PurchaseTransaction
# Import des Booking Models aus der anderen App (absolute Import)
from course.models import Booking 

# --- Bestehende Registrierungen (bleiben erhalten) ---
admin.site.register(Credits)
admin.site.register(PurchaseTransaction)

# --- Neue Logik für die User-Erweiterung ---

class BookingInline(admin.TabularInline):
    model = Booking
    extra = 0 # Keine leeren Zeilen anzeigen
    can_delete = False # Optional: Verhindert versehentliches Löschen durch Admin in dieser Ansicht
    
    # Felder definieren: Kurs (Link), Kursdatum (berechnet) und Buchungsdatum
    fields = ['course', 'get_course_date', 'date']
    readonly_fields = ['course', 'get_course_date', 'date']

    def get_course_date(self, obj):
        return obj.course.date
    get_course_date.short_description = "Kursdatum"
    get_course_date.admin_order_field = 'course__date'

class UserAdmin(BaseUserAdmin):
    # Fügt die Buchungsliste unten in der User-Detailansicht an
    inlines = [BookingInline]

# Den Standard-User deregistrieren und mit der Erweiterung neu registrieren
admin.site.unregister(User)
admin.site.register(User, UserAdmin)
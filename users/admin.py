from django.contrib import admin
from django.contrib.auth.admin import UserAdmin as BaseUserAdmin
from django.contrib.auth.models import User

from .models import Credits, PurchaseTransaction
from course.models import Booking 

# --- 1. Custom Admin für Credits ---

class CreditsAdmin(admin.ModelAdmin):
    # Zeigt User und Anzahl in getrennten Spalten
    list_display = ('get_full_name', 'user', 'number')
    
    # Ermöglicht Klick auf Spaltenkopf zum Sortieren
    ordering = ('user__first_name', 'user__last_name')
    
    # Suche oben rechts (User Name, Mail)
    search_fields = ('user__username', 'user__first_name', 'user__last_name', 'user__email')
    
    # Optional: User Link anklickbar machen, aber 'get_full_name' ist schöner zu lesen
    def get_full_name(self, obj):
        return f"{obj.user.first_name} {obj.user.last_name}"
    get_full_name.short_description = "Kunde"
    get_full_name.admin_order_field = 'user__last_name' # Sortierung basierend auf Nachname

# --- 2. Custom Admin für PurchaseTransaction ---

class PurchaseTransactionAdmin(admin.ModelAdmin):
    list_display = ('date', 'user', 'number', 'status')
    list_filter = ('status', 'date') 
    search_fields = ('user__username', 'user__last_name', 'user__email')
    ordering = ('-date',) # Neueste zuerst

# --- 3. User Admin Erweiterung (Booking Inline) ---

class BookingInline(admin.TabularInline):
    model = Booking
    extra = 0
    can_delete = False
    fields = ['course', 'get_course_date', 'date']
    readonly_fields = ['course', 'get_course_date', 'date']

    def get_course_date(self, obj):
        return obj.course.date
    get_course_date.short_description = "Kursdatum"
    get_course_date.admin_order_field = 'course__date'

class UserAdmin(BaseUserAdmin):
    inlines = [BookingInline]
    # Optional: Zeigt Credits direkt in der User-Übersicht als Spalte an (wenn gewünscht)
    list_display = BaseUserAdmin.list_display + ('get_credits',)

    def get_credits(self, obj):
        # Versucht das Credit-Objekt zu holen, falls es existiert
        if hasattr(obj, 'credits'):
            return obj.credits.number
        return 0
    get_credits.short_description = "Credits"

# --- Registrierungen ---

# Alte Registrierungen aufheben/überschreiben
admin.site.unregister(User)

# Neue Registrierungen
admin.site.register(User, UserAdmin)
admin.site.register(Credits, CreditsAdmin) # Jetzt mit CreditsAdmin Klasse
admin.site.register(PurchaseTransaction, PurchaseTransactionAdmin)
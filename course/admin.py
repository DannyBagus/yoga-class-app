from django.contrib import admin, messages
from django.db.models import Count
from django.template.response import TemplateResponse
from django.urls import reverse
from django.utils import timezone
from django.utils.html import format_html

from users.models import Credits
from .models import Courses, Category, Booking


# --- Helfer -----------------------------------------------------------------

def _user_link(user):
    ''' Verlinkt einen User auf sein Admin-Profil (Credits, Historie) '''
    if not user:
        return "—"
    url = reverse("admin:auth_user_change", args=[user.pk])
    name = f"{user.first_name} {user.last_name}".strip() or user.username
    return format_html('<a href="{}">{}</a>', url, name)


def _user_credits(user):
    credits = getattr(user, "credits", None)
    return credits.number if credits else 0


class UpcomingFilterBase(admin.SimpleListFilter):
    ''' Quickfilter: kommende vs. vergangene Kurse '''
    title = "Zeitraum"
    parameter_name = "zeitraum"
    date_field = "date"  # in Subklasse überschreiben

    def lookups(self, request, model_admin):
        return (("upcoming", "Kommende"), ("past", "Vergangene"))

    def queryset(self, request, queryset):
        today = timezone.now().date()
        if self.value() == "upcoming":
            return queryset.filter(**{f"{self.date_field}__gte": today})
        if self.value() == "past":
            return queryset.filter(**{f"{self.date_field}__lt": today})
        return queryset


class CourseUpcomingFilter(UpcomingFilterBase):
    date_field = "date"


class BookingUpcomingFilter(UpcomingFilterBase):
    date_field = "course__date"


# --- Inline: Buchungen auf der Kursseite ------------------------------------

class BookingInline(admin.TabularInline):
    ''' Buchungen direkt auf der Kursseite verwalten (anlegen, bearbeiten, löschen) '''
    model = Booking
    extra = 0
    autocomplete_fields = ['user']
    fields = ['user', 'customer_link', 'customer_credits', 'date']
    readonly_fields = ['customer_link', 'customer_credits']
    can_delete = True  # Buchungen dürfen von der Kursseite aus gelöscht werden

    def customer_link(self, obj):
        return _user_link(obj.user) if obj.pk else "—"
    customer_link.short_description = "Kundin (Profil)"

    def customer_credits(self, obj):
        return _user_credits(obj.user) if obj.pk and obj.user_id else "—"
    customer_credits.short_description = "Credits"


# --- Kurse ------------------------------------------------------------------

@admin.register(Courses)
class CourseAdmin(admin.ModelAdmin):
    list_display = ('name', 'category', 'topic', 'date', 'start', 'occupancy')
    list_filter = (CourseUpcomingFilter, 'category', 'topic', 'date')
    search_fields = (
        'name', 'topic', 'category__name',
        'bookings__user__first_name', 'bookings__user__last_name',
        'bookings__user__email',
    )
    date_hierarchy = 'date'
    ordering = ['-date']
    list_select_related = ('category',)
    inlines = [BookingInline]

    def get_queryset(self, request):
        return super().get_queryset(request).annotate(_booking_count=Count('bookings'))

    def occupancy(self, obj):
        # capacity = freie Plätze (Live-Zähler), _booking_count = gebuchte Plätze
        return format_html("<b>{}</b> gebucht · {} frei", obj._booking_count, obj.capacity)
    occupancy.short_description = "Belegung"
    occupancy.admin_order_field = '_booking_count'


# --- Buchungen --------------------------------------------------------------

@admin.register(Booking)
class BookingAdmin(admin.ModelAdmin):
    list_display = ('customer_link', 'customer_credits', 'course', 'course_date', 'date')
    list_filter = (BookingUpcomingFilter, 'course__category', 'course__date', 'date')
    search_fields = (
        'user__first_name', 'user__last_name', 'user__email',
        'course__name', 'course__topic',
    )
    autocomplete_fields = ['user', 'course']
    date_hierarchy = 'course__date'
    ordering = ['-date']
    list_select_related = ('user', 'user__credits', 'course', 'course__category')
    actions = ['cancel_with_refund', 'cancel_without_refund', 'rebook_to_course']

    def customer_link(self, obj):
        return _user_link(obj.user)
    customer_link.short_description = "Kundin"
    customer_link.admin_order_field = 'user__last_name'

    def customer_credits(self, obj):
        return _user_credits(obj.user)
    customer_credits.short_description = "Credits"

    def course_date(self, obj):
        return obj.course.date
    course_date.short_description = "Kursdatum"
    course_date.admin_order_field = 'course__date'

    # --- Actions ---

    @admin.action(description="Stornieren + Credit zurückerstatten")
    def cancel_with_refund(self, request, queryset):
        count = 0
        for booking in list(queryset.select_related('user', 'course')):
            credits, _ = Credits.objects.get_or_create(user=booking.user)
            credits.number += 1
            credits.save()
            booking.course.capacity += 1  # Platz wieder freigeben
            booking.course.save(update_fields=['capacity'])
            booking.delete()
            count += 1
        self.message_user(
            request,
            f"{count} Buchung(en) storniert – je 1 Credit zurückerstattet.",
            messages.SUCCESS,
        )

    @admin.action(description="Stornieren ohne Rückerstattung")
    def cancel_without_refund(self, request, queryset):
        count = 0
        for booking in list(queryset.select_related('course')):
            booking.course.capacity += 1
            booking.course.save(update_fields=['capacity'])
            booking.delete()
            count += 1
        self.message_user(
            request,
            f"{count} Buchung(en) storniert (ohne Rückerstattung).",
            messages.WARNING,
        )

    @admin.action(description="Auf anderen Kurs umbuchen …")
    def rebook_to_course(self, request, queryset):
        if 'apply' in request.POST:
            target = Courses.objects.filter(pk=request.POST.get('target_course')).first()
            if not target:
                self.message_user(request, "Kein Zielkurs gewählt.", messages.ERROR)
                return None
            moved = skipped = 0
            for booking in list(queryset.select_related('user', 'course')):
                # Gleicher Kurs oder Kundin dort schon gebucht -> überspringen
                if booking.course_id == target.pk or \
                        Booking.objects.filter(user=booking.user, course=target).exists():
                    skipped += 1
                    continue
                old = booking.course
                old.capacity += 1
                old.save(update_fields=['capacity'])
                booking.course = target
                booking.save(update_fields=['course'])
                target.capacity = max(target.capacity - 1, 0)
                target.save(update_fields=['capacity'])
                moved += 1
            msg = f"{moved} Buchung(en) auf „{target}“ umgebucht."
            if skipped:
                msg += f" {skipped} übersprungen (gleicher Kurs oder bereits gebucht)."
            self.message_user(request, msg, messages.SUCCESS)
            return None

        # Zwischenseite: Zielkurs auswählen
        context = {
            **self.admin_site.each_context(request),
            'title': "Buchungen umbuchen",
            'bookings': queryset.select_related('user', 'course'),
            'courses': Courses.objects.select_related('category').order_by('-date'),
            'action_name': 'rebook_to_course',
            'opts': self.model._meta,
        }
        return TemplateResponse(request, 'admin/course/rebook_action.html', context)


# --- Kategorien -------------------------------------------------------------

@admin.register(Category)
class CategoryAdmin(admin.ModelAdmin):
    list_display = ('name',)
    search_fields = ('name',)

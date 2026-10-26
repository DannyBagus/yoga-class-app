from django.contrib import admin, messages
from django.db.models import Count
from django.shortcuts import get_object_or_404, redirect
from django.template.response import TemplateResponse
from django.urls import path, reverse
from django.utils import timezone
from django.utils.html import format_html

from users.models import Credits
from .cancellation import SUMMARY_RECIPIENTS, SWISS_TZ, CourseAlreadyCancelled, cancel_course
from .models import CancellationNotice, Courses, Category, Booking


# --- Helfer -----------------------------------------------------------------

def _user_link(user):
    ''' Verlinkt einen User auf sein Admin-Profil (Credits, Historie) '''
    if not user:
        return "—"
    url = reverse("admin:auth_user_change", args=[user.pk])
    name = f"{user.first_name} {user.last_name}".strip() or user.username
    return format_html('<a href="{}">{}</a>', url, name)


def _user_phone(user):
    ''' Natelnummer mit tel:- und WhatsApp-Link (fuer kurzfristige Kursinfos) '''
    profile = getattr(user, "profile", None)
    phone = profile.phone if profile else ""
    if not phone:
        return "—"
    return format_html(
        '<a href="tel:{0}">{0}</a> · <a href="https://wa.me/{1}" target="_blank" rel="noopener">WhatsApp</a>',
        phone, phone.lstrip('+'),
    )


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
    fields = ['user', 'customer_link', 'customer_phone', 'customer_credits', 'date']
    readonly_fields = ['customer_link', 'customer_phone', 'customer_credits']
    can_delete = True  # Buchungen dürfen von der Kursseite aus gelöscht werden

    def get_queryset(self, request):
        return super().get_queryset(request).select_related('user', 'user__profile', 'user__credits')

    def customer_link(self, obj):
        return _user_link(obj.user) if obj.pk else "—"
    customer_link.short_description = "Kundin (Profil)"

    def customer_phone(self, obj):
        return _user_phone(obj.user) if obj.pk and obj.user_id else "—"
    customer_phone.short_description = "Telefon"

    def customer_credits(self, obj):
        return _user_credits(obj.user) if obj.pk and obj.user_id else "—"
    customer_credits.short_description = "Credits"


class CancellationNoticeInline(admin.TabularInline):
    ''' Bei der Absage benachrichtigte Kundinnen inkl. Erhaltsbestaetigung (nur lesen) '''
    model = CancellationNotice
    extra = 0
    can_delete = False
    verbose_name_plural = "Absage-Benachrichtigungen"
    fields = ['customer_link', 'customer_phone', 'credits_before', 'credits_after',
              'mail_sent', 'confirmation']
    readonly_fields = fields

    def has_add_permission(self, request, obj=None):
        return False

    def get_queryset(self, request):
        return super().get_queryset(request).select_related('user', 'user__profile')

    def customer_link(self, obj):
        return _user_link(obj.user)
    customer_link.short_description = "Kundin"

    def customer_phone(self, obj):
        return _user_phone(obj.user)
    customer_phone.short_description = "Telefon"

    def confirmation(self, obj):
        if obj.confirmed_at:
            return format_html('<span style="color:#047857;font-weight:600;">✔ {}</span>',
                               timezone.localtime(obj.confirmed_at, SWISS_TZ).strftime('%d.%m.%Y %H:%M'))
        return format_html('<span style="color:#ba2121;font-weight:600;">{}</span>', "offen")
    confirmation.short_description = "Erhalt bestätigt"


# --- Kurse ------------------------------------------------------------------

@admin.register(Courses)
class CourseAdmin(admin.ModelAdmin):
    list_display = ('name', 'category', 'topic', 'date', 'start', 'occupancy', 'is_cancelled')
    list_filter = (CourseUpcomingFilter, 'is_cancelled', 'category', 'topic', 'date')
    readonly_fields = ('cancelled_at',)
    search_fields = (
        'name', 'topic', 'category__name',
        'bookings__user__first_name', 'bookings__user__last_name',
        'bookings__user__email',
    )
    date_hierarchy = 'date'
    ordering = ['-date']
    list_select_related = ('category',)
    inlines = [BookingInline]

    def get_inlines(self, request, obj):
        # Abgesagte Kurse: zusaetzlich wer benachrichtigt wurde und wer bestaetigt hat
        if obj is not None and obj.is_cancelled:
            return [CancellationNoticeInline, BookingInline]
        return [BookingInline]

    def get_queryset(self, request):
        return super().get_queryset(request).annotate(_booking_count=Count('bookings'))

    def occupancy(self, obj):
        # capacity = freie Plätze (Live-Zähler), _booking_count = gebuchte Plätze
        return format_html("<b>{}</b> gebucht · {} frei", obj._booking_count, obj.capacity)
    occupancy.short_description = "Belegung"
    occupancy.admin_order_field = '_booking_count'

    # --- Kurs absagen (roter Button auf der Detailseite) ---

    def get_urls(self):
        custom = [
            path('<path:object_id>/absagen/', self.admin_site.admin_view(self.cancel_course_view),
                 name='course_courses_cancel'),
        ]
        return custom + super().get_urls()

    def change_view(self, request, object_id, form_url='', extra_context=None):
        course = self.get_object(request, object_id)
        if course is not None and not course.is_cancelled:
            bookings = course.bookings.select_related('user', 'user__credits')
            extra_context = {
                **(extra_context or {}),
                'cancel_url': reverse('admin:course_courses_cancel', args=[course.pk]),
                'cancel_bookings': [
                    (f"{b.user.first_name} {b.user.last_name}".strip() or b.user.username,
                     _user_credits(b.user))
                    for b in bookings
                ],
            }
        return super().change_view(request, object_id, form_url, extra_context)

    def cancel_course_view(self, request, object_id):
        course = get_object_or_404(Courses, pk=object_id)
        change_url = reverse('admin:course_courses_change', args=[course.pk])
        if request.method != 'POST' or not self.has_change_permission(request, course):
            return redirect(change_url)

        try:
            result = cancel_course(course.pk, cancelled_by=request.user)
        except CourseAlreadyCancelled:
            self.message_user(request, "Der Kurs war bereits abgesagt.", messages.WARNING)
            return redirect(change_url)

        refunds = ", ".join(
            f"{u.first_name} {u.last_name} ({before}→{after})" for u, before, after in result.refunds
        ) or "keine Buchungen"
        course.refresh_from_db()
        self.log_change(request, course,
                        f"Kurs abgesagt. {len(result.refunds)} Buchung(en) storniert, "
                        f"Credits gutgeschrieben: {refunds}. E-Mails versendet: {result.mails_sent}.")

        self.message_user(
            request,
            f"Kurs abgesagt: {len(result.refunds)} Buchung(en) storniert, je 1 Credit gutgeschrieben, "
            f"{result.mails_sent} E-Mail(s) versendet. Zusammenfassung an "
            f"{', '.join(SUMMARY_RECIPIENTS)}: {'versendet' if result.summary_sent else 'FEHLGESCHLAGEN'}.",
            messages.SUCCESS if result.summary_sent else messages.WARNING,
        )
        if result.mail_failures:
            names = ", ".join(f"{u.first_name} {u.last_name} <{u.email or 'keine E-Mail'}>"
                              for u in result.mail_failures)
            self.message_user(request, f"E-Mail fehlgeschlagen, bitte telefonisch informieren: {names}",
                              messages.ERROR)
        return redirect(change_url)


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

from typing import Any
from django.db.models import Count, Q
from django.http import Http404, HttpResponse
from django.template.loader import render_to_string
from django.core.mail import send_mail
from django.shortcuts import render, get_object_or_404
from course import waitlist
from course.booking import BookingResult, book, cancellation_refundable
from course.models import Courses, Booking, WaitlistEntry
from course.cancellation import confirm_receipt, notice_from_token
from course.waitlist import ClaimResult, WaitlistError
from users.models import Credits
from django.contrib.auth.models import User
from django.views.generic import ListView
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.utils import timezone
from datetime import datetime, timedelta

def _decorate(courses, user):
    """Kurse fuer die Karten aufbereiten: Datum/Zeit formatiert, Anzahl Wartende
    (ohne Namen), Buchungen und Wartelisten-Eintraege der eingeloggten Kundin."""
    courses = courses.select_related('category').annotate(
        waitlist_count=Count('waitlist_entries',
                             filter=Q(waitlist_entries__status=WaitlistEntry.WAITING),
                             distinct=True),
    ).order_by('date', 'start')  # Meta.ordering gilt bei GROUP BY (annotate) nicht
    for course in courses:
        course.formatted_date = course.date.strftime('%d.%m.%Y')  # Format date as day.month.year
        course.formatted_time = course.start.strftime('%H:%M')    # Format time as hour:minute
    if user.is_authenticated:
        booked = set(Booking.objects.filter(user=user).values_list('course_id', flat=True))
        for course in courses:
            if course.pk in booked:  # fuer die Rueckfrage beim Abmelden
                course.cancel_refundable = cancellation_refundable(course)
        waitlisted = set(WaitlistEntry.objects.filter(user=user, status=WaitlistEntry.WAITING)
                         .values_list('course_id', flat=True))
    else:
        booked, waitlisted = set(), set()
    return {'courses': courses, 'booked_courses': booked, 'waitlisted_courses': waitlisted}


_CATEGORY_FILTERS = {'yoga': 'Yoga', 'pilates': 'Pilates', 'mamifit': 'MamiFit'}


def _filtered_courses(request):
    """Kommende Kurse gemaess ``?filter=`` (Chips oben auf der Seite). Wird auch
    nach Buchen/Abmelden/Warteliste angewendet, damit der Filter erhalten bleibt."""
    courses = Courses.upcoming_courses.upcoming()
    filter_type = request.GET.get('filter', '')
    if filter_type in _CATEGORY_FILTERS:
        courses = courses.filter(category__name=_CATEGORY_FILTERS[filter_type])
    elif filter_type == 'my_courses' and request.user.is_authenticated:
        courses = courses.filter(bookings__user=request.user)
    return courses


def _render_course_list(request, **extra):
    context = _decorate(_filtered_courses(request), request.user)
    context.update(extra)
    return render(request, 'partials/course_list.html', context)


def _course_from_request(request):
    course_id = request.GET.get('course')
    return Courses.objects.filter(pk=course_id).first() if course_id else None


class CourseListView(ListView):
    model = Courses
    template_name = 'course/courses.html'
    context_object_name = 'courses'

    def get_queryset(self):
        # Use the custom manager to get upcoming courses
        return Courses.upcoming_courses.upcoming()  # Get courses with date >= today

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context.update(_decorate(self.get_queryset(), self.request.user))
        return context


def filter_courses(request):
    return _render_course_list(request)


_BOOKING_ERRORS = {
    BookingResult.CANCELLED: "Dieser Kurs wurde abgesagt und kann nicht gebucht werden.",
    BookingResult.FULL: "Der Kurs ist bereits ausgebucht. Trag Dich doch auf die Warteliste ein.",
    BookingResult.NO_CREDITS: "Du hast nicht genügend Credits.",
    BookingResult.ALREADY_BOOKED: "Du bist für diesen Kurs bereits angemeldet.",
}


def create_booking(request):
    course = _course_from_request(request)
    conflict = None
    if course and request.user.is_authenticated:
        release = request.GET.get('release')
        result, detail = book(request.user, course.pk, release=release)
        if result is BookingResult.BOOKED:
            text = f"Buchung erfolgreich. Du hast {detail} Credit(s) übrig."
            left = WaitlistEntry.objects.filter(pk=release, user=request.user, status=WaitlistEntry.LEFT) \
                .select_related('course', 'course__category').first() if release else None
            if left:
                text += (f" Du wurdest von der Warteliste {left.course.category.name} - "
                         f"{left.course.name} entfernt.")
            messages.success(request, text)
        elif result is BookingResult.WAITLIST_CONFLICT:
            conflict = {'course': course, 'entries': detail}
        else:
            messages.error(request, _BOOKING_ERRORS[result])
    return _render_course_list(request, booking_conflict=conflict)


def cancel_booking(request):
    course = _course_from_request(request)
    if course is None:
        raise Http404
    booking = Booking.objects.filter(user=request.user, course=course).first() \
        if request.user.is_authenticated else None

    if booking:
        credits, _ = Credits.objects.get_or_create(user=request.user, defaults={'number': 0})

        # Credit zurueck nur bis 24 h vor Kursbeginn (Schweizer Zeit)
        if cancellation_refundable(course):
            # Add credit back to user's balance
            credits.number += 1  # Assuming each booking gives 1 credit
            credits.save()
            booking.delete()
            messages.success(request, f"Du wurdest erfolgreich abgemeldet. Du hast {credits.number} Credit(s) übrig.")
        else:
            # Delete the booking without adding credit
            booking.delete()
            messages.success(request, "Du wurdest erfolgreich abgemeldet. Die Abmeldefrist wurde nicht "
                                      f"eingehalten. Du hast {credits.number} Credit(s) übrig.")

        # Platz wieder freigeben; loest die Warteliste aus (course.waitlist)
        course.capacity += 1
        course.save()
    else:
        # Handle case where no booking exists
        messages.error(request, "Es wurde keine Buchung gefunden.")

    return _render_course_list(request)


def join_waitlist(request):
    course = _course_from_request(request)
    if course and request.user.is_authenticated:
        try:
            waitlist.join(request.user, course)
            messages.success(request, "Du bist auf der Warteliste. Sobald ein Platz frei wird, "
                                      "bekommst Du eine E-Mail.")
        except WaitlistError as e:
            messages.error(request, str(e))
    return _render_course_list(request)


def leave_waitlist(request):
    course = _course_from_request(request)
    if course and request.user.is_authenticated:
        if waitlist.leave(request.user, course):
            messages.success(request, "Du wurdest von der Warteliste ausgetragen.")
        else:
            messages.error(request, "Du stehst nicht auf der Warteliste dieses Kurses.")
    return _render_course_list(request)


def claim_waitlist_seat(request, token):
    """Landeseite des Buttons "Jetzt einschreiben" in der Platz-frei-Mail.

    GET zeigt nur die Seite; gebucht wird erst per POST (Button), weil
    Mail-Scanner Links in E-Mails automatisch aufrufen. Kein Login noetig:
    der signierte Link ist persoenlich.
    """
    entry = waitlist.entry_from_token(token)
    if entry is None:
        return render(request, 'course/waitlist_claim.html', {'invalid': True}, status=404)

    course = entry.course
    if request.method == 'POST':
        result = waitlist.claim(entry)
    elif Booking.objects.filter(user=entry.user, course=course).exists():
        result = ClaimResult.ALREADY_BOOKED
    elif course.is_cancelled:
        result = ClaimResult.COURSE_CANCELLED
    elif waitlist.has_started(course):
        result = ClaimResult.COURSE_STARTED
    else:
        result = None  # Button anzeigen

    credits = Credits.objects.filter(user=entry.user).values_list('number', flat=True).first() or 0
    return render(request, 'course/waitlist_claim.html', {
        'entry': entry,
        'course': course,
        'course_date': course.date.strftime('%d.%m.%Y'),
        'course_time': course.start.strftime('%H:%M'),
        'result': result.value if result else None,
        'credits': credits,
    })

def show_attendees(request):
    course_id = request.GET.get('course_id')
    
    # Get the specific course by primary key (or return 404 if not found)
    course = get_object_or_404(Courses, pk=course_id)
    
    # Get all users who have a booking for this course
    attendees = User.objects.filter(booking__course=course)
    
    context =  {'attendees': attendees}
    
    return render(request, 'partials/course_attendees.html', context)

def send_course_reminder(request):
    ''' Send a list of course participants to the course instructor '''
    # Get the current date
    today = timezone.now().date()
    
    # Find courses that are scheduled for later today
    courses_today = Courses.objects.filter(date=today, is_cancelled=False)
    
    if not courses_today.exists():
        return HttpResponse('Es findet heute kein Kurs statt.')
    
    # Prepare email content
    for course in courses_today:
        bookings = Booking.objects.filter(course=course)
        
        if bookings.exists():
            participant_list = [booking.user.get_full_name() or booking.user.username for booking in bookings]
            
            # Render HTML template
            html_message = render_to_string('course/course_reminder.html', {
                'course': course,
                'participants': participant_list
            })
            
            # Send email
            send_mail(
                subject=f'Teilnehmerliste für den Kurs: {course.name}',
                message='',
                html_message=html_message,
                from_email='admin@mileja.ch',
                recipient_list=['hebammen@mileja.ch', 'admin@mileja.ch'],
                fail_silently=False,
            )
        else:
            # If no bookings, send an email informing about it
            send_mail(
                subject=f'Keine Buchungen für den Kurs: {course.name}',
                message=f'Der Kurs "{course.name}" findet heute um {course.start} statt, jedoch sind keine Teilnehmer angemeldet.',
                from_email='admin@mileja.ch',
                recipient_list=['hebammen@mileja.ch', 'admin@mileja.ch'],
                fail_silently=False,
            )
    
    return HttpResponse('Teilnehmerliste wurde erfolgreich versendet.')

def confirm_cancellation_receipt(request, token):
    ''' Landeseite des "Erhalt bestaetigen"-Buttons in der Absage-Mail.

    GET zeigt nur die Seite; bestaetigt wird erst per POST (Button), weil
    Mail-Scanner Links in E-Mails automatisch aufrufen.
    '''
    notice = notice_from_token(token)
    if notice is None:
        return render(request, 'course/cancellation_confirm.html', {'invalid': True}, status=404)

    if request.method == 'POST':
        confirm_receipt(notice)
        notice.refresh_from_db(fields=['confirmed_at'])

    return render(request, 'course/cancellation_confirm.html', {
        'notice': notice,
        'course_date': notice.course.date.strftime('%d.%m.%Y'),
        'course_time': notice.course.start.strftime('%H:%M'),
    })

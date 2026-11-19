"""Einen Platz buchen: gemeinsamer Kern von Kursliste ("Buchen") und Warteliste
("Platz jetzt sichern"), damit beide Wege dieselben Regeln und dieselbe Sperre
gegen den Wettlauf um den letzten Platz nutzen.
"""
import enum
from datetime import datetime, timedelta

from django.db import transaction
from django.utils import timezone

from users.models import Credits
from .cancellation import SWISS_TZ
from .models import Booking, Courses, WaitlistEntry

# Abmeldung mit Credit-Rueckgabe nur bis so lange vor Kursbeginn
REFUND_DEADLINE = timedelta(hours=24)


def course_start(course):
    """Kursbeginn als aware datetime. Datum/Zeit im Admin sind Schweizer
    Ortszeit; die App selbst laeuft in UTC."""
    return datetime.combine(course.date, course.start).replace(tzinfo=SWISS_TZ)


def active_waitlists(user):
    """Wartende Eintraege der Kundin fuer kommende, nicht abgesagte Kurse.
    Pro Eintrag ist 1 Credit reserviert. (Eintraege vergangener Kurse bleiben
    'waiting' stehen und zaehlen nicht.)"""
    return WaitlistEntry.objects.filter(
        user=user, status=WaitlistEntry.WAITING, course__is_cancelled=False,
        course__date__gte=timezone.localdate(timezone=SWISS_TZ))


def cancellation_refundable(course, now=None):
    """True, wenn bei einer Abmeldung jetzt der Credit zurueckkommt."""
    return course_start(course) - (now or timezone.now()) > REFUND_DEADLINE


class BookingResult(enum.Enum):
    BOOKED = 'booked'
    ALREADY_BOOKED = 'already_booked'
    CANCELLED = 'cancelled'
    FULL = 'full'
    NO_CREDITS = 'no_credits'
    # Der einzige freie Credit ist fuer eine Warteliste reserviert
    WAITLIST_CONFLICT = 'waitlist_conflict'


def book_locked(user, course):
    """Bucht ``user`` in ``course``. Aufrufer haelt ``course`` per
    ``select_for_update`` in einer Transaktion gesperrt.

    Rueckgabe: (BookingResult, verbleibende Credits oder None).
    """
    if Booking.objects.filter(user=user, course=course).exists():
        return BookingResult.ALREADY_BOOKED, None
    if course.is_cancelled:
        return BookingResult.CANCELLED, None
    if course.capacity <= 0:
        return BookingResult.FULL, None
    credits = Credits.objects.select_for_update().filter(user=user).first()
    if credits is None or credits.number < 1:
        return BookingResult.NO_CREDITS, None

    credits.number -= 1
    credits.save(update_fields=['number'])
    Booking.objects.create(user=user, course=course)
    course.capacity -= 1
    course.save(update_fields=['capacity'])
    # Wer bucht, ist nicht mehr auf der Warteliste
    WaitlistEntry.objects.filter(course=course, user=user, status=WaitlistEntry.WAITING).update(
        status=WaitlistEntry.BOOKED, booked_at=timezone.now())
    return BookingResult.BOOKED, credits.number


def book(user, course_id, release=None):
    """Buchung aus der Kursliste (atomar, Kurs und Credits gesperrt).

    Bleibt nach der Buchung kein Credit fuer die Wartelisten der Kundin uebrig,
    wird nicht gebucht: Rueckgabe (WAITLIST_CONFLICT, [blockierende Eintraege]).
    ``release`` = Wartelisten-Eintrag, den die Kundin dafuer aufgibt; er wird
    nur aufgehoben, wenn die Buchung danach tatsaechlich klappt.
    Sonst wie ``book_locked``: (BookingResult, verbleibende Credits oder None).
    """
    with transaction.atomic():
        course = Courses.objects.select_for_update().get(pk=course_id)
        credits = (Credits.objects.select_for_update().filter(user=user)
                   .values_list('number', flat=True).first() or 0)
        bookable = (credits >= 1 and course.capacity > 0 and not course.is_cancelled
                    and not Booking.objects.filter(user=user, course=course).exists())
        if bookable:
            # die Warteliste des gebuchten Kurses selbst blockiert nicht
            blocking = list(active_waitlists(user).exclude(course=course)
                            .select_related('course', 'course__category').order_by('course__date'))
            released = [e for e in blocking if release is not None and str(e.pk) == str(release)]
            if credits - (len(blocking) - len(released)) < 1:
                return BookingResult.WAITLIST_CONFLICT, blocking
        else:
            released = []

        result, credits_left = book_locked(user, course)
        if result is BookingResult.BOOKED and released:
            WaitlistEntry.objects.filter(pk=released[0].pk).update(status=WaitlistEntry.LEFT)
        return result, credits_left

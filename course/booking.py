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


def cancellation_refundable(course, now=None):
    """True, wenn bei einer Abmeldung jetzt der Credit zurueckkommt."""
    return course_start(course) - (now or timezone.now()) > REFUND_DEADLINE


class BookingResult(enum.Enum):
    BOOKED = 'booked'
    ALREADY_BOOKED = 'already_booked'
    CANCELLED = 'cancelled'
    FULL = 'full'
    NO_CREDITS = 'no_credits'


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


def book(user, course_id):
    """Buchung aus der Kursliste (atomar, Kurs gesperrt)."""
    with transaction.atomic():
        course = Courses.objects.select_for_update().get(pk=course_id)
        return book_locked(user, course)

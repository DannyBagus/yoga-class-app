"""Warteliste fuer ausgebuchte Kurse.

- Kundinnen tragen sich auf ausgebuchten Kursen ein (mind. 1 Credit noetig).
- Steigt ``Courses.capacity`` (Abmeldung, Storno, Umbuchung, Admin erhoeht
  die Plaetze), bekommen nach dem Commit alle Wartenden eine zweisprachige
  Mail mit persoenlichem Link (siehe Signal-Handler unten). Das feuert bei
  jeder Erhoehung neu, also auch mehrmals pro Kurs.
- Der Link fuehrt auf eine Zwischenseite; erst deren POST bucht (Schutz vor
  Mail-Scannern). First come, first serve ueber die Kurs-Sperre in
  ``booking.book_locked``.
- Bei einer Kursabsage werden die Eintraege geschlossen und die Wartenden
  kurz informiert (aufgerufen aus ``cancellation.cancel_course``).
"""
import enum
import logging
from datetime import datetime

from django.conf import settings
from django.core import signing
from django.db import transaction
from django.db.models import F
from django.db.models.signals import post_save, pre_save
from django.dispatch import receiver
from django.utils import timezone

from users.models import Credits
from .booking import BookingResult, book_locked
from .cancellation import CUSTOMER_REPLY_TO, SWISS_TZ, _send_mail
from .models import Booking, Courses, WaitlistEntry

logger = logging.getLogger(__name__)

CLAIM_SALT = 'course.waitlist.claim'
CLAIM_MAX_AGE = 60 * 60 * 24 * 60  # 60 Tage; danach ist der Kurs ohnehin vorbei


class WaitlistError(Exception):
    """Eintragen nicht moeglich; die Meldung wird der Kundin angezeigt."""


class ClaimResult(enum.Enum):
    SUCCESS = 'success'
    TOO_LATE = 'too_late'
    NO_CREDITS = 'no_credits'
    ALREADY_BOOKED = 'already_booked'
    COURSE_CANCELLED = 'course_cancelled'
    COURSE_STARTED = 'course_started'
    NOT_WAITING = 'not_waiting'


_CLAIM_RESULTS = {
    BookingResult.BOOKED: ClaimResult.SUCCESS,
    BookingResult.FULL: ClaimResult.TOO_LATE,
    BookingResult.NO_CREDITS: ClaimResult.NO_CREDITS,
    BookingResult.ALREADY_BOOKED: ClaimResult.ALREADY_BOOKED,
    BookingResult.CANCELLED: ClaimResult.COURSE_CANCELLED,
}


def has_started(course):
    """Kurszeiten sind Schweizer Ortszeit (die App selbst laeuft in UTC)."""
    start = datetime.combine(course.date, course.start).replace(tzinfo=SWISS_TZ)
    return timezone.now() >= start


def waiting_count(course):
    return course.waitlist_entries.filter(status=WaitlistEntry.WAITING).count()


# --- Eintragen / Austragen --------------------------------------------------

def join(user, course):
    """Traegt ``user`` auf die Warteliste ein (idempotent) oder wirft WaitlistError."""
    with transaction.atomic():
        course = Courses.objects.select_for_update().get(pk=course.pk)
        if Booking.objects.filter(user=user, course=course).exists():
            raise WaitlistError("Du bist für diesen Kurs bereits angemeldet.")
        if course.is_cancelled:
            raise WaitlistError("Dieser Kurs wurde abgesagt.")
        if has_started(course):
            raise WaitlistError("Dieser Kurs hat bereits begonnen.")
        if course.capacity > 0:
            raise WaitlistError("Im Kurs sind noch Plätze frei – Du kannst direkt buchen.")
        credits = Credits.objects.filter(user=user).values_list('number', flat=True).first() or 0
        if credits < 1:
            raise WaitlistError("Für die Warteliste brauchst Du mindestens 1 Credit.")

        entry, created = WaitlistEntry.objects.get_or_create(course=course, user=user)
        if not created and entry.status != WaitlistEntry.WAITING:
            entry.status = WaitlistEntry.WAITING
            entry.created_at = timezone.now()
            entry.save(update_fields=['status', 'created_at'])
        return entry


def leave(user, course):
    """Austragen; True, wenn die Kundin auf der Warteliste stand."""
    return bool(WaitlistEntry.objects
                .filter(course=course, user=user, status=WaitlistEntry.WAITING)
                .update(status=WaitlistEntry.LEFT))


# --- Platz frei: Ausloeser und Mail -----------------------------------------

@receiver(pre_save, sender=Courses)
def _remember_capacity(sender, instance, raw=False, **kwargs):
    instance._capacity_before = None
    if not raw and instance.pk is not None:
        instance._capacity_before = (Courses.objects.filter(pk=instance.pk)
                                     .values_list('capacity', flat=True).first())


@receiver(post_save, sender=Courses)
def _capacity_increased(sender, instance, created, raw=False, **kwargs):
    before = getattr(instance, '_capacity_before', None)
    if raw or created or before is None or instance.capacity <= before:
        return
    course_id = instance.pk
    # Erst nach dem Commit: bei einem Rollback wurde kein Platz frei.
    transaction.on_commit(lambda: notify_seat_freed(course_id))


def notify_seat_freed(course_id):
    """Mail an alle Wartenden. Gibt die Anzahl versendeter Mails zurueck.

    Laeuft nach dem Commit einer Abmeldung o. ae.; darf darum nie eine
    Exception werfen, sonst saehe die Kundin trotz erfolgreicher Abmeldung
    einen Fehler.
    """
    try:
        course = Courses.objects.select_related('category').get(pk=course_id)
        if course.is_cancelled or course.capacity <= 0 or has_started(course):
            return 0
        entries = list(course.waitlist_entries
                       .filter(status=WaitlistEntry.WAITING).select_related('user'))
    except Exception:
        logger.exception('Warteliste: Kurs %s konnte nicht geladen werden', course_id)
        return 0

    sent = 0
    for entry in entries:
        if not entry.user.email:
            logger.warning('Warteliste: %s hat keine E-Mail (Kurs %s)', entry.user, course_id)
            continue
        try:
            _send_seat_freed_mail(course, entry)
        except Exception:
            logger.exception('Platz-frei-Mail an %s fehlgeschlagen (Kurs %s)', entry.user.email, course_id)
            continue
        WaitlistEntry.objects.filter(pk=entry.pk).update(
            notified_count=F('notified_count') + 1, last_notified_at=timezone.now())
        sent += 1
    logger.info('Warteliste: Kurs %s, %s Platz-frei-Mail(s) versendet', course_id, sent)
    return sent


def _mail_context(course, **extra):
    return {
        'course': course,
        'course_date': course.date.strftime('%d.%m.%Y'),
        'course_time': course.start.strftime('%H:%M'),
        'courses_url': f"{settings.SITE_URL.rstrip('/')}/kurse/",
        **extra,
    }


def _send_seat_freed_mail(course, entry):
    ctx = _mail_context(course, claim_url=claim_url(entry))
    _send_mail(
        f'Platz frei / Spot available: {course.category.name} - {course.name}, '
        f'{ctx["course_date"]} {ctx["course_time"]}',
        'course/emails/waitlist_seat_freed', ctx, [entry.user.email], reply_to=CUSTOMER_REPLY_TO,
    )


# --- Platz sichern (Link aus der Mail) --------------------------------------

def claim_url(entry):
    token = signing.dumps(entry.pk, salt=CLAIM_SALT)
    return f"{settings.SITE_URL.rstrip('/')}/kurse/warteliste/{token}/"


def entry_from_token(token):
    try:
        pk = signing.loads(token, salt=CLAIM_SALT, max_age=CLAIM_MAX_AGE)
    except signing.BadSignature:  # inkl. SignatureExpired
        return None
    return (WaitlistEntry.objects.select_related('user', 'course', 'course__category')
            .filter(pk=pk).first())


def claim(entry):
    """Bucht den frei gewordenen Platz, falls die Kundin die Erste ist."""
    with transaction.atomic():
        course = Courses.objects.select_for_update().get(pk=entry.course_id)
        entry = WaitlistEntry.objects.select_for_update().select_related('user').get(pk=entry.pk)
        if Booking.objects.filter(user=entry.user, course=course).exists():
            return ClaimResult.ALREADY_BOOKED
        if course.is_cancelled:
            return ClaimResult.COURSE_CANCELLED
        if has_started(course):
            return ClaimResult.COURSE_STARTED
        if entry.status != WaitlistEntry.WAITING:
            return ClaimResult.NOT_WAITING
        result, _ = book_locked(entry.user, course)
    return _CLAIM_RESULTS[result]


# --- Kursabsage -------------------------------------------------------------

def close_waitlist(course):
    """In der Absage-Transaktion: Wartende schliessen, Liste fuer die Info-Mail."""
    entries = list(course.waitlist_entries
                   .filter(status=WaitlistEntry.WAITING).select_related('user'))
    course.waitlist_entries.filter(pk__in=[e.pk for e in entries]).update(
        status=WaitlistEntry.COURSE_CANCELLED)
    return entries


def notify_course_cancelled(course, entries):
    """Nach dem Commit der Absage: kurze Info an die ehemals Wartenden."""
    sent = 0
    ctx = _mail_context(course)
    for entry in entries:
        if not entry.user.email:
            continue
        try:
            _send_mail(
                f'Kurs abgesagt / Course cancelled: {course.category.name} - {course.name}, '
                f'{ctx["course_date"]}',
                'course/emails/waitlist_course_cancelled', ctx, [entry.user.email],
                reply_to=CUSTOMER_REPLY_TO,
            )
            sent += 1
        except Exception:
            logger.exception('Warteliste-Absage-Mail an %s fehlgeschlagen (Kurs %s)',
                             entry.user.email, course.pk)
    return sent

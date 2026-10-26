"""Kurs absagen: Buchungen stornieren, Credits gutschreiben, Kundinnen informieren.

Wird vom "Kurs absagen"-Button im Admin aufgerufen (siehe CourseAdmin).
"""
import logging
from dataclasses import dataclass, field

from django.core.mail import send_mail
from django.db import transaction
from django.template.loader import render_to_string
from django.utils import timezone

from users.models import Credits
from .models import Courses

logger = logging.getLogger(__name__)


class CourseAlreadyCancelled(Exception):
    pass


@dataclass
class CancellationResult:
    # (user, credits_vorher, credits_nachher) je stornierter Buchung
    refunds: list = field(default_factory=list)
    mails_sent: int = 0
    mail_failures: list = field(default_factory=list)


def cancel_course(course_id):
    """Sagt den Kurs ab. Atomar: entweder alles (Absage, Stornos, Gutschriften) oder nichts.

    Gutgeschrieben wird immer 1 Credit pro Buchung, unabhaengig von der
    24h-Abmeldefrist, weil die Absage von uns kommt. E-Mails gehen erst nach
    dem Commit raus; ein Mailfehler macht die Absage nicht rueckgaengig.
    """
    result = CancellationResult()
    with transaction.atomic():
        # Sperre gegen Doppelklick/parallele Absage.
        course = Courses.objects.select_for_update().select_related('category').get(pk=course_id)
        if course.is_cancelled:
            raise CourseAlreadyCancelled(course)

        bookings = list(course.bookings.select_related('user'))
        for booking in bookings:
            credits, _ = Credits.objects.select_for_update().get_or_create(
                user=booking.user, defaults={'number': 0})
            before = credits.number
            credits.number += 1
            credits.save(update_fields=['number'])
            result.refunds.append((booking.user, before, credits.number))
            booking.delete()

        course.capacity += len(bookings)  # Plaetze wieder freigeben (Live-Zaehler)
        course.is_cancelled = True
        course.cancelled_at = timezone.now()
        course.save(update_fields=['capacity', 'is_cancelled', 'cancelled_at'])

    for user, _, credits_after in result.refunds:
        if not user.email:
            result.mail_failures.append(user)
            continue
        try:
            _send_cancellation_mail(course, user, credits_after)
            result.mails_sent += 1
        except Exception:
            logger.exception('Absage-Mail an %s fehlgeschlagen (Kurs %s)', user.email, course.pk)
            result.mail_failures.append(user)
    return result


def _send_cancellation_mail(course, user, credits_after):
    context = {
        'user': user,
        'course': course,
        'course_date': course.date.strftime('%d.%m.%Y'),
        'course_time': course.start.strftime('%H:%M'),
        'credits': credits_after,
    }
    send_mail(
        f'Kursabsage: {course.category.name} - {course.name} am {context["course_date"]}',
        render_to_string('course/emails/course_cancelled.txt', context),
        'admin@mileja.ch',
        [user.email],
        fail_silently=False,
        html_message=render_to_string('course/emails/course_cancelled.html', context),
    )

"""Kurs absagen: Buchungen stornieren, Credits gutschreiben, Kundinnen informieren.

Wird vom "Kurs absagen"-Button im Admin aufgerufen (siehe CourseAdmin).
"""
import logging
from dataclasses import dataclass, field

from django.core.mail import EmailMultiAlternatives
from django.db import transaction
from django.template.loader import render_to_string
from django.utils import timezone

try:
    from zoneinfo import ZoneInfo
except ImportError:  # Python 3.8 (Docker-Image)
    from backports.zoneinfo import ZoneInfo

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
    summary_sent: bool = False


SUMMARY_RECIPIENTS = ['hebammen@mileja.ch']
# Bestaetigungen der Kundinnen ("Antworten") landen beim Team, nicht bei admin@.
CUSTOMER_REPLY_TO = ['hebammen@mileja.ch']
FROM_EMAIL = 'admin@mileja.ch'
# App laeuft in UTC; die Zusammenfassung zeigt Schweizer Zeit.
SWISS_TZ = ZoneInfo('Europe/Zurich')


def cancel_course(course_id, cancelled_by=None):
    """Sagt den Kurs ab. Atomar: entweder alles (Absage, Stornos, Gutschriften) oder nichts.

    Gutgeschrieben wird immer 1 Credit pro Buchung, unabhaengig von der
    24h-Abmeldefrist, weil die Absage von uns kommt. E-Mails gehen erst nach
    dem Commit raus; ein Mailfehler macht die Absage nicht rueckgaengig.
    Zum Schluss geht eine Zusammenfassung an SUMMARY_RECIPIENTS, weil per
    SMTP versendete Mails in keinem Gesendet-Ordner landen.
    """
    result = CancellationResult()
    with transaction.atomic():
        # Sperre gegen Doppelklick/parallele Absage.
        course = Courses.objects.select_for_update().select_related('category').get(pk=course_id)
        if course.is_cancelled:
            raise CourseAlreadyCancelled(course)

        bookings = list(course.bookings.select_related('user', 'user__profile'))
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

    try:
        _send_summary_mail(course, result, cancelled_by)
        result.summary_sent = True
    except Exception:
        logger.exception('Absage-Zusammenfassung fehlgeschlagen (Kurs %s)', course.pk)
    return result


def _send_cancellation_mail(course, user, credits_after):
    context = {
        'user': user,
        'course': course,
        'course_date': course.date.strftime('%d.%m.%Y'),
        'course_time': course.start.strftime('%H:%M'),
        'credits': credits_after,
    }
    _send_mail(
        f'Kursabsage: {course.category.name} - {course.name} am {context["course_date"]}',
        'course/emails/course_cancelled', context, [user.email], reply_to=CUSTOMER_REPLY_TO,
    )


def _send_summary_mail(course, result, cancelled_by):
    failed = {u.pk for u in result.mail_failures}
    participants = []
    for user, before, after in result.refunds:
        profile = getattr(user, 'profile', None)
        participants.append({
            'name': f"{user.first_name} {user.last_name}".strip() or user.username,
            'email': user.email,
            'phone': profile.phone if profile else '',
            'credits_before': before,
            'credits_after': after,
            'mail_ok': user.pk not in failed,
        })
    by = ''
    if cancelled_by is not None:
        by = f"{cancelled_by.first_name} {cancelled_by.last_name}".strip() or cancelled_by.username
    context = {
        'course': course,
        'course_date': course.date.strftime('%d.%m.%Y'),
        'course_time': course.start.strftime('%H:%M'),
        'cancelled_at': timezone.localtime(course.cancelled_at, SWISS_TZ).strftime('%d.%m.%Y %H:%M'),
        'cancelled_by': by,
        'participants': participants,
        'mails_sent': result.mails_sent,
        'mail_failures': len(result.mail_failures),
    }
    _send_mail(
        f'Kurs abgesagt: {course.category.name} - {course.name} am {context["course_date"]} '
        f'({len(participants)} Buchung(en) storniert)',
        'course/emails/course_cancelled_summary', context, SUMMARY_RECIPIENTS,
    )


def _send_mail(subject, template, context, to, reply_to=None):
    """Text- + HTML-Mail aus ``<template>.txt``/``.html``."""
    msg = EmailMultiAlternatives(
        subject, render_to_string(f'{template}.txt', context), FROM_EMAIL, to, reply_to=reply_to)
    msg.attach_alternative(render_to_string(f'{template}.html', context), 'text/html')
    msg.send(fail_silently=False)

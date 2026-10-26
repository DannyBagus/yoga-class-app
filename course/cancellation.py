"""Kurs absagen: Buchungen stornieren, Credits gutschreiben, Kundinnen informieren.

Wird vom "Kurs absagen"-Button im Admin aufgerufen (siehe CourseAdmin).
"""
import logging
from dataclasses import dataclass, field

from django.conf import settings
from django.core import signing
from django.core.mail import EmailMultiAlternatives
from django.db import transaction
from django.template.loader import render_to_string
from django.utils import timezone

try:
    from zoneinfo import ZoneInfo
except ImportError:  # Python 3.8 (Docker-Image)
    from backports.zoneinfo import ZoneInfo

from users.models import Credits
from .models import CancellationNotice, Courses

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
    # user_pk -> CancellationNotice
    notices: dict = field(default_factory=dict)


SUMMARY_RECIPIENTS = ['hebammen@mileja.ch']
# Bestaetigungen der Kundinnen ("Antworten") landen beim Team, nicht bei admin@.
CUSTOMER_REPLY_TO = ['hebammen@mileja.ch']
FROM_EMAIL = 'admin@mileja.ch'
# App laeuft in UTC; die Zusammenfassung zeigt Schweizer Zeit.
SWISS_TZ = ZoneInfo('Europe/Zurich')
# Signierter Token im "Erhalt bestaetigen"-Link der Absage-Mail
CONFIRM_SALT = 'course.cancellation.confirm'
CONFIRM_MAX_AGE = 60 * 60 * 24 * 60  # 60 Tage


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
            result.notices[booking.user.pk] = CancellationNotice.objects.create(
                course=course, user=booking.user,
                credits_before=before, credits_after=credits.number)
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
            notice = result.notices[user.pk]
            _send_cancellation_mail(course, user, credits_after, confirm_url(notice))
            notice.mail_sent = True
            notice.save(update_fields=['mail_sent'])
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


def confirm_url(notice):
    token = signing.dumps(notice.pk, salt=CONFIRM_SALT)
    return f"{settings.SITE_URL.rstrip('/')}/kurse/absage/{token}/"


def notice_from_token(token):
    """CancellationNotice zum Token aus der Absage-Mail, sonst None."""
    try:
        pk = signing.loads(token, salt=CONFIRM_SALT, max_age=CONFIRM_MAX_AGE)
    except signing.BadSignature:  # inkl. SignatureExpired
        return None
    return (CancellationNotice.objects
            .select_related('user', 'user__profile', 'course', 'course__category')
            .filter(pk=pk).first())


def confirm_receipt(notice):
    """Bestaetigt den Erhalt (idempotent). True nur beim ersten Mal; dann Mail ans Team."""
    now = timezone.now()
    updated = CancellationNotice.objects.filter(pk=notice.pk, confirmed_at__isnull=True).update(confirmed_at=now)
    if not updated:
        return False
    notice.confirmed_at = now
    try:
        _send_confirmation_mail(notice)
    except Exception:
        # Bestaetigung bleibt gespeichert und ist im Admin sichtbar.
        logger.exception('Bestaetigungs-Mail fehlgeschlagen (Notice %s)', notice.pk)
    return True


def _send_confirmation_mail(notice):
    course, user = notice.course, notice.user
    profile = getattr(user, 'profile', None)
    context = {
        'name': f"{user.first_name} {user.last_name}".strip() or user.username,
        'email': user.email,
        'phone': profile.phone if profile else '',
        'course': course,
        'course_date': course.date.strftime('%d.%m.%Y'),
        'course_time': course.start.strftime('%H:%M'),
        'confirmed_at': timezone.localtime(notice.confirmed_at, SWISS_TZ).strftime('%d.%m.%Y %H:%M'),
        'open': CancellationNotice.objects.filter(course=course, confirmed_at__isnull=True).count(),
    }
    _send_mail(
        f'Erhalt bestätigt: {context["name"]} - {course.category.name} - {course.name} am {context["course_date"]}',
        'course/emails/course_cancelled_confirmed', context, SUMMARY_RECIPIENTS,
        reply_to=[user.email] if user.email else None,
    )


def _send_cancellation_mail(course, user, credits_after, confirm_link):
    context = {
        'confirm_url': confirm_link,
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

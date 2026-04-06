import logging

import stripe
from django.conf import settings
from django.contrib.auth.decorators import login_required
from django.db import transaction as db_transaction
from django.http import HttpResponse
from django.shortcuts import redirect, render
from django.template.loader import render_to_string
from django.core.mail import EmailMultiAlternatives
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_POST

from users.models import Credits, PurchaseTransaction

stripe.api_key = settings.STRIPE_SECRET_KEY
logger = logging.getLogger(__name__)

# Mapping: credit count -> settings attribute name
CREDIT_PACKAGES = {
    1: 'STRIPE_PRICE_1_CREDIT',
    5: 'STRIPE_PRICE_5_CREDITS',
    10: 'STRIPE_PRICE_10_CREDITS',
}


@login_required
@require_POST
def create_checkout_session(request):
    """Erstellt eine Stripe Checkout Session fuer den Credit-Kauf."""
    try:
        number = int(request.POST.get('number', 0))
    except (TypeError, ValueError):
        return redirect('my-account')

    if number not in CREDIT_PACKAGES:
        return redirect('my-account')

    price_id = getattr(settings, CREDIT_PACKAGES[number])

    transaction = PurchaseTransaction.objects.create(
        user=request.user,
        number=number,
    )

    session = stripe.checkout.Session.create(
        automatic_payment_methods={'enabled': True},
        line_items=[{'price': price_id, 'quantity': 1}],
        mode='payment',
        success_url=request.build_absolute_uri('/users/checkout/success/') + '?session_id={CHECKOUT_SESSION_ID}',
        cancel_url=request.build_absolute_uri('/users/checkout/cancel/'),
        customer_email=request.user.email,
        metadata={
            'user_id': str(request.user.id),
            'transaction_id': str(transaction.id),
            'credits': str(number),
        },
    )

    transaction.stripe_checkout_session_id = session.id
    transaction.save(update_fields=['stripe_checkout_session_id'])

    return redirect(session.url)


@login_required
def checkout_success(request):
    """Verifiziert die Stripe Session und schreibt Credits sofort gut."""
    session_id = request.GET.get('session_id')
    credits_added = 0

    if session_id and session_id.startswith('cs_'):
        try:
            session = stripe.checkout.Session.retrieve(session_id)
            if session.payment_status == 'paid':
                transaction_id = session.metadata.get('transaction_id')
                credits_added = _finalize_transaction(
                    transaction_id,
                    session.payment_intent or '',
                )
                if credits_added:
                    user = PurchaseTransaction.objects.get(id=transaction_id).user
                    _send_purchase_emails(
                        user,
                        PurchaseTransaction.objects.get(id=transaction_id),
                    )
        except Exception:
            logger.exception('Fehler bei Checkout-Verifizierung: %s', session_id)

    credits_obj, _ = Credits.objects.get_or_create(user=request.user)

    return render(request, 'users/checkout_success.html', {
        'credits_added': credits_added,
        'total_credits': credits_obj.number,
    })


@login_required
def checkout_cancel(request):
    """User hat den Checkout abgebrochen."""
    return render(request, 'users/checkout_cancel.html')


@csrf_exempt
@require_POST
def stripe_webhook(request):
    """Stripe Webhook als Backup-Mechanismus fuer die Gutschrift."""
    payload = request.body
    sig_header = request.META.get('HTTP_STRIPE_SIGNATURE', '')

    try:
        event = stripe.Webhook.construct_event(
            payload, sig_header, settings.STRIPE_WEBHOOK_SECRET,
        )
    except (ValueError, stripe.error.SignatureVerificationError):
        return HttpResponse(status=400)

    if event['type'] == 'checkout.session.completed':
        session = event['data']['object']
        _handle_checkout_completed(session)

    return HttpResponse(status=200)


def _handle_checkout_completed(session):
    """Webhook-Handler: Setzt Transaction auf final (falls noch pending)."""
    transaction_id = session.get('metadata', {}).get('transaction_id')
    if not transaction_id:
        return

    try:
        credits_added = _finalize_transaction(
            transaction_id,
            session.get('payment_intent', ''),
        )
        if credits_added:
            txn = PurchaseTransaction.objects.get(id=transaction_id)
            _send_purchase_emails(txn.user, txn)
    except PurchaseTransaction.DoesNotExist:
        logger.error('Transaction %s nicht gefunden (Webhook)', transaction_id)


def _finalize_transaction(transaction_id, payment_intent_id):
    """Atomar: pending -> final setzen. Gibt Anzahl Credits zurueck oder 0."""
    with db_transaction.atomic():
        try:
            txn = PurchaseTransaction.objects.select_for_update().get(
                id=transaction_id
            )
        except PurchaseTransaction.DoesNotExist:
            logger.error('Transaction %s nicht gefunden', transaction_id)
            return 0

        if txn.status != PurchaseTransaction.STATUS_PENDING:
            return 0

        txn.stripe_payment_intent_id = payment_intent_id
        txn.status = PurchaseTransaction.STATUS_FINAL
        txn.save(update_fields=['status', 'stripe_payment_intent_id'])
        return txn.number


def _send_purchase_emails(user, transaction):
    """Sendet Bestaetigungs-Email an User und Info-Email an Team."""
    site_url = 'https://kurse.mileja.ch'
    credits_obj, _ = Credits.objects.get_or_create(user=user)
    context = {
        'user': user,
        'transaction': transaction,
        'site_url': site_url,
        'total_credits': credits_obj.number,
    }

    # 1. Bestaetigung an User
    _send_html_email(
        template_name='emails/purchase_confirmation',
        context=context,
        subject=f'Deine {transaction.number} Yoga Credits sind bereit!',
        recipient_list=[user.email],
    )

    # 2. Info an Team
    _send_html_email(
        template_name='emails/purchase_notification',
        context=context,
        subject=f'Credit-Kauf: {user.first_name} {user.last_name} – {transaction.number} Credits',
        recipient_list=['hebammen@mileja.ch', 'info@mileja.ch', 'admin@mileja.ch'],
    )


def _send_html_email(template_name, context, subject, recipient_list):
    """Sendet HTML+Text Email. Fehler werden geloggt, nicht geworfen."""
    try:
        txt_body = render_to_string(f'{template_name}.txt', context)
        html_body = render_to_string(f'{template_name}.html', context)
        msg = EmailMultiAlternatives(
            subject=subject,
            body=txt_body,
            from_email=settings.DEFAULT_FROM_EMAIL,
            to=recipient_list,
        )
        msg.attach_alternative(html_body, 'text/html')
        msg.send()
    except Exception:
        logger.exception('Email-Versand fehlgeschlagen: "%s" an %s', subject, recipient_list)

"""
Merge duplicate users with the same email address.

For each group of users sharing an email (case-insensitive):
- Keep the user with the most credits (tiebreaker: highest id = newest)
- Transfer all bookings and purchase transactions to the primary user
- Sum up credits
- Delete duplicate users
Then add a unique index on LOWER(email) to prevent future duplicates.
"""

from django.db import migrations


def merge_duplicate_email_users(apps, schema_editor):
    User = apps.get_model('auth', 'User')
    Credits = apps.get_model('users', 'Credits')
    PurchaseTransaction = apps.get_model('users', 'PurchaseTransaction')
    Booking = apps.get_model('course', 'Booking')

    from django.db.models import Count
    from django.db.models.functions import Lower

    # Find emails that appear more than once (case-insensitive)
    dupes = (
        User.objects
        .annotate(lower_email=Lower('email'))
        .values('lower_email')
        .annotate(cnt=Count('id'))
        .filter(cnt__gt=1)
    )

    for entry in dupes:
        email_lower = entry['lower_email']
        if not email_lower:
            continue  # skip users without email

        users = list(
            User.objects
            .filter(email__iexact=email_lower)
            .order_by('id')
        )

        # Determine primary: most credits, then newest (highest id)
        def sort_key(u):
            try:
                credits = Credits.objects.get(user=u).number
            except Credits.DoesNotExist:
                credits = 0
            return (credits, u.id)

        users.sort(key=sort_key, reverse=True)
        primary = users[0]
        duplicates = users[1:]

        # Ensure primary has a Credits entry
        primary_credits, _ = Credits.objects.get_or_create(
            user=primary, defaults={'number': 0}
        )

        for dup in duplicates:
            # Sum credits
            try:
                dup_credits = Credits.objects.get(user=dup)
                primary_credits.number += dup_credits.number
            except Credits.DoesNotExist:
                pass

            # Transfer purchase transactions
            PurchaseTransaction.objects.filter(user=dup).update(user=primary)

            # Transfer bookings (skip if primary already has booking for same course)
            existing_course_ids = set(
                Booking.objects.filter(user=primary).values_list('course_id', flat=True)
            )
            for booking in Booking.objects.filter(user=dup):
                if booking.course_id not in existing_course_ids:
                    booking.user = primary
                    booking.save()
                else:
                    booking.delete()  # duplicate booking for same course

            # Delete the duplicate user (cascades Credits entry)
            dup.delete()

        primary_credits.save()


def reverse_noop(apps, schema_editor):
    pass  # cannot un-merge


class Migration(migrations.Migration):

    dependencies = [
        ('users', '0010_purchasetransaction_stripe_checkout_session_id_and_more'),
        ('course', '0011_alter_booking_course'),
    ]

    operations = [
        migrations.RunPython(merge_duplicate_email_users, reverse_noop),
        migrations.RunSQL(
            "CREATE UNIQUE INDEX unique_user_email ON auth_user (email);",
            reverse_sql="DROP INDEX unique_user_email ON auth_user;",
        ),
    ]

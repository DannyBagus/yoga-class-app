from django.db import models
from django.contrib.auth.models import User
from django.utils import timezone
from django.db.models.signals import post_save
from django.dispatch import receiver

class Credits(models.Model):
    user = models.OneToOneField(
        User, 
        on_delete=models.CASCADE
    )
    number = models.BigIntegerField(
        "Anzahl"
    )        

    class Meta:
        verbose_name_plural = ("Credits")

    def __str__(self):
        return f"{self.user.first_name} {self.user.last_name}: {self.number}"
    
# Signal to create a Credits entry when a new User is created
@receiver(post_save, sender=User)
def create_user_credits(sender, instance, created, **kwargs):
    if created:
        Credits.objects.create(user=instance, number=0)
        

class PurchaseTransaction(models.Model):
    date = models.DateField(
        verbose_name="Transaktionsdatum",
        default=timezone.now
    )
    user = models.ForeignKey(
        User, 
        on_delete=models.CASCADE
    )
    number = models.BigIntegerField(
        "Anzahl"
    )
    STATUS_PENDING = 'pending'
    STATUS_FINAL = 'final'

    STATUS_CHOICES = [
        (STATUS_PENDING, 'Pendent'),
        (STATUS_FINAL, 'Abgeschlossen'),
    ]
    status = models.CharField(
        max_length=10,
        choices=STATUS_CHOICES,
        default=STATUS_PENDING,
        verbose_name="Status"
    )
    stripe_checkout_session_id = models.CharField(
        max_length=200, blank=True, default='',
        verbose_name="Stripe Session ID"
    )
    stripe_payment_intent_id = models.CharField(
        max_length=200, blank=True, default='',
        verbose_name="Stripe Payment Intent"
    )

    class Meta:
        verbose_name = ("Kauftransaktion")
        verbose_name_plural = ("Kauftransaktionen")
        
    def __str__(self) -> str:
        return f"{self.date}: {self.user.first_name} {self.user.last_name} ({self.number} Credits) - {self.status.upper()}"
    
# Signal handler to update or create Credits entry when a PurchaseTransaction is saved
@receiver(post_save, sender=PurchaseTransaction)
def update_credits(sender, instance, created, **kwargs):
    if instance.status != PurchaseTransaction.STATUS_FINAL:
        return
    # Only credit on creation with status=final or when status field was explicitly updated
    update_fields = kwargs.get('update_fields')
    if not created and update_fields is not None and 'status' not in update_fields:
        return
    credits_obj, _ = Credits.objects.get_or_create(user=instance.user)
    credits_obj.number += instance.number
    credits_obj.save()
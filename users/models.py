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
        return f"{self.user}: {self.number}"
    
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

    class Meta:
        verbose_name = ("Kauftransaktion")
        verbose_name_plural = ("Kauftransaktionen")
        
    def __str__(self) -> str:
        return f"{self.date}: {self.user} ({self.number} Credits) - {self.status.upper()}"
    
# Signal handler to update or create Credits entry when a PurchaseTransaction is saved
@receiver(post_save, sender=PurchaseTransaction)
def update_credits(sender, instance, **kwargs):
    # Check if the transaction is marked as 'final'
    if instance.status == PurchaseTransaction.STATUS_FINAL:
        # Get or create the Credits entry for the user
        credits, created = Credits.objects.get_or_create(user=instance.user)

        # Increment the number of credits by the transaction amount
        credits.number += instance.number
        credits.save()
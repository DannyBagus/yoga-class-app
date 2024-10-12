from django.db import models
from django.utils import timezone
from django.contrib.auth.models import User

class Category(models.Model):
    name = models.CharField(max_length=100)
    
    class Meta:
        verbose_name = "Kategorie"
        verbose_name_plural = "Kategorien"
    
    def __str__(self) -> str:
        return f'{self.name}'

class Courses(models.Model):
    name = models.CharField(max_length=100)
    category = models.ForeignKey(
        Category,
        verbose_name='Kategorie',
        default=1,
        on_delete=models.CASCADE)
    topic = models.CharField(
        max_length=100,
        verbose_name="Thema")
    date = models.DateField(
        default=timezone.now,
        verbose_name="Datum")
    start = models.TimeField(
        default="18:00:00",
        verbose_name="Start Zeit")
    duration = models.IntegerField(
        verbose_name="Dauer",
        default=1)
    capacity = models.BigIntegerField(
        default=7,
        verbose_name="Anzahl Plätze")
    
    class Meta:
        ordering = ["date"]
        verbose_name = "Kurs"
        verbose_name_plural = "Kurse"
    
    def __str__(self) -> str:
        return f'{self.name} - {self.topic} ({self.start})'
    
class Booking(models.Model):
    user = models.ForeignKey(
        User,
        on_delete=models.CASCADE,
        verbose_name="Kundin"
    )
    course = models.ForeignKey(
        Courses,
        related_name="bookings",
        on_delete=models.CASCADE,
        verbose_name="Kurs"
    )
    date = models.DateTimeField(
        default=timezone.now,
        verbose_name="Buchungsdatum")
    
    class Meta:
        ordering = ["date"]
        verbose_name = "Buchung"
        verbose_name_plural = "Buchungen"
        
    def __str__(self) -> str:
        return f"{self.user} - {self.course} ({self.date})"
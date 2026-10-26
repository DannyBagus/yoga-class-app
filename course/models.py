from django.db import models
from django.utils import timezone
from django.contrib.auth.models import User

class Category(models.Model):
    ''' contains the course categories which is a foreign key of the courses model'''
    name = models.CharField(max_length=100)
    
    class Meta:
        verbose_name = "Kategorie"
        verbose_name_plural = "Kategorien"
    
    def __str__(self) -> str:
        return f'{self.name}'
    
class CourseManager(models.Manager):
    ''' custom manager to only return the upcoming courses '''
    def upcoming(self):
        today = timezone.now().date()  # Get today's date
        return self.filter(date__gte=today)  # Return courses with a date >= today

class Courses(models.Model):
    ''' capturing courses '''
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
    is_cancelled = models.BooleanField(
        default=False,
        verbose_name="Abgesagt",
        help_text="Abgesagte Kurse werden grau angezeigt und sind nicht buchbar.")
    cancelled_at = models.DateTimeField(
        null=True,
        blank=True,
        verbose_name="Abgesagt am")
    
    # Assign the default manager
    objects = models.Manager()  # Default manager
    upcoming_courses = CourseManager()  # Custom manager for upcoming courses
    
    class Meta:
        ordering = ["date"]
        verbose_name = "Kurs"
        verbose_name_plural = "Kurse"
    
    def __str__(self) -> str:
        return f'{self.category.name} - {self.name} ({self.date})'
    
class Booking(models.Model):
    ''' when a user books a course, the booking is stored in this model '''
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
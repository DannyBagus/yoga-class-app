from django.db import models

class News(models.Model):
    title = models.CharField(
        max_length=255,
        verbose_name="Titel"
    )
    news_text = models.TextField(
        verbose_name="News Text"
    )
    publish_date = models.DateField(
        verbose_name="Publikationsdatum"
    )
    important = models.BooleanField(
        default=False,
        verbose_name="Wichtig"
    )
    
    class Meta:
        verbose_name = "News"
        verbose_name_plural = "News"
    
    def __str__(self) -> str:
        return f"{self.publish_date}: {self.title}"
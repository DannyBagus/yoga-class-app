# Generated by Django 5.1.1 on 2024-09-20 09:35

import datetime
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('course', '0003_courses_categorie'),
    ]

    operations = [
        migrations.AddField(
            model_name='courses',
            name='date',
            field=models.DateField(default=datetime.datetime(2024, 9, 20, 9, 35, 0, 527499, tzinfo=datetime.timezone.utc)),
        ),
        migrations.AlterField(
            model_name='courses',
            name='start',
            field=models.TimeField(default='18:00:00'),
        ),
    ]

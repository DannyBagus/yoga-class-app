# Generated by Django 5.1.1 on 2024-09-29 22:13

import datetime
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('course', '0005_rename_categorie_category_and_more'),
    ]

    operations = [
        migrations.AlterField(
            model_name='courses',
            name='date',
            field=models.DateField(default=datetime.datetime(2024, 9, 29, 22, 13, 29, 587009, tzinfo=datetime.timezone.utc)),
        ),
    ]

# Generated by Django 4.1.7 on 2024-10-06 10:21

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('core', '0001_initial'),
    ]

    operations = [
        migrations.AlterModelOptions(
            name='news',
            options={'verbose_name': 'News', 'verbose_name_plural': 'News'},
        ),
        migrations.AddField(
            model_name='news',
            name='important',
            field=models.BooleanField(default=False, verbose_name='Wichtig'),
        ),
    ]

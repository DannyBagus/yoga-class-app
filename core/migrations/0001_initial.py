# Generated by Django 4.1.7 on 2024-10-06 10:19

from django.db import migrations, models


class Migration(migrations.Migration):

    initial = True

    dependencies = [
    ]

    operations = [
        migrations.CreateModel(
            name='News',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('title', models.CharField(max_length=255, verbose_name='Titel')),
                ('news_text', models.TextField(verbose_name='News Text')),
                ('publish_date', models.DateField(verbose_name='Publikationsdatum')),
            ],
        ),
    ]

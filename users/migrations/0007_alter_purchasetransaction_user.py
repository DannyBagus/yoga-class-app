# Generated by Django 4.1.7 on 2024-10-06 14:59

from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
        ('users', '0006_alter_purchasetransaction_date'),
    ]

    operations = [
        migrations.AlterField(
            model_name='purchasetransaction',
            name='user',
            field=models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, to=settings.AUTH_USER_MODEL),
        ),
    ]

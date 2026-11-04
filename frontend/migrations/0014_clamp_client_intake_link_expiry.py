from datetime import timedelta

from django.db import migrations


def clamp_existing_intake_expiries(apps, schema_editor):
    IntakeLink = apps.get_model('frontend', 'ClientIntakeLink')
    for link in IntakeLink.objects.only('pk', 'created_at', 'expires_at').iterator():
        maximum_expiry = link.created_at + timedelta(hours=10)
        if link.expires_at > maximum_expiry:
            IntakeLink.objects.filter(pk=link.pk).update(expires_at=maximum_expiry)


class Migration(migrations.Migration):

    dependencies = [
        ('frontend', '0013_clientprofile_principal_business_activity_and_more'),
    ]

    operations = [
        migrations.RunPython(
            clamp_existing_intake_expiries,
            migrations.RunPython.noop,
        ),
    ]

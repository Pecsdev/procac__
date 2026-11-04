from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('frontend', '0009_subscription_expires_at'),
    ]

    operations = [
        migrations.AlterField(
            model_name='clientprofile',
            name='status',
            field=models.CharField(
                choices=[
                    ('DRAFT', 'Draft'),
                    ('READY', 'Ready for Portal Fill'),
                    ('COMPLETED', 'Successfully Registered'),
                ],
                default='READY',
                max_length=9,
            ),
        ),
    ]

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('frontend', '0005_clientprofile_business_type_clientprofile_city_and_more'),
    ]

    operations = [
        migrations.AddField(
            model_name='clientprofile',
            name='status',
            field=models.CharField(
                choices=[
                    ('READY', 'Ready for Portal Fill'),
                    ('COMPLETED', 'Successfully Registered'),
                ],
                default='READY',
                max_length=9,
            ),
        ),
    ]
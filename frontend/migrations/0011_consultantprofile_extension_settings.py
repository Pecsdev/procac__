from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('frontend', '0010_clientprofile_draft_status'),
    ]

    operations = [
        migrations.AddField(
            model_name='consultantprofile',
            name='call_to_bar_number',
            field=models.CharField(blank=True, max_length=100),
        ),
        migrations.AddField(
            model_name='consultantprofile',
            name='extension_token_hash',
            field=models.CharField(blank=True, max_length=64),
        ),
        migrations.AddField(
            model_name='consultantprofile',
            name='presenter_email',
            field=models.EmailField(blank=True, max_length=254),
        ),
        migrations.AddField(
            model_name='consultantprofile',
            name='presenter_lga',
            field=models.CharField(blank=True, max_length=100),
        ),
        migrations.AddField(
            model_name='consultantprofile',
            name='presenter_phone',
            field=models.CharField(blank=True, max_length=30),
        ),
        migrations.AddField(
            model_name='consultantprofile',
            name='presenter_state',
            field=models.CharField(blank=True, max_length=100),
        ),
    ]

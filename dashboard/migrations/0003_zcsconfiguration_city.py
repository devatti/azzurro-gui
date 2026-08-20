from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('dashboard', '0002_zcsconfiguration'),
    ]

    operations = [
        migrations.AddField(
            model_name='zcsconfiguration',
            name='city',
            field=models.CharField(blank=True, default='', help_text='City used for the weather widget (e.g. "Rome, IT").', max_length=100),
        ),
    ]
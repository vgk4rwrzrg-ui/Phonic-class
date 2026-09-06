# Generated migration for async pet hatching

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('game', '0014_class_egg_cost_class_pets_enabled_kid_points_spent_and_more'),
    ]

    operations = [
        migrations.AddField(
            model_name='pet',
            name='hatch_status',
            field=models.CharField(
                max_length=20,
                default='unhatched',
                choices=[
                    ('unhatched', 'Unhatched'),
                    ('cracking', 'Cracking'),
                    ('halfway', 'Halfway'),
                    ('hatching', 'Hatching'),
                    ('complete', 'Complete'),
                    ('failed', 'Failed'),
                ]
            ),
        ),
        migrations.AddField(
            model_name='pet',
            name='hatch_task_id',
            field=models.CharField(max_length=100, blank=True, default=''),
        ),
    ]

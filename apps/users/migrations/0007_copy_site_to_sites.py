from django.db import migrations


def copy_site_to_sites(apps, schema_editor):
    User = apps.get_model('users', 'User')
    for user in User.objects.filter(role='SITE_USER', site__isnull=False):
        user.sites.add(user.site_id)


class Migration(migrations.Migration):
    dependencies = [
        ('users', '0006_user_sites'),
    ]
    operations = [
        migrations.RunPython(copy_site_to_sites, migrations.RunPython.noop),
    ]
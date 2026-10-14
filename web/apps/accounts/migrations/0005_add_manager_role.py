from django.db import migrations, models


def forward(apps, schema_editor):
    """Promote nobody.

    0003_simplify_roles collapsed "privileged" into "user", so the information
    needed to restore those assignments is gone. Inferring it would silently
    grant write access to accounts that may no longer warrant it — an admin
    promotes whoever should be a manager, from the Users page.
    """


def backward(apps, schema_editor):
    User = apps.get_model("accounts", "User")
    User.objects.filter(role="manager").update(role="user")


class Migration(migrations.Migration):
    dependencies = [
        ("accounts", "0004_alter_user_managers"),
    ]

    operations = [
        migrations.RunPython(forward, backward),
        migrations.AlterField(
            model_name="user",
            name="role",
            field=models.CharField(
                choices=[("user", "User"), ("manager", "Manager"), ("admin", "Admin")],
                default="user",
                max_length=20,
            ),
        ),
    ]

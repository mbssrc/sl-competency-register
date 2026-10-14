from django.contrib.auth.models import AbstractUser, UserManager
from django.db import models


class AppUserManager(UserManager):
    def active_admin_count(self):
        """How many accounts can still reach the admin tools."""
        return self.filter(role="admin", is_active=True).count()


class User(AbstractUser):
    ROLE_CHOICES = [
        ("user", "User"),
        ("manager", "Manager"),
        ("admin", "Admin"),
    ]
    # Ordered low to high. role_rank returns -1 for anything unrecognised, so a
    # stale value left by an old migration grants nothing.
    ROLE_RANK = {"user": 0, "manager": 1, "admin": 2}

    role = models.CharField(max_length=20, choices=ROLE_CHOICES, default="user")
    person = models.OneToOneField(
        "personnel.Person",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="user_account",
    )

    objects = AppUserManager()

    class Meta:
        app_label = "accounts"

    @property
    def role_rank(self):
        return self.ROLE_RANK.get(self.role, -1)

    @property
    def is_admin(self):
        return self.role == "admin"

    @property
    def is_manager(self):
        """True for managers and admins — anyone who may edit other people's data."""
        return self.role_rank >= self.ROLE_RANK["manager"]

    def save(self, *args, **kwargs):
        if self.is_superuser and self.role != "admin":
            self.role = "admin"
        super().save(*args, **kwargs)

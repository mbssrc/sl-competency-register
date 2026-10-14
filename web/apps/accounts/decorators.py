from functools import wraps

from django.contrib.auth.views import redirect_to_login
from django.http import HttpResponseForbidden

from .models import User


def _has_role(user, minimum_role):
    return user.is_active and user.role_rank >= User.ROLE_RANK[minimum_role]


def _is_owner(request, kwargs):
    linked = request.user.person_id
    return linked is not None and linked == kwargs.get("person_id")


def role_required(minimum_role, allow_owner=False):
    """Require the request user to hold at least `minimum_role`.

    Thresholds, lowest to highest: "user" (any active account — sees their own
    record, projects and the taxonomy), "manager" (edits personnel, assessments,
    projects and the taxonomy; sees the org-wide reports), "admin" (manages
    accounts, runs the admin tools, deletes personnel records).

    With allow_owner, a person may also act on their own record: the view must
    receive `person_id` as a URL keyword argument.
    """
    if minimum_role not in User.ROLE_RANK:
        raise ValueError(
            f"Unknown role {minimum_role!r}; expected one of {', '.join(User.ROLE_RANK)}"
        )

    def decorator(view_func):
        @wraps(view_func)
        def wrapper(request, *args, **kwargs):
            if not request.user.is_authenticated:
                # redirect_to_login URL-encodes ?next=.
                return redirect_to_login(request.get_full_path())
            if (allow_owner and _is_owner(request, kwargs)) or _has_role(
                request.user, minimum_role
            ):
                return view_func(request, *args, **kwargs)
            return HttpResponseForbidden("Insufficient permissions")

        # Lets a test assert that every routed view declares a threshold,
        # instead of discovering an ungated view in production.
        wrapper._required_role = minimum_role
        return wrapper

    return decorator


def owner_or_role(minimum_role):
    """Allow a person to act on their own record, or anyone at `minimum_role`."""
    return role_required(minimum_role, allow_owner=True)


# Retained so existing call sites keep working.
admin_required = role_required("admin")

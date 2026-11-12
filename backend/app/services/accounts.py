"""User provisioning. Passwordless: first login by email creates the account and a
default watchlist so the user lands on something usable."""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from ..models import User, Watchlist


def get_or_create_user(db: Session, email: str, display_name: str = "") -> User:
    user = db.execute(select(User).where(User.email == email)).scalar_one_or_none()
    if user is None:
        try:
            user = User(email=email, display_name=display_name or email.split("@")[0])
            db.add(user)
            db.flush()  # assign user.id
            db.add(Watchlist(user_id=user.id, name="My Watchlist"))
            db.commit()
        except IntegrityError:
            # concurrent first login for the same email — the unique constraint won;
            # roll back and use the row the other request created.
            db.rollback()
            user = db.execute(select(User).where(User.email == email)).scalar_one()
    elif display_name and user.display_name != display_name:
        user.display_name = display_name
        db.commit()
    return user


def default_watchlist(db: Session, user: User) -> Watchlist:
    wl = db.execute(
        select(Watchlist).where(Watchlist.user_id == user.id).order_by(Watchlist.id.asc()).limit(1)
    ).scalar_one_or_none()
    if wl is None:
        wl = Watchlist(user_id=user.id, name="My Watchlist")
        db.add(wl)
        db.commit()
    return wl

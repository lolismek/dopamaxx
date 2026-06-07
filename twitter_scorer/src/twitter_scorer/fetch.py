"""Fetch tweets from a user's timeline via twscrape."""

from __future__ import annotations

from .models import Tweet


async def fetch_timeline(username: str, limit: int = 50) -> list[Tweet]:
    """Return up to ``limit`` recent tweets from ``username``.

    Requires at least one Twitter account added to the twscrape pool:
        twscrape add_accounts accounts.txt
        twscrape login_accounts
    """
    try:
        from twscrape import API, gather
    except ImportError as exc:
        raise RuntimeError(
            "twscrape is required: pip install twscrape"
        ) from exc

    api = API()
    accounts = await api.pool.get_all()
    if not accounts:
        raise RuntimeError(
            "No Twitter accounts configured in twscrape.\n"
            "Add one with:\n"
            "  echo 'username password email email_password' > accounts.txt\n"
            "  twscrape add_accounts accounts.txt --username username --password password "
            "--email email --email_password email_password\n"
            "  twscrape login_accounts"
        )

    user = await api.user_by_login(username)
    if user is None:
        raise ValueError(f"Twitter user {username!r} not found")

    raw = await gather(api.user_tweets(user.id, limit=limit))
    return [
        Tweet(
            id=str(t.id),
            text=t.rawContent,
            author=username,
            created_at=t.date.timestamp(),
        )
        for t in raw
    ]

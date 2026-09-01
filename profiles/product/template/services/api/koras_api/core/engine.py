"""The connection pool, and nothing else.

Its own module because two things need it and they cannot import each other.
`core/database.py` builds the request session and depends on a resolved tenant;
`core/tenant.py` resolves that tenant, and resolving it is a query. Putting the
pool in either one makes the pair circular.

Splitting it also keeps the split honest: this file has no policy in it. What a
session is *allowed* to see is decided by whichever dependency sets its context,
and there are exactly three of those -- the tenant one, the organization
lookup, and the provisioning one -- each in a file that says what it grants.
"""

from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from .settings import settings

engine = create_async_engine(settings.database_url, pool_size=settings.database_pool_size)

SessionLocal = async_sessionmaker(engine, expire_on_commit=False)

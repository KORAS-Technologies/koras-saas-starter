"""The contract every external-system adapter must satisfy.

No adapter defaults to production, and every one takes an explicit environment.
This is the mechanical half of that rule. The other half is that nothing
constructs an adapter for an environment other than the one the process is
running as, which ``ExternalAdapter`` enforces rather than trusts.
"""

from __future__ import annotations

from abc import ABC, abstractmethod

from .environment import Environment, resolve_environment


class EnvironmentIsolationError(RuntimeError):
    """Raised when a component tries to reach across an environment boundary."""


class ExternalAdapter(ABC):
    """Base for every adapter that talks to a system outside this process.

    ZITADEL, Supabase, Doppler, GitHub, Vercel, Fly, Cloudflare, object storage,
    and the platform APIs of other products all sit behind one of these.

    The environment is a required constructor argument -- there is no default to
    inherit and nothing to infer from a hostname or a branch name. Construction
    also checks the request against the environment the process itself runs as,
    so a dev deployment cannot build a prod adapter even if a configuration
    value or a caller asks it to.

    Example:
        class ZitadelAdapter(ExternalAdapter):
            @property
            def system(self) -> str:
                return "zitadel"

        adapter = ZitadelAdapter(settings.environment,
                                 process_environment=settings.environment)
    """

    def __init__(self, environment: Environment | str, *, process_environment: Environment) -> None:
        requested = resolve_environment(environment)

        if requested is not process_environment:
            raise EnvironmentIsolationError(
                f"A process running as {process_environment.value!r} may not construct a "
                f"{type(self).__name__} for {requested.value!r}. Every adapter is confined "
                "to its own environment; reaching across the boundary is prohibited."
            )

        self._environment = requested

    @property
    def environment(self) -> Environment:
        return self._environment

    @property
    @abstractmethod
    def system(self) -> str:
        """The external system this adapter speaks to, for logs and audit."""

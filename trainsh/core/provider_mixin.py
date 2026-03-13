"""Provider facade for the DSL executor."""

from __future__ import annotations

from .provider_conditions import ExecutorProviderConditionsMixin
from .provider_dispatch import ExecutorProviderDispatchMixin
from .provider_data import ExecutorProviderDataMixin
from .provider_http import ExecutorProviderHttpMixin
from .provider_notify import ExecutorProviderNotifyMixin
from .provider_shell import ExecutorProviderShellOpsMixin
from .provider_storage import ExecutorProviderStorageMixin


class ExecutorProviderMixin(
    ExecutorProviderDispatchMixin,
    ExecutorProviderHttpMixin,
    ExecutorProviderDataMixin,
    ExecutorProviderStorageMixin,
    ExecutorProviderConditionsMixin,
    ExecutorProviderShellOpsMixin,
    ExecutorProviderNotifyMixin,
):
    pass

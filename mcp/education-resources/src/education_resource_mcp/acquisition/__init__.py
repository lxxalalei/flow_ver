"""Download provider routing primitives."""

from .models import (
    ACQUISITION_SCOPES,
    ACQUISITION_STRATEGIES,
    AcquisitionFailure,
    AcquisitionItemFailure,
    AcquisitionRequest,
    AcquisitionResult,
    AcquisitionStrategy,
    Artifact,
    ArtifactBundle,
)
from .router import AcquisitionRouter, ProviderRegistration

__all__ = [
    "ACQUISITION_SCOPES",
    "ACQUISITION_STRATEGIES",
    "AcquisitionFailure",
    "AcquisitionItemFailure",
    "AcquisitionRequest",
    "AcquisitionResult",
    "AcquisitionRouter",
    "AcquisitionStrategy",
    "Artifact",
    "ArtifactBundle",
    "ProviderRegistration",
]

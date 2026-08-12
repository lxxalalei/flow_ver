"""Private acquisition seam used by the education-resource job runner."""

from .models import (
    ACQUISITION_STRATEGIES,
    ACQUISITION_SCOPES,
    ARTIFACT_ROLES,
    ASSET_ROLES,
    AcquisitionScope,
    CompletionKind,
    FORMAL_ARTIFACT_ROLES,
    INTERNAL_ARTIFACT_ROLES,
    MAX_ARTIFACTS,
    PERSISTENT_ARTIFACT_ROLES,
    AcquisitionFailure,
    AcquisitionItemFailure,
    AcquisitionResult,
    AcquisitionStrategy,
    Artifact,
    ArtifactBundle,
    ArtifactRole,
    PreferredContainer,
    StrategyKind,
)
from ..downloader import DownloadBatchResult, DownloadItemFailure, DownloadResult
from .router import (
    BrowserCapture,
    DirectProvider,
    ProviderRegistration,
    WebMaterializer,
)
# 0037 active boundary: Provider calls carry only execution facts required by
# the actual acquisition operation. Descriptor/readiness/eligibility digests
# are no longer part of this seam.
from .simple import AcquisitionRequest, AcquisitionRouter

__all__ = [
    "ACQUISITION_STRATEGIES",
    "ACQUISITION_SCOPES",
    "ARTIFACT_ROLES",
    "ASSET_ROLES",
    "AcquisitionScope",
    "CompletionKind",
    "FORMAL_ARTIFACT_ROLES",
    "INTERNAL_ARTIFACT_ROLES",
    "MAX_ARTIFACTS",
    "PERSISTENT_ARTIFACT_ROLES",
    "AcquisitionFailure",
    "AcquisitionItemFailure",
    "AcquisitionRequest",
    "AcquisitionResult",
    "AcquisitionRouter",
    "AcquisitionStrategy",
    "Artifact",
    "ArtifactBundle",
    "ArtifactRole",
    "BrowserCapture",
    "DirectProvider",
    "DownloadBatchResult",
    "DownloadItemFailure",
    "DownloadResult",
    "PreferredContainer",
    "ProviderRegistration",
    "StrategyKind",
    "WebMaterializer",
]

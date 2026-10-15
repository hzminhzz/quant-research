"""Public bounded certification interface for the managed data plane.

The existing src.catalog registry remains the source of dataset discovery.
This module does not register or qualify every historical source, migrate old
schemas, or isolate file access. Certification binds exact supplied frame,
catalog, calendar and timezone identities. Run permits remain mandatory.
"""

from src.data_plane.certificate import (
    CertificateError,
    DataCertificate,
    DataPolicy,
    asof_frame,
    certify_frame,
    verify_certificate,
)

# Public spellings share one implementation; there is no parallel registry.
certify = certify_frame
view_asof = asof_frame
verify = verify_certificate

__all__ = [
    "CertificateError", "DataCertificate", "DataPolicy", "certify", "verify",
    "view_asof", "certify_frame", "verify_certificate", "asof_frame",
]

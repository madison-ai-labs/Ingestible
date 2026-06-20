"""Provenance-based trust classification for ANCS ingest (the preclassifier).

Security principle — mirrors Madison's Action-Gate, where a proposal's `rationale`
is display-only and never used to classify risk:

    The TRUST tier of an ingested document is decided ONLY by out-of-band
    provenance — where the file came from and how it was handed to us — NEVER by
    the document's own content.

A malicious PDF can *claim* to be a trusted personal note; it must not be able to
escalate its own trust. So `classify_trust` takes a provenance channel and nothing
derived from the bytes. Content-derived signals (domain, document type) may be used
to ORGANIZE — set metadata, pick a domain namespace — but must never feed trust.

The trust class then selects which ANCS tenant the document lands in. Tenants are
isolated, so an untrusted document can never surface as a human-confirmed core fact.
The set of classes is open — add a channel + class + policy and route a new corpus.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


class SourceChannel(str, Enum):
    """How Madison obtained the document. This is OUT-OF-BAND provenance — it is
    asserted by the trusted caller (Madison), not read from the document."""

    USER_AUTHORED = "user_authored"     # the user deliberately wrote/added it
    DOWNLOAD = "download"               # fetched from an external source (web, arxiv…)
    MAIL_ATTACHMENT = "mail_attachment" # arrived via email — attacker-influenceable
    UNKNOWN = "unknown"                 # unspecified → treated as least trusted


class TrustClass(str, Enum):
    PERSONAL = "personal"     # user's own material
    REFERENCE = "reference"   # external but deliberately collected
    UNTRUSTED = "untrusted"   # attacker-influenceable / unknown provenance


@dataclass(frozen=True)
class TrustPolicy:
    """What a trust class implies for ANCS ingest."""

    trust_class: TrustClass
    tenant_key_setting: str  # Settings attribute holding this class's ANCS key
    can_promote: bool        # may anything here EVER reach SUPPORTED (via human confirm)?
    note: str


# Each class maps to its own isolated ANCS tenant. Only `personal` is ever
# eligible for promotion — and even then only through Madison's human-confirm
# gate (E8), never automatically.
_POLICIES: dict[TrustClass, TrustPolicy] = {
    TrustClass.PERSONAL: TrustPolicy(
        TrustClass.PERSONAL, "ancs_key_personal", True,
        "User-authored; recallable and eligible for human-confirm promotion.",
    ),
    TrustClass.REFERENCE: TrustPolicy(
        TrustClass.REFERENCE, "ancs_key_reference", False,
        "External reference; recall-only, never promoted to a self-fact.",
    ),
    TrustClass.UNTRUSTED: TrustPolicy(
        TrustClass.UNTRUSTED, "ancs_key_untrusted", False,
        "Attacker-influenceable/unknown; most isolated, recall-only.",
    ),
}

# Provenance → trust class. Anything not explicitly trusted falls to UNTRUSTED.
_CHANNEL_TO_CLASS: dict[SourceChannel, TrustClass] = {
    SourceChannel.USER_AUTHORED: TrustClass.PERSONAL,
    SourceChannel.DOWNLOAD: TrustClass.REFERENCE,
    SourceChannel.MAIL_ATTACHMENT: TrustClass.UNTRUSTED,
    SourceChannel.UNKNOWN: TrustClass.UNTRUSTED,
}


def classify_trust(source_channel: str | None) -> TrustPolicy:
    """Map an out-of-band provenance channel to a trust policy.

    Default-deny: an unrecognized, missing, or malformed channel resolves to the
    most isolated class (UNTRUSTED). Note the signature takes ONLY provenance —
    there is deliberately no parameter through which document content could
    influence the trust tier.
    """
    try:
        channel = SourceChannel(source_channel) if source_channel else SourceChannel.UNKNOWN
    except ValueError:
        channel = SourceChannel.UNKNOWN
    cls = _CHANNEL_TO_CLASS.get(channel, TrustClass.UNTRUSTED)
    return _POLICIES[cls]


def resolve_ancs_config(policy: TrustPolicy, settings, source_uri: str | None = None):
    """Build the ANCSConfig for a trust policy.

    Raises ValueError if ANCS isn't configured or the class's tenant key is unset
    — we refuse to ingest into a class that hasn't been deliberately provisioned,
    rather than silently falling back to a more-trusted tenant.
    """
    from ingestible.adapters.ancs_export import ANCSConfig

    base_url = getattr(settings, "ancs_url", "") or ""
    if not base_url:
        raise ValueError("ANCS is not configured (INGEST_ANCS_URL is empty)")

    key = getattr(settings, policy.tenant_key_setting, "") or ""
    if not key:
        raise ValueError(
            f"No ANCS tenant key for trust class '{policy.trust_class.value}' "
            f"({policy.tenant_key_setting} is unset) — refusing to ingest"
        )

    return ANCSConfig(
        base_url=base_url,
        api_key=key,
        source_uri=source_uri,
        timeout=getattr(settings, "ancs_timeout", 60.0),
    )

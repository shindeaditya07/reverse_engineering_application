"""Documentation agent (FR-7): documents assembled from stored claims, no model (CLM-1.6)."""

from services.documentation.assemble import Doc, DocClaim, assemble, check

__all__ = ["Doc", "DocClaim", "assemble", "check"]

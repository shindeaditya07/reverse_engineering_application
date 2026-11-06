"""Code Analysis agent (FR-3): routes, call graph and unresolved constructs from the syntax
tree. Deterministic, no model."""

from services.codeanalysis.analyze import Analysis, CallEdge, analyze

__all__ = ["Analysis", "CallEdge", "analyze"]

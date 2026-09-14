"""Package-local routing canvas backed by the shared runtime."""
try:
    from .wayricad_runtime.preview import GeometryPreview
except ImportError:
    from wayricad_runtime.preview import GeometryPreview

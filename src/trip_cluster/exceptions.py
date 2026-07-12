"""TripCluster exceptions."""


class TripClusterError(Exception):
    """Base exception for TripCluster."""


class ParseError(TripClusterError):
    """Raised when the input file cannot be parsed."""


class GeocodeError(TripClusterError):
    """Raised when geocoding fails in strict mode."""


class MatrixError(TripClusterError):
    """Raised when the travel-time matrix cannot be built."""

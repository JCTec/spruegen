"""Exception hierarchy. Every error carries an actionable message the CLI prints as-is."""

from __future__ import annotations


class SpruegenError(Exception):
    """Error accionable; el CLI lo imprime tal cual."""


class InputError(SpruegenError):
    """Bad input file / profile / job (units, not watertight, unknown preset...)."""


class FeatureError(SpruegenError):
    """The ring geometry could not be understood (no finger hole, no safe inner attach...)."""


class PolicyError(SpruegenError):
    """The plan would break a shop rule or a lock."""

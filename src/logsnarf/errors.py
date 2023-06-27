#!/usr/bin/env python
# -*- coding: utf-8 -*-
# pylint: disable=invalid-name
"""One line description here.

Longer description here.
"""


class Error(Exception):
    """Base exception class."""


class ValidationError(ValueError, Error):
    """Validation Error."""


class ConfigError(Error):
    """Configuration Error."""


class ValidatorError(Error):
    """Invalid validator."""


class MissingConfigValue(ConfigError):
    def __init__(self, section, item, msg=""):
        self.section = section
        self.item = item
        self.msg = msg

    def __str__(self):
        print(f"Missing configuration item section: {self.section} item: {self.item} {self.msg}")


class ServiceError(Error):
    """Error raised by BigQueryService."""

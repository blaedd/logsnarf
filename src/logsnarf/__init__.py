#!/usr/bin/env python
# -*- coding: utf-8 -*-

"""This package provides classes for streaming log files to BigQuery.

Currently only JSON schema are supported, and the log files must, likewise
contain valid line separated JSON. You can however hook into post-decode hooks
to conveniently munge or backfill fields based on the log data.

"""
__version__ = '0.0.1'
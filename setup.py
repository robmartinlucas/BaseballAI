"""Compatibility shim for older pip editable installs.

Project metadata lives in pyproject.toml. This file exists so older pip versions
that still expect setup.py for editable installs can invoke setuptools.
"""
from setuptools import setup

setup()

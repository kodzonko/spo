# Docstring Decisions

## Runtime API vs Tests

Option A was adding full multi-section Google-style docstrings to every documented callable, including pytest fixtures and tests.
Option B was using concise Google-style docstrings for public runtime modules, classes, and callables, while keeping test docstrings to single-line behavior statements.

This repository now uses option B because it satisfies the public-API documentation goal without drowning tests in repetitive setup details, and it matches the agreed requirement that tests explain only what behavior they cover.

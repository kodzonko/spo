For commit messages use semantic commit messages. For example: feat: add new feature, fix: resolve issue, chore: update dependencies.

Use `uv` command to run the application in development mode, test and add dependencies.

Use `uv run pytest` for testing.

Add docstrings to functions and classes, and use type hints for function parameters and return types.

When adding new features or fixing bugs, ensure to write tests that cover the new functionality or the bug fix.

Don't create docstrings for tests, but ensure they are clear and descriptive.

When making changes to the codebase, ensure that you run the tests locally to verify the changes.

To annotate optional values don't use `Optional`, instead use `Type | None` for type hints.

When annotaing collections, use the `list`, `dict`, `set`, and `tuple` types directly instead of using `List`, `Dict`, `Set`, and `Tuple` from the `typing` module.

When annotating collections with specific types, use `list[Type]`, `dict[KeyType, ValueType]`, `set[Type]`, and `tuple[Type1, Type2, ...]` instead of `List[Type]`, `Dict[KeyType, ValueType]`, `Set[Type]`, and `Tuple[Type1, Type2, ...]`.

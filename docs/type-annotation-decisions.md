# Type Annotation Decisions

## ANN Compliance At Dynamic Boundaries

Option A was relaxing Ruff's `ANN` rules for tests, nested helper functions, and dynamic integration points such as callback wrappers and template context.
Option B was keeping `ANN` enabled everywhere and using the narrowest honest annotations at each boundary: `ParamSpec` and `TypeVar` for call-through helpers, explicit async iterator return types for streaming generators, and `object` where values are intentionally open-ended.

This repository now uses option B because it keeps the lint signal consistent across source and tests without pretending that framework payloads or template context are more structured than they really are.

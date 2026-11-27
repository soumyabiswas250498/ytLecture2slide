# AGENTS.md — ytLecture2slide

All development activities MUST follow the instructions below.

## 1. Core Engineering Principles

- Follow SOLID, DRY, KISS and YAGNI principles.
- Follow Clean Code and Separation of Concerns.
- Prefer composition over inheritance.
- Maintain high cohesion and low coupling.
- Design reusable, independently testable modules.
- Avoid unnecessary abstractions and overengineering.
- Prioritize readability, maintainability, reliability and simplicity.
- Fix root causes rather than applying temporary workarounds.

## 2. Architecture

- Follow a modular monolith architecture.
- Maintain clear boundaries between presentation, application, domain and infrastructure layers.
- Keep business logic independent of frameworks.
- Use dependency injection wherever appropriate.
- Keep external service integrations behind well-defined interfaces.
- Ensure individual processing modules can be used independently.
- Avoid circular dependencies.
- Do not introduce microservices without explicit approval.

## 3. Code Quality

- Use meaningful and descriptive naming conventions.
- Keep functions, classes and components focused on a single responsibility.
- Avoid unnecessarily large files and functions.
- Avoid deeply nested conditional logic.
- Use early returns wherever appropriate.
- Remove unused imports, dead code and unnecessary dependencies.
- Explain why complex logic exists rather than commenting on obvious code.
- Avoid magic numbers and hardcoded configuration values.
- Maintain consistent formatting and coding conventions.

## 4. Python Standards

- Follow PEP 8 conventions.
- Use type hints for function parameters and return values.
- Use Pydantic for external data validation.
- Use Ruff for linting and formatting.
- Use mypy for static type checking.
- Use uv for dependency management.
- Use context managers for resource management.
- Catch specific exceptions instead of broad exceptions.
- Never silently suppress errors.
- Separate business logic from FastAPI route handlers.

## 5. Frontend Standards

- Use TypeScript with strict mode enabled.
- Avoid using `any` unless explicitly justified.
- Use functional React components.
- Follow feature-based folder organization.
- Create reusable UI components and custom hooks.
- Keep business logic separate from presentation components.
- Avoid unnecessary state, effects and component re-renders.
- Centralize API communication.
- Validate external data using Zod where appropriate.
- Use consistent loading, error, empty and success states.
- Follow accessibility and responsive design standards.
- Use ESLint and Prettier.

## 6. Configuration Management

- Make application behaviour configuration-driven.
- Never hardcode credentials, API keys, file paths, channel names or exam names.
- Maintain a centralized, typed configuration system.
- Use environment variables for deployment-specific settings.
- Maintain an updated `.env.example`.
- Validate configuration during application startup.
- Provide sensible defaults where appropriate.

## 7. Security

- Treat all external input as untrusted.
- Validate and sanitize inputs at system boundaries.
- Prevent SQL injection, command injection and path traversal.
- Avoid shell command construction using unsanitized input.
- Never expose sensitive information in logs or API responses.
- Never commit credentials or secrets.
- Use least-privilege permissions.
- Respect external service access restrictions and content permissions.

## 8. Error Handling and Logging

- Implement centralized error handling.
- Use structured logging with appropriate severity levels.
- Provide meaningful, actionable error messages.
- Include job identifiers in processing logs.
- Implement bounded retries with exponential backoff for transient failures.
- Distinguish recoverable and non-recoverable errors.
- Never report success when an operation has failed.

## 9. Reliability and Data Integrity

- Make processing operations idempotent wherever possible.
- Prevent duplicate job execution.
- Support recovery from interrupted processing.
- Use database transactions where appropriate.
- Maintain database schema migrations.
- Use atomic file operations for generated outputs.
- Verify output integrity before deleting source files.
- Never silently discard potentially important content.
- Preserve recoverable intermediate results when processing fails.

## 10. Performance and Resource Management

- Avoid unnecessary CPU, memory, network and disk usage.
- Process large files incrementally wherever possible.
- Avoid loading entire videos into memory.
- Limit concurrency using configurable settings.
- Release resources after use.
- Clean up temporary files safely.
- Measure performance before introducing optimizations.
- Keep the application suitable for resource-constrained servers.

## 11. Testing

- Use Pytest for backend testing.
- Use Vitest for frontend testing.
- Use Playwright for end-to-end testing.
- Write meaningful unit and integration tests.
- Test normal cases, edge cases and failure scenarios.
- Add regression tests when fixing bugs.
- Mock external services where appropriate.
- Avoid tests that depend on live external services by default.
- Never weaken or remove tests merely to make them pass.
- Run relevant tests, linting and type checks before completing a task.

## 12. Git and Version Control

- Keep changes focused on the assigned task.
- Avoid unrelated modifications.
- Preserve existing user changes.
- Maintain an appropriate `.gitignore`.
- Do not commit generated files, temporary videos, databases or secrets.
- Do not perform destructive Git operations.
- Do not commit or push changes without authorization.

## 13. Documentation

- Maintain an updated README.md.
- Document architecture, installation and configuration.
- Document public interfaces and API contracts.
- Record significant architectural decisions and their rationale.
- Update documentation whenever behaviour changes.
- Maintain a development roadmap in PLANS.md.
- Maintain a development history in CHANGELOG.md.

## 14. AI Agent Development Rules

- Understand existing code before modifying it.
- Reuse existing components and utilities before creating new ones.
- Implement only the explicitly assigned scope.
- Do not implement future development phases prematurely.
- Do not change the approved technology stack without permission.
- Do not introduce unnecessary dependencies.
- Do not modify existing API contracts without authorization.
- Do not make significant architectural decisions without approval.
- Do not assume undocumented business requirements.
- Ask for clarification when requirements are materially ambiguous.
- Never fabricate test results or implementation status.
- Do not use placeholders or mock implementations as completed features.
- Stop after completing the assigned phase.

## 15. Definition of Done

A task is considered complete only when:

- All assigned requirements are implemented.
- Acceptance criteria are satisfied.
- Relevant tests pass.
- Linting and type checks pass.
- Error handling is implemented.
- Documentation is updated.
- No unintended regressions are introduced.
- Known limitations are explicitly documented.

## 16. Mandatory Completion Report

After completing each task or development phase, provide a report containing:

1. Implementation summary.
2. Files created and modified.
3. Architectural decisions.
4. Dependencies added and their justification.
5. Tests executed and actual results.
6. Linting and type-checking results.
7. Acceptance criteria status.
8. Known issues and limitations.
9. Pending work.

Do not proceed to the next phase without explicit approval.

## 17. Project-Specific Constraints

- The application must remain reusable for different examinations and educational channels.
- Do not tightly couple the application to WBPSC IDO.
- No LLM, OCR or paid AI API integration.
- All video and image processing must run locally.
- Individual pipeline modules must support independent execution.
- Image deduplication must prioritize preserving potentially unique educational content.
- Never delete a source video before verifying successful PDF generation.
- Support deployment through Docker on an Ubuntu server.
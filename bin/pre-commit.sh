#!/bin/bash
#
# Pre-commit hook: runs ruff and the fast pytest suite (excludes tests marked
# `slow`, see pyproject.toml) on staged Python files. Rejects the commit if
# lint or tests fail. Run `just test` for the full suite, including slow
# scale-checkpoint tests.

STAGED_PY_FILES=$(git diff --cached --name-only --diff-filter=ACM | grep -E '\.py$' || true)

if [ -z "$STAGED_PY_FILES" ]; then
  exit 0
fi

echo "---"
echo "Running lint and tests..."
echo "---"

just lint
LINT_EXIT=$?

if [ $LINT_EXIT -ne 0 ]; then
  echo "---"
  echo "Lint failed. Please fix the errors above and try again."
  exit 1
fi

just test-fast
TEST_EXIT=$?

if [ $TEST_EXIT -ne 0 ]; then
  echo "---"
  echo "Tests failed. Please fix the errors above and try again."
  exit 1
fi

echo "Lint and tests passed."
exit 0

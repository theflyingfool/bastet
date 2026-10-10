# Test-Writing Guardrails: Stop Test Bloat & Layer Duplication

You have a severe tendency toward test bloat. The test suite currently has over 1,200 tests taking 6 full minutes for a 14k LOC project (a bloated 1:1 test-to-code ratio). You are prohibited from adding sprawling micro-tests. Follow these strict rules when writing or modifying tests:

### 1. The "Single-Sentry" Rule (Zero Layer Duplication)
- NEVER duplicate tests across layers. If business logic, error handling, or edge cases are tested in `tests/core/`, DO NOT test them again in `tests/cli/`.
- `tests/cli/` is ONLY for testing the CLI boundary: Did the argument parse? Did the flag trigger the right mode? Is the exit code correct? Is the top-level user summary printed?
- A CLI command must have at most 4–6 high-level tests (happy path, `-y` non-interactive, exit code on error). Never write 25+ mocked CLI tests for internal branches already covered by core tests.

### 2. Test Observable Behavior, Not Implementation Details
- DO NOT write unit tests for private helper functions, trivial string cleaners, regex splits, or 2-line utilities (e.g. `clean()`, `short_cpu()`, `format_size()`). Test them strictly through the public interface that calls them.
- Avoid fragile white-box monkeypatching (`monkeypatch.setattr(...)` on private module variables or internal functions). If a test requires mocking 4 internal functions to run, the test is poorly designed.

### 3. Parameterize; Never Spawn Function Sprawl
- NEVER write separate `def test_...` functions for minor input variations, edge cases, or string formats.
- ALWAYS use `@pytest.mark.parametrize` with a compact table of inputs and expected outputs.
- If you find yourself writing more than 2 `def test_...` for parsing logic, collapse them into a single parameterized test immediately.

### 4. Zero Subprocess & Latency Overhead
- Avoid spawning OS subprocesses (`git init`, `git config`, `ssh-keygen`) per test function. Reuse fixtures or mock them.
- NEVER use real `threading.Barrier` waits, `time.sleep()`, or timeouts in unit tests. Mock the clock or thread pools deterministically.
- A single test must run in under 0.05 seconds. Any test taking over 0.5 seconds is considered a performance defect.

### 5. Strict Test Budget per Feature/Task
- For any new task or feature, your budget is **3 to 6 focused tests** maximum:
  1. Primary happy path.
  2. The primary domain invariant / safety gate.
  3. The primary user-facing error / exit code.
- Stop adding tests for hypothetical permutations or obsolete legacy syntax. Quality and signal-to-noise ratio over quantity.
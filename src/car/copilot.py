from __future__ import annotations

# Re-exported from car.harness for backward compatibility.
# New code should import directly from car.harness.
from car.harness import (  # noqa: F401
    DoctorResult,
    check_copilot_extension,
    check_gh_auth,
    check_gh_installed,
    copilot_env,
    exec_copilot,
)

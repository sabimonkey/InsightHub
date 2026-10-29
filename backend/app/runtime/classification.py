from enum import Enum


class DependencyTier(str, Enum):
    CORE_REQUIRED = "CORE_REQUIRED"
    CAPABILITY = "CAPABILITY_DEPENDENCY"
    OPTIONAL = "OPTIONAL"


SERVICE_TIERS: dict[str, DependencyTier] = {
    "postgresql": DependencyTier.CORE_REQUIRED,
    "redis": DependencyTier.CORE_REQUIRED,
    "backend": DependencyTier.CORE_REQUIRED,
    "rq_worker": DependencyTier.CORE_REQUIRED,
    "frontend": DependencyTier.CORE_REQUIRED,
    "bge_m3": DependencyTier.CAPABILITY,
    "chromium": DependencyTier.CAPABILITY,
    "deepseek": DependencyTier.OPTIONAL,
    "siliconflow": DependencyTier.OPTIONAL,
    "lm_studio": DependencyTier.OPTIONAL,
    "docker_engine": DependencyTier.CORE_REQUIRED,
}


class HealthState(str, Enum):
    READY = "READY"
    STARTING = "STARTING"
    DEGRADED = "DEGRADED"
    FAILED = "FAILED"
    STOPPED = "STOPPED"
    UNKNOWN = "UNKNOWN"
    REUSE = "REUSE"
    CONFIGURED = "CONFIGURED"
    MISSING = "MISSING"
    OPTIONAL_DISABLED = "OPTIONAL"
    PORT_CONFLICT = "PORT_CONFLICT"


def overall_state(service_states: dict[str, str]) -> str:
    core = [k for k, tier in SERVICE_TIERS.items() if tier == DependencyTier.CORE_REQUIRED and k != "docker_engine"]
    for name in core:
        state = service_states.get(name, HealthState.UNKNOWN.value)
        if state in {HealthState.FAILED.value, HealthState.STOPPED.value, HealthState.PORT_CONFLICT.value}:
            return HealthState.FAILED.value
        if state in {HealthState.UNKNOWN.value, HealthState.STARTING.value}:
            return HealthState.STARTING.value
    capability = [k for k, tier in SERVICE_TIERS.items() if tier == DependencyTier.CAPABILITY]
    degraded = any(service_states.get(k) not in {HealthState.READY.value, HealthState.REUSE.value, HealthState.CONFIGURED.value} for k in capability)
    if degraded:
        return HealthState.DEGRADED.value
    return HealthState.READY.value

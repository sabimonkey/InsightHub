"""Connection probe entrypoints."""

from app.services.llm.capability_probe import probe_deployment_capabilities


def probe_provider(provider) -> dict:
    """Run full deployment capability probes (connectivity + structured output)."""
    return probe_deployment_capabilities(provider)

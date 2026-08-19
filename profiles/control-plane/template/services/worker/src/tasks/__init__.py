from typing import Any


async def provision_product(ctx: dict[str, Any], product_slug: str) -> dict[str, Any]:
    """Orchestrate infrastructure provisioning for a newly registered product."""
    return {"status": "provisioned", "product": product_slug}


async def reconcile_infrastructure(ctx: dict[str, Any], product_slug: str) -> dict[str, Any]:
    """Detect and correct infrastructure drift for a product."""
    return {"status": "reconciled", "product": product_slug}

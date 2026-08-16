async def provision_product(ctx: dict, product_slug: str) -> dict:
    """Orchestrate infrastructure provisioning for a newly registered product."""
    return {"status": "provisioned", "product": product_slug}


async def reconcile_infrastructure(ctx: dict, product_slug: str) -> dict:
    """Detect and correct infrastructure drift for a product."""
    return {"status": "reconciled", "product": product_slug}

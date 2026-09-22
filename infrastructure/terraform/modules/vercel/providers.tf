terraform {
  required_providers {
    vercel = {
      source  = "vercel/vercel"
      # Kept level with the root providers.tf AND with
      # infrastructure/terraform/templates/providers.tf.tpl, which bootstrap:doctor
      # assembles a root from. All four Vercel pins must agree or nothing can init.
      version = "~> 5.0"
    }
  }
}

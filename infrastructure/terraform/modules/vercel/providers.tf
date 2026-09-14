terraform {
  required_providers {
    vercel = {
      source  = "vercel/vercel"
      # Kept level with the root providers.tf. All three Vercel pins must
      # agree or nothing can init.
      version = "~> 5.0"
    }
  }
}

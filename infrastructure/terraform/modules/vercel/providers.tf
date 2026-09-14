terraform {
  required_providers {
    vercel = {
      source  = "vercel/vercel"
      # >= 4.2.0 for `git_provider_options.create_deployments`; see the root
      # providers.tf. All three Vercel pins must agree or nothing can init.
      version = "~> 5.0"
    }
  }
}

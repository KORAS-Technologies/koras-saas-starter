resource "cloudflare_record" "records" {
  for_each = { for r in var.dns_records : r.name => r }

  zone_id = var.zone_id
  name    = each.value.name
  type    = each.value.type
  content = each.value.value
  proxied = lookup(each.value, "proxied", true)
  ttl     = lookup(each.value, "ttl", 1) # 1 = auto
}

# WAF — OWASP managed ruleset
resource "cloudflare_ruleset" "waf" {
  count = var.enable_waf ? 1 : 0

  zone_id     = var.zone_id
  name        = "${var.project_slug} WAF"
  description = "Managed WAF rules for ${var.project_slug}"
  kind        = "zone"
  phase       = "http_request_firewall_managed"

  rules {
    action = "execute"
    action_parameters {
      id = "efb7b8c949ac4650a09736fc376e9aee" # Cloudflare OWASP core ruleset
    }
    expression  = "true"
    description = "OWASP core ruleset"
    enabled     = true
  }
}

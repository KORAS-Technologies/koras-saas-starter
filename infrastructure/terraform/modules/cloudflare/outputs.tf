output "record_ids" {
  value = { for k, v in cloudflare_record.records : k => v.id }
}

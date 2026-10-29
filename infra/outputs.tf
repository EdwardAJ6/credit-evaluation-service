output "api_url" {
  description = "Base URL of the API (it answers a few minutes after boot, once the image is built)."
  value       = "http://${aws_instance.app.public_ip}"
}

output "boot_log" {
  description = "Read the instance console output to follow or debug the first boot."
  value       = "aws ec2 get-console-output --region ${var.region} --instance-id ${aws_instance.app.id} --latest --output text"
}

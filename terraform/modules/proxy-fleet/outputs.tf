output "asg_name" { value = aws_autoscaling_group.proxy.name }
output "nlb_dns_name" { value = aws_lb.proxy.dns_name }
output "nlb_arn" { value = aws_lb.proxy.arn }
output "security_group_id" { value = aws_security_group.proxy.id }

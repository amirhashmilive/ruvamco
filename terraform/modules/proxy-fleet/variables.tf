variable "environment" { type = string }
variable "vpc_id" { type = string }
variable "private_subnet_ids" { type = list(string) }
variable "public_subnet_ids" { type = list(string) }
variable "instance_type" { type = string; default = "c6i.xlarge" }
variable "min_size" { type = number; default = 3 }
variable "max_size" { type = number; default = 2000 }
variable "desired_capacity" { type = number; default = 6 }
variable "ami_id" { type = string; default = "" }

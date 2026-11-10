variable "vault_name" {
  description = "The name of this Key Vault."
  type        = string
}

variable "resource_group_name" {
  description = "The name of the resource group to create the resources in."
  type        = string
}

variable "location" {
  description = "The location to create the resources in."
  type        = string
}

variable "tenant_id" {
  description = "The ID of the Microsoft Entra tenant that should be used for authenticating requests to this Key Vault. If value is set to null, the ID of the current tenant will be used."
  type        = string
  nullable    = true
  default     = null
}

variable "soft_delete_retention_days" {
  description = "The number of days that items should be retained for once soft-deleted."
  type        = number
  default     = 90
}

variable "purge_protection_enabled" {
  description = "Is purge protection enabled for this Key Vault?"
  type        = bool
  default     = true
}

variable "enabled_for_deployment" {
  description = "Should Azure Virtual Machines be permitted to retrieve certificates stored as secrets from this Key Vault?"
  type        = bool
  default     = false
}

variable "enabled_for_disk_encryption" {
  description = "Should Azure Disk Encryption be permitted to retrieve secrets and unwrap keys from this Key Vault?"
  type        = bool
  default     = false
}

variable "enabled_for_template_deployment" {
  description = "Should Azure Resource Manager be permitted to retrieve secrets from this Key Vault?"
  type        = bool
  default     = false
}

variable "access_policies" {
  description = "A list of access policies for this Key Vault. The access policy model is a legacy authorization system. RBAC is the recommended authorization system."
  type = list(object({
    object_id               = string
    secret_permissions      = optional(list(string), [])
    certificate_permissions = optional(list(string), [])
    key_permissions         = optional(list(string), [])
  }))
  default = []
}

variable "enable_rbac_authorization" {
  description = "Should RBAC authorization be enabled for this Key Vault?"
  type        = bool
  default     = true
}

variable "public_network_access_enabled" {
  description = "Should public network access be enabled for this Key Vault?"
  type        = bool
  default     = true
}

variable "network_acls_default_action" {
  description = "The default action of the network ACLs of this Key Vault."
  type        = string
  default     = "Deny"

  validation {
    condition     = contains(["Allow", "Deny"], var.network_acls_default_action)
    error_message = "Default action must be \"Allow\" or \"Deny\"."
  }
}

variable "network_acls_bypass_azure_services" {
  description = "Should Azure services be allowed to bypass the network ACLs of this Key Vault?"
  type        = bool
  default     = true
}

variable "network_acls_ip_rules" {
  description = "A list of IP addresses or CIDR blocks that should be able to bypass the network ACLs and access this Key Vault."
  type        = list(string)
  default     = []
}

variable "network_acls_virtual_network_subnet_ids" {
  description = "A list of Virtual Network subnet IDs that should be able to bypass the network ACLs and access this Key Vault."
  type        = list(string)
  default     = []
}

variable "private_endpoints" {
  description = "A map of private endpoints to create for this Key Vault. A dedicated subnet for private endpoints is recommended."
  type = map(object({
    name                   = string
    network_interface_name = optional(string)
    subnet_id              = string
    private_dns_zone_ids   = list(string)
  }))
  nullable = false
  default  = {}
}

variable "diagnostic_setting_name" {
  description = "The name of this diagnostic setting."
  type        = string
  default     = "audit-logs"
}

variable "diagnostic_setting_enabled_log_categories" {
  description = "A list of log categories to be enabled for this diagnostic setting."
  type        = list(string)
  default     = ["AuditEvent"]
}

variable "diagnostic_setting_enabled_metric_categories" {
  description = "A list of metric categories to be enabled for this diagnostic setting."
  type        = list(string)
  default     = []
}

variable "log_analytics_workspace_id" {
  description = "The ID of the Log Analytics workspace to send diagnostics to."
  type        = string
}

variable "tags" {
  description = "A map of tags to assign to the resources."
  type        = map(string)
  default     = {}
}

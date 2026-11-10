run "research_smoke_plan" {
 command = plan
}

variables {
  environment = "test"
  notification_channel_id = "oasis-research"
  function_name = "oasis-research"
  service_prefix = "oasis-research"
  eval_period_sec = "oasis-research"
  duration_sec = "oasis-research"
  error_5xx_threshold = 1
  execution_error_threshold = 1
  execution_time_max = 1
}

mock_provider "google" {
}

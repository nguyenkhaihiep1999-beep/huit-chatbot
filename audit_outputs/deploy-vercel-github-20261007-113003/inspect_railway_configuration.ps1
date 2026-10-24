$ErrorActionPreference = 'Stop'
$taskConfig = Get-Content -LiteralPath 'C:\Users\LOQ\.railway\config.json' -Raw | ConvertFrom-Json
$taskClient = [System.Net.Http.HttpClient]::new()
$taskClient.Timeout = [TimeSpan]::FromSeconds(20)
$taskClient.DefaultRequestHeaders.Authorization = [System.Net.Http.Headers.AuthenticationHeaderValue]::new('Bearer', $taskConfig.user.accessToken)
$taskQuery = 'query inspect($projectId: String!, $environmentId: String!, $serviceId: String!) { variables(projectId: $projectId, environmentId: $environmentId, serviceId: $serviceId) buildLogs(deploymentId: "e7760864-4567-45bc-9b1c-df5ed76a9956", limit: 60) { message timestamp } deploymentLogs(deploymentId: "e7760864-4567-45bc-9b1c-df5ed76a9956", limit: 60) { message timestamp } }'
$taskPayload = @{query=$taskQuery;variables=@{projectId='18aa08f0-352d-4248-ad54-8cda262cf410';environmentId='6b6eb395-9851-4f6c-952d-794f669f3fb4';serviceId='9217966a-82c4-4947-9bf2-31834a607500'}} | ConvertTo-Json -Depth 5 -Compress
try {
    $taskContent = [System.Net.Http.StringContent]::new($taskPayload, [System.Text.Encoding]::UTF8, 'application/json')
    $taskResp = $taskClient.PostAsync('https://backboard.railway.com/graphql/v2', $taskContent).GetAwaiter().GetResult()
    $taskData = $taskResp.Content.ReadAsStringAsync().GetAwaiter().GetResult() | ConvertFrom-Json
    $taskVars = $taskData.data.variables
    $taskLogs = @($taskData.data.buildLogs) + @($taskData.data.deploymentLogs)
    $taskMessages = @($taskLogs | ForEach-Object {$_.message}) -join [Environment]::NewLine
    [pscustomobject]@{
        status=[int]$taskResp.StatusCode
        has_errors=[bool]$taskData.errors
        variable_names=@($taskVars.PSObject.Properties.Name)
        required_config=@(foreach($taskName in @('APP_ENV','ADMIN_USERNAME','ADMIN_PASSWORD','ADMIN_TOKEN','CORS_ALLOWED_ORIGINS','MONGODB_URI','MONGODB_PASSWORD','REDIS_URL','STORAGE_BACKEND','TYPESAFE_API_KEY')) { [pscustomobject]@{name=$taskName;present=[bool]$taskVars.$taskName} })
        nonsecret_runtime=@{APP_ENV=$taskVars.APP_ENV;JEV_MODE=$taskVars.JEV_MODE;JEV_MODEL=$taskVars.JEV_MODEL;STORAGE_BACKEND=$taskVars.STORAGE_BACKEND;ENABLE_LOCAL_EMBEDDINGS=$taskVars.ENABLE_LOCAL_EMBEDDINGS;PORT=$taskVars.PORT}
        configured_dockerfile=$(if ([string]$taskVars.RAILWAY_DOCKERFILE_PATH -match '^[a-zA-Z0-9_./-]{1,180}$') { [string]$taskVars.RAILWAY_DOCKERFILE_PATH } else { '[not confirmed]' })
        log_count=$taskLogs.Count
        failure_indicators=@{
            out_of_memory=($taskMessages -match 'out of memory|OOM')
            missing_start_command=($taskMessages -match 'No start command|failed to determine|could not find.*start')
            build_failed=($taskMessages -match 'build failed|failed to build|Dockerfile.*not found')
            auth_or_repo_failure=($taskMessages -match 'not authorized|unauthorized|repository not found')
            billing_or_credit=($taskMessages -match 'credit|billing|subscription|usage limit')
            missing_required_configuration=($taskMessages -match 'ADMIN_|CORS_ALLOWED_ORIGINS|MONGODB_|RuntimeError')
            dockerfile_read_failed=($taskMessages -match 'failed to read dockerfile|[Dd]ockerfile.*not found|[Dd]ockerfile.*no such file|[Dd]ockerfile.*does not exist')
            copy_source_missing=($taskMessages -match 'COPY.*not found|failed to calculate checksum|failed to compute cache key')
            unsupported_builder=($taskMessages -match 'unsupported.*builder|unknown.*builder')
            plan_generation_failed=($taskMessages -match 'failed to generate.*plan|could not.*build plan')
        }
    } | ConvertTo-Json -Depth 6
} catch {
    [pscustomobject]@{status='not_confirmed';error_type=$_.Exception.GetType().Name} | ConvertTo-Json
    exit 2
} finally { $taskClient.Dispose() }

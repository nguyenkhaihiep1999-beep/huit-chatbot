param([string]$ProjectId = '18aa08f0-352d-4248-ad54-8cda262cf410', [string]$EnvironmentId = '6b6eb395-9851-4f6c-952d-794f669f3fb4')
$ErrorActionPreference = 'Stop'
$taskConfig = Get-Content -LiteralPath 'C:\Users\LOQ\.railway\config.json' -Raw | ConvertFrom-Json
$taskClient = [System.Net.Http.HttpClient]::new()
$taskClient.Timeout = [TimeSpan]::FromSeconds(20)
$taskClient.DefaultRequestHeaders.Authorization = [System.Net.Http.Headers.AuthenticationHeaderValue]::new('Bearer', $taskConfig.user.accessToken)
function Invoke-TargetQuery([string]$Query, [hashtable]$Variables = @{}) {
    $taskBody = @{query=$Query;variables=$Variables} | ConvertTo-Json -Depth 8 -Compress
    $taskContent = [System.Net.Http.StringContent]::new($taskBody, [System.Text.Encoding]::UTF8, 'application/json')
    try {
        $taskResponse = $taskClient.PostAsync('https://backboard.railway.com/graphql/v2', $taskContent).GetAwaiter().GetResult()
        $taskParsed = $taskResponse.Content.ReadAsStringAsync().GetAwaiter().GetResult() | ConvertFrom-Json
        if (-not $taskResponse.IsSuccessStatusCode -or $taskParsed.errors) { throw 'Railway metadata query failed; raw errors suppressed.' }
        return $taskParsed.data
    } finally { $taskContent.Dispose() }
}
try {
    $taskSchema = Invoke-TargetQuery 'query { source: __type(name: "ServiceSource") { fields { name } } deployment: __type(name: "Deployment") { fields { name } } instance: __type(name: "ServiceInstance") { fields { name } } }'
    $taskSourceFields = @('repo','branch','image') | Where-Object { $_ -in $taskSchema.source.fields.name }
    $taskDeployFields = @('id','status','createdAt','updatedAt') | Where-Object { $_ -in $taskSchema.deployment.fields.name }
    $taskInstanceFields = @('serviceId','environmentId','rootDirectory','dockerfilePath','startCommand','healthcheckPath','numReplicas','sleepApplication','hasEverDeployed') | Where-Object { $_ -in $taskSchema.instance.fields.name }
    $taskSourceSelection = if ($taskSourceFields.Count) { $taskSourceFields -join ' ' } else { '__typename' }
    $taskQuery = 'query inspect($serviceId: String!, $environmentId: String!) { serviceInstance(serviceId: $serviceId, environmentId: $environmentId) { ' + ($taskInstanceFields -join ' ') + ' source { ' + $taskSourceSelection + ' } latestDeployment { ' + ($taskDeployFields -join ' ') + ' } activeDeployments { ' + ($taskDeployFields -join ' ') + ' } } }'
    foreach ($taskServiceId in @('08528560-6b76-479c-838e-ddd1f77d2dad','9217966a-82c4-4947-9bf2-31834a607500')) {
        $taskResult = (Invoke-TargetQuery $taskQuery @{serviceId=$taskServiceId;environmentId=$EnvironmentId}).serviceInstance
        [pscustomobject]@{
            projectId=$ProjectId
            serviceId=$taskServiceId
            environmentId=$EnvironmentId
            rootDirectory=$taskResult.rootDirectory
            dockerfilePath=$taskResult.dockerfilePath
            hasStartCommand=[bool]$taskResult.startCommand
            startCommandUsesHuitApi=([string]$taskResult.startCommand -match 'backend\.app\.main:app')
            healthcheckPath=$taskResult.healthcheckPath
            numReplicas=$taskResult.numReplicas
            sleepApplication=$taskResult.sleepApplication
            hasEverDeployed=$taskResult.hasEverDeployed
            sourceRepo=([string]$taskResult.source.repo -replace '://[^/@]+@','://[redacted]@' -replace '[?].*$','')
            sourceBranch=$taskResult.source.branch
            hasImageSource=[bool]$taskResult.source.image
            latestDeployment=$taskResult.latestDeployment
            activeDeployments=$taskResult.activeDeployments
        } | ConvertTo-Json -Depth 6
    }
} catch {
    [pscustomobject]@{status='not_confirmed';error_type=$_.Exception.GetType().Name} | ConvertTo-Json
    exit 2
} finally { $taskClient.Dispose() }

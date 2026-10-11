$ErrorActionPreference = "Stop"

$launcher = Get-Command py -ErrorAction SilentlyContinue
if ($launcher) {
    $python = "py"
    $pythonArgs = @("-3.12")
} else {
    $launcher = Get-Command python -ErrorAction SilentlyContinue
    if (-not $launcher) {
        throw "Python 3.12 is required. Install Python, then run this script again."
    }
    $python = "python"
    $pythonArgs = @()
}

& $python @pythonArgs --version
if ($LASTEXITCODE -ne 0) {
    throw "Could not start Python 3.12."
}

$stages = @(
    "pipeline/01_read_source.py",
    "pipeline/02_data_extraction.py",
    "pipeline/03_weightage_assessment.py",
    "pipeline/04_lead_notification.py",
    "pipeline/05_auditing_record.py"
)

foreach ($stage in $stages) {
    Write-Host "Running $stage"
    & $python @pythonArgs $stage
    if ($LASTEXITCODE -ne 0) {
        throw "Pipeline stopped because $stage failed with exit code $LASTEXITCODE."
    }
}

Write-Host "Pipeline complete. Results are in the output/ directory."

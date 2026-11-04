$ErrorActionPreference = "Stop"

$docker = Get-Command docker -ErrorAction SilentlyContinue
if (-not $docker) {
    throw "Docker was not found. Install and start Docker Desktop, then rerun this script."
}

docker info *> $null
if ($LASTEXITCODE -ne 0) {
    throw "Docker Desktop is installed but its engine is not running. Start Docker Desktop and rerun this script."
}

$dataPath = Join-Path $PSScriptRoot "data"
$pbfPath = Join-Path $dataPath "central-zone-latest.osm.pbf"
$image = "osrm/osrm-backend:latest"
$composeFile = Join-Path $PSScriptRoot "docker-compose.yml"
$downloadUrl = "https://download.geofabrik.de/asia/india/central-zone-latest.osm.pbf"

New-Item -ItemType Directory -Force -Path $dataPath | Out-Null

if (-not (Test-Path -LiteralPath $pbfPath)) {
    Write-Host "Downloading the Geofabrik Central Zone OSM extract (about 335 MB)..."
    Invoke-WebRequest -Uri $downloadUrl -OutFile $pbfPath
}

Write-Host "Pulling the OSRM Docker image..."
docker pull $image
if ($LASTEXITCODE -ne 0) {
    throw "Could not download the OSRM Docker image."
}

$mount = "type=bind,source=$dataPath,target=/data"
$osrmFilesExist = Test-Path -LiteralPath (Join-Path $dataPath "central-zone-latest.osrm")
if (-not $osrmFilesExist) {
    Write-Host "Preparing the OSM road graph. This may take a while and needs several GB of free disk space and memory..."
    docker run --rm -t --mount $mount $image osrm-extract -p /opt/car.lua /data/central-zone-latest.osm.pbf
    if ($LASTEXITCODE -ne 0) {
        throw "OSRM extract preprocessing failed."
    }

    docker run --rm -t --mount $mount $image osrm-partition /data/central-zone-latest.osrm
    if ($LASTEXITCODE -ne 0) {
        throw "OSRM partition preprocessing failed."
    }

    docker run --rm -t --mount $mount $image osrm-customize /data/central-zone-latest.osrm
    if ($LASTEXITCODE -ne 0) {
        throw "OSRM customization failed."
    }
}

Write-Host "Starting self-hosted OSRM at http://127.0.0.1:5000 ..."
docker compose -f $composeFile up -d
if ($LASTEXITCODE -ne 0) {
    throw "Could not start OSRM with Docker Compose."
}

$ready = $false
for ($attempt = 0; $attempt -lt 30; $attempt++) {
    try {
        $response = Invoke-RestMethod -Uri "http://127.0.0.1:5000/route/v1/driving/78.2241242,21.0080057;78.2335817,20.9977617?overview=false" -TimeoutSec 5
        if ($response.code -eq "Ok") {
            $ready = $true
            break
        }
    } catch {
        Start-Sleep -Seconds 2
    }
}

if (-not $ready) {
    throw "The OSRM container started but did not become ready. Check it with: docker compose -f `"$composeFile`" logs"
}

Write-Host "Self-hosted OSRM is ready. The backend now defaults to this local service."

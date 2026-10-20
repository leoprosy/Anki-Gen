# build_llama_vulkan.ps1 — Remplace la roue llama-cpp-python processeur par une roue Vulkan.
#
# Aucun index ne publie de roue Windows récente avec GPU : on la compile, à la
# version de requirements.txt, avec le SDK Vulkan de LunarG. Vulkan tourne sur
# les cartes NVIDIA, AMD et Intel ; sans carte, llama.cpp reste sur le processeur.
# Le chargeur vulkan-1.dll redistribuable est posé dans build/vulkan-loader :
# flask-server.spec l'embarque en secours (voir local_llm.py).
#
#   pwsh scripts/build_llama_vulkan.ps1      (dans l'environnement Python du build)
#
# La roue est gardée dans build/llama-vulkan : les workflows la mettent en cache.
param([string]$SdkVersion = "1.4.363.0")
$ErrorActionPreference = "Stop"

$llama = (Select-String -Path requirements.txt -Pattern '^llama_cpp_python==(\S+)').Matches[0].Groups[1].Value
$wheels = "build/llama-vulkan"
$wheel = Get-ChildItem $wheels -Filter "llama_cpp_python-$llama-*.whl" -ErrorAction SilentlyContinue | Select-Object -First 1
if (-not $wheel) {
    $sdk = "C:\VulkanSDK\$SdkVersion"
    if (-not (Test-Path "$sdk\Bin\glslc.exe")) {
        $installer = Join-Path ([IO.Path]::GetTempPath()) "vulkansdk.exe"
        Invoke-WebRequest "https://sdk.lunarg.com/sdk/download/$SdkVersion/windows/vulkansdk-windows-X64-$SdkVersion.exe" -OutFile $installer
        Start-Process $installer -Wait -ArgumentList "--root", $sdk, "--accept-licenses", "--default-answer", "--confirm-command", "install"
    }
    $env:VULKAN_SDK = $sdk
    $env:PATH = "$sdk\Bin;$env:PATH"
    # Pas de -march=native : la roue doit tourner sur les processeurs des utilisateurs.
    $env:CMAKE_ARGS = "-DGGML_VULKAN=on -DGGML_NATIVE=off"
    $env:CMAKE_BUILD_PARALLEL_LEVEL = $env:NUMBER_OF_PROCESSORS
    python -m pip wheel "llama_cpp_python==$llama" --no-deps --no-binary llama_cpp_python --no-cache-dir -w $wheels
    if ($LASTEXITCODE) { throw "compilation de llama-cpp-python $llama (Vulkan) en échec" }
    $wheel = Get-ChildItem $wheels -Filter "llama_cpp_python-$llama-*.whl" | Select-Object -First 1
}
python -m pip install --force-reinstall --no-deps $wheel.FullName
if ($LASTEXITCODE) { throw "installation de $($wheel.Name) en échec" }

$loader = "build/vulkan-loader"
if (-not (Test-Path "$loader/vulkan-1.dll")) {
    $zip = Join-Path ([IO.Path]::GetTempPath()) "vulkanrt.zip"
    Invoke-WebRequest "https://sdk.lunarg.com/sdk/download/$SdkVersion/windows/VulkanRT-X64-$SdkVersion-Components.zip" -OutFile $zip
    $unpacked = Join-Path ([IO.Path]::GetTempPath()) "vulkanrt"
    Expand-Archive $zip $unpacked -Force
    New-Item -ItemType Directory -Force $loader | Out-Null
    Copy-Item (Get-ChildItem $unpacked -Recurse -Filter vulkan-1.dll | Where-Object { $_.Directory.Name -eq "x64" }).FullName $loader
    Copy-Item (Get-ChildItem $unpacked -Recurse -Filter VulkanRT-License.txt | Select-Object -First 1).FullName $loader
}
Write-Host "llama-cpp-python $llama (Vulkan) installé ; chargeur dans $loader"

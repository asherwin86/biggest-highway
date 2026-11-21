param([string]$scene = "drive", [int]$frames = 90, [string]$name = $scene, [double]$timescale = 1.0)
Set-Location "E:\bigest highway"
$p = Start-Process -FilePath .\.venv\Scripts\python.exe -ArgumentList "main.py --fresh --shot shots\$name.png --frames $frames --scene $scene --timescale $timescale" -NoNewWindow -PassThru -RedirectStandardOutput shots\out.txt -RedirectStandardError shots\err.txt
if (-not $p.WaitForExit(150000)) { $p.Kill(); "TIMEOUT" }
Get-Content shots\out.txt | Select-String "SHOT|Error|error|Exception" | Select-Object -Last 8
Get-Content shots\err.txt | Select-String -NotMatch "iCCP|prc\(warning\)|pipe|aux display|wglGraphics|ursina.ico|SetForeground" | Select-Object -Last 25

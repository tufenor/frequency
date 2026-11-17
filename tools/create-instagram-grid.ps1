param(
  [Parameter(Mandatory = $true)][string]$Source,
  [Parameter(Mandatory = $true)][string]$OutputDirectory
)

$ErrorActionPreference = 'Stop'
Add-Type -AssemblyName System.Drawing
New-Item -ItemType Directory -Force -Path $OutputDirectory | Out-Null

$labels = @(
  @('FREQUENCY GYM', 'O ritmo certo para sua academia'),
  @('ALUNOS', 'Cadastros simples e completos'),
  @('PLANOS', 'Controle de planos e vencimentos'),
  @('PAGAMENTOS', 'Tudo organizado em um só lugar'),
  @('ACESSOS', 'Entrada rápida e segura'),
  @('DADOS', 'Relatórios para decidir melhor'),
  @('OFFLINE', 'Continue trabalhando mesmo sem internet'),
  @('EM QUALQUER TELA', 'Celular · tablet · desktop'),
  @('EXPERIMENTE', '7 dias para conhecer o Frequency Gym')
)

$sourceImage = [System.Drawing.Image]::FromFile($Source)
try {
  $tileSize = 1080
  $masterSize = $tileSize * 3
  $masterPath = Join-Path $OutputDirectory 'frequency-grid-master.png'
  $master = New-Object System.Drawing.Bitmap($masterSize, $masterSize, [System.Drawing.Imaging.PixelFormat]::Format32bppArgb)
  $masterGraphics = [System.Drawing.Graphics]::FromImage($master)
  try {
    $masterGraphics.InterpolationMode = [System.Drawing.Drawing2D.InterpolationMode]::HighQualityBicubic
    $masterGraphics.SmoothingMode = [System.Drawing.Drawing2D.SmoothingMode]::HighQuality
    $masterGraphics.DrawImage($sourceImage, 0, 0, $masterSize, $masterSize)
    $master.Save($masterPath, [System.Drawing.Imaging.ImageFormat]::Png)
  } finally {
    $masterGraphics.Dispose()
  }

  $titleFont = New-Object System.Drawing.Font('Arial', [float]($tileSize * 0.055), [System.Drawing.FontStyle]::Bold, [System.Drawing.GraphicsUnit]::Pixel)
  $subtitleFont = New-Object System.Drawing.Font('Arial', [float]($tileSize * 0.031), [System.Drawing.FontStyle]::Regular, [System.Drawing.GraphicsUnit]::Pixel)
  $smallFont = New-Object System.Drawing.Font('Arial', [float]($tileSize * 0.022), [System.Drawing.FontStyle]::Bold, [System.Drawing.GraphicsUnit]::Pixel)
  $lime = New-Object System.Drawing.SolidBrush([System.Drawing.Color]::FromArgb(255, 181, 255, 73))
  $cream = New-Object System.Drawing.SolidBrush([System.Drawing.Color]::FromArgb(255, 250, 249, 239))
  $muted = New-Object System.Drawing.SolidBrush([System.Drawing.Color]::FromArgb(235, 250, 249, 239))
  $panel = New-Object System.Drawing.SolidBrush([System.Drawing.Color]::FromArgb(205, 4, 30, 23))
  $accentPen = New-Object System.Drawing.Pen([System.Drawing.Color]::FromArgb(230, 181, 255, 73), [float]($tileSize * 0.008))

  for ($index = 0; $index -lt 9; $index++) {
    $row = [Math]::Floor($index / 3)
    $column = $index % 3
    $tile = New-Object System.Drawing.Bitmap($tileSize, $tileSize, [System.Drawing.Imaging.PixelFormat]::Format32bppArgb)
    $graphics = [System.Drawing.Graphics]::FromImage($tile)
    try {
      $graphics.DrawImage($master, (New-Object System.Drawing.Rectangle(0, 0, $tileSize, $tileSize)), $column * $tileSize, $row * $tileSize, $tileSize, $tileSize, [System.Drawing.GraphicsUnit]::Pixel)
      $panelHeight = [int]($tileSize * 0.25)
      $graphics.FillRectangle($panel, 0, $tileSize - $panelHeight, $tileSize, $panelHeight)
      $graphics.DrawLine($accentPen, [int]($tileSize * 0.07), [int]($tileSize * 0.76), [int]($tileSize * 0.22), [int]($tileSize * 0.76))
      $graphics.DrawString($labels[$index][0], $titleFont, $lime, [int]($tileSize * 0.07), [int]($tileSize * 0.795))
      $graphics.DrawString($labels[$index][1], $subtitleFont, $cream, [int]($tileSize * 0.07), [int]($tileSize * 0.87))
      $number = ('{0:D2}' -f ($index + 1))
      $graphics.DrawString($number, $smallFont, $muted, [int]($tileSize * 0.88), [int]($tileSize * 0.92))
      $path = Join-Path $OutputDirectory (('frequency-grid-{0:D2}.png' -f ($index + 1)))
      $tile.Save($path, [System.Drawing.Imaging.ImageFormat]::Png)
    } finally {
      $graphics.Dispose()
      $tile.Dispose()
    }
  }
  $master.Dispose()
  Write-Output "Criadas 9 peças de $tileSize x $tileSize em $OutputDirectory"
} finally {
  $sourceImage.Dispose()
}

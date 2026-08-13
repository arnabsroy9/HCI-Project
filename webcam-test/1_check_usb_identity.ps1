# =============================================================
#  1_check_usb_identity.ps1
#  Windows-native equivalent of `lsusb | grep 046d:082d`.
#  A genuine Logitech C920 enumerates as VID_046D & PID_082D
#  (some batches: 0892 / 08E5). Counterfeits show a generic
#  "USB Camera" / "PC Camera" with a different vendor ID and
#  do NOT expose manual UVC controls -> your OpenCV CAP_PROP
#  calls will silently fail.
# =============================================================

Write-Host "=== Imaging / camera devices seen by Windows ===" -ForegroundColor Cyan

$cams = Get-PnpDevice -Class 'Camera','Image' -PresentOnly -ErrorAction SilentlyContinue |
        Where-Object { $_.Status -eq 'OK' }

if (-not $cams) {
    Write-Host "No camera devices found. Is it plugged in? Try a different USB port." -ForegroundColor Yellow
    return
}

foreach ($c in $cams) {
    $id = $c.InstanceId
    $vid = if ($id -match 'VID_([0-9A-Fa-f]{4})') { $matches[1].ToUpper() } else { '----' }
    $devpid = if ($id -match 'PID_([0-9A-Fa-f]{4})') { $matches[1].ToUpper() } else { '----' }

    $genuine = ($vid -eq '046D')
    $c920pid = @('082D','0892','08E5') -contains $devpid

    Write-Host ""
    Write-Host ("Name : {0}" -f $c.FriendlyName)
    Write-Host ("VID  : {0}   PID : {1}" -f $vid, $devpid)

    if ($genuine -and $c920pid) {
        Write-Host "VERDICT: Genuine Logitech C920 family (VID 046D). GOOD." -ForegroundColor Green
    } elseif ($genuine) {
        Write-Host "VERDICT: Genuine Logitech (VID 046D) but PID is not a known C920 id. Check the model." -ForegroundColor Yellow
    } else {
        Write-Host "VERDICT: NOT a Logitech vendor id. Likely a counterfeit/generic sensor -> WALK AWAY." -ForegroundColor Red
    }
}
Write-Host ""
Write-Host "(Reference: genuine C920 = VID_046D, PID_082D)" -ForegroundColor DarkGray
